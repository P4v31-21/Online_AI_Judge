import hashlib
import logging
import json
import os
import re
# import shutil
import tempfile
import zipfile
from concurrent.futures import ThreadPoolExecutor, as_completed
from wsgiref.util import FileWrapper

from django.conf import settings
from django.db import transaction
from django.db.models import Q
from django.http import StreamingHttpResponse, FileResponse

from account.decorators import problem_permission_required, ensure_created_by
from contest.models import Contest, ContestStatus
from fps.parser import FPSHelper, FPSParser
from judge.dispatcher import SPJCompiler
from options.options import SysOptions
from submission.models import Submission, JudgeStatus
from utils.api import APIView, CSRFExemptAPIView, validate_serializer, APIError
from utils.constants import Difficulty
from utils.shortcuts import rand_str, natural_sort_key
from utils.tasks import delete_files
from ..models import Problem, ProblemRuleType, ProblemTag
from ..serializers import (CreateContestProblemSerializer, CompileSPJSerializer,
                           CreateProblemSerializer, EditProblemSerializer, EditContestProblemSerializer,
                           ProblemAdminSerializer, TestCaseUploadForm, ContestProblemMakePublicSerializer,
                           AddContestProblemSerializer, ExportProblemSerializer,
                           ExportProblemRequestSerialzier, UploadProblemForm, ImportProblemSerializer,
                           FPSProblemSerializer, AIGenerateProblemSerializer, AISaveProblemSerializer,
                           AIBatchGenerateProblemSerializer)
from ..utils import TEMPLATE_BASE, build_problem_template


class TestCaseZipProcessor(object):
    def process_zip(self, uploaded_zip_file, spj, dir=""):
        try:
            zip_file = zipfile.ZipFile(uploaded_zip_file, "r")
        except zipfile.BadZipFile:
            raise APIError("Bad zip file")
        name_list = zip_file.namelist()
        test_case_list = self.filter_name_list(name_list, spj=spj, dir=dir)
        if not test_case_list:
            raise APIError("Empty file")

        test_case_id = rand_str()
        test_case_dir = os.path.join(settings.TEST_CASE_DIR, test_case_id)
        os.mkdir(test_case_dir)
        os.chmod(test_case_dir, 0o710)

        size_cache = {}
        md5_cache = {}

        for item in test_case_list:
            with open(os.path.join(test_case_dir, item), "wb") as f:
                # 防御 Zip Bomb: 检查解压前声明的文件原始大小，若大于 32MB 直接拒绝
                item_info = zip_file.getinfo(f"{dir}{item}")
                if item_info.file_size > 32 * 1024 * 1024:
                    raise APIError(f"Test case file {item} is too large (max 32MB allowed).")
                
                content = zip_file.read(f"{dir}{item}").replace(b"\r\n", b"\n")
                size_cache[item] = len(content)
                if item.endswith(".out"):
                    md5_cache[item] = hashlib.md5(content.rstrip()).hexdigest()
                f.write(content)
        test_case_info = {"spj": spj, "test_cases": {}}

        info = []

        if spj:
            for index, item in enumerate(test_case_list):
                data = {"input_name": item, "input_size": size_cache[item]}
                info.append(data)
                test_case_info["test_cases"][str(index + 1)] = data
        else:
            # ["1.in", "1.out", "2.in", "2.out"] => [("1.in", "1.out"), ("2.in", "2.out")]
            test_case_list = zip(*[test_case_list[i::2] for i in range(2)])
            for index, item in enumerate(test_case_list):
                data = {"stripped_output_md5": md5_cache[item[1]],
                        "input_size": size_cache[item[0]],
                        "output_size": size_cache[item[1]],
                        "input_name": item[0],
                        "output_name": item[1]}
                info.append(data)
                test_case_info["test_cases"][str(index + 1)] = data

        with open(os.path.join(test_case_dir, "info"), "w", encoding="utf-8") as f:
            f.write(json.dumps(test_case_info, indent=4))

        for item in os.listdir(test_case_dir):
            os.chmod(os.path.join(test_case_dir, item), 0o640)

        return info, test_case_id

    def filter_name_list(self, name_list, spj, dir=""):
        ret = []
        prefix = 1
        if spj:
            while True:
                in_name = f"{prefix}.in"
                if f"{dir}{in_name}" in name_list:
                    ret.append(in_name)
                    prefix += 1
                    continue
                else:
                    return sorted(ret, key=natural_sort_key)
        else:
            while True:
                in_name = f"{prefix}.in"
                out_name = f"{prefix}.out"
                if f"{dir}{in_name}" in name_list and f"{dir}{out_name}" in name_list:
                    ret.append(in_name)
                    ret.append(out_name)
                    prefix += 1
                    continue
                else:
                    return sorted(ret, key=natural_sort_key)


class TestCaseAPI(CSRFExemptAPIView, TestCaseZipProcessor):
    request_parsers = ()

    def get(self, request):
        problem_id = request.GET.get("problem_id")
        if not problem_id:
            return self.error("Parameter error, problem_id is required")
        try:
            problem = Problem.objects.get(id=problem_id)
        except Problem.DoesNotExist:
            return self.error("Problem does not exists")

        if problem.contest:
            ensure_created_by(problem.contest, request.user)
        else:
            ensure_created_by(problem, request.user)

        test_case_dir = os.path.join(settings.TEST_CASE_DIR, problem.test_case_id)
        if not os.path.isdir(test_case_dir):
            return self.error("Test case does not exists")
        name_list = self.filter_name_list(os.listdir(test_case_dir), problem.spj)
        name_list.append("info")
        file_name = os.path.join(test_case_dir, problem.test_case_id + ".zip")
        with zipfile.ZipFile(file_name, "w") as file:
            for test_case in name_list:
                file.write(f"{test_case_dir}/{test_case}", test_case)
        response = StreamingHttpResponse(FileWrapper(open(file_name, "rb")),
                                         content_type="application/octet-stream")

        response["Content-Disposition"] = f"attachment; filename=problem_{problem.id}_test_cases.zip"
        response["Content-Length"] = os.path.getsize(file_name)
        return response

    def post(self, request):
        form = TestCaseUploadForm(request.POST, request.FILES)
        if form.is_valid():
            spj = form.cleaned_data["spj"] == "true"
            file = form.cleaned_data["file"]
        else:
            return self.error("Upload failed")
        zip_file = f"/tmp/{rand_str()}.zip"
        with open(zip_file, "wb") as f:
            for chunk in file:
                f.write(chunk)
        info, test_case_id = self.process_zip(zip_file, spj=spj)
        os.remove(zip_file)
        return self.success({"id": test_case_id, "info": info, "spj": spj})


class CompileSPJAPI(APIView):
    @validate_serializer(CompileSPJSerializer)
    def post(self, request):
        data = request.data

        if not data.get("samples"):
            sample_input = data.get("sample_input", "")
            sample_output = data.get("sample_output", "")
            if sample_input or sample_output:
                data["samples"] = [{"input": sample_input, "output": sample_output}]
            else:
                return self.error("samples: This field is required.")
        spj_version = rand_str(8)
        error = SPJCompiler(data["spj_code"], spj_version, data["spj_language"]).compile_spj()
        if error:
            return self.error(error)
        else:
            return self.success()


class ProblemBase(APIView):
    def common_checks(self, request):
        data = request.data
        if data["spj"]:
            if not data["spj_language"] or not data["spj_code"]:
                return "Invalid spj"
            if not data["spj_compile_ok"]:
                return "SPJ code must be compiled successfully"
            data["spj_version"] = hashlib.md5(
                (data["spj_language"] + ":" + data["spj_code"]).encode("utf-8")).hexdigest()
        else:
            data["spj_language"] = None
            data["spj_code"] = None
        if data["rule_type"] == ProblemRuleType.OI:
            total_score = 0
            for item in data["test_case_score"]:
                if item["score"] <= 0:
                    return "Invalid score"
                else:
                    total_score += item["score"]
            data["total_score"] = total_score
        data["languages"] = list(data["languages"])


class ProblemAPI(ProblemBase):
    @problem_permission_required
    @validate_serializer(CreateProblemSerializer)
    def post(self, request):
        data = request.data
        _id = data["_id"]
        if not _id:
            return self.error("Display ID is required")
        if Problem.objects.filter(_id=_id, contest_id__isnull=True).exists():
            return self.error("Display ID already exists")

        error_info = self.common_checks(request)
        if error_info:
            return self.error(error_info)

        # todo check filename and score info
        tags = data.pop("tags")
        data["created_by"] = request.user
        problem = Problem.objects.create(**data)

        for item in tags:
            try:
                tag = ProblemTag.objects.get(name=item)
            except ProblemTag.DoesNotExist:
                tag = ProblemTag.objects.create(name=item)
            problem.tags.add(tag)
        return self.success(ProblemAdminSerializer(problem).data)

    @problem_permission_required
    def get(self, request):
        problem_id = request.GET.get("id")
        rule_type = request.GET.get("rule_type")
        user = request.user
        if problem_id:
            try:
                problem = Problem.objects.get(id=problem_id)
                ensure_created_by(problem, request.user)
                return self.success(ProblemAdminSerializer(problem).data)
            except Problem.DoesNotExist:
                return self.error("Problem does not exist")

        problems = Problem.objects.filter(contest_id__isnull=True).order_by("-create_time")
        if rule_type:
            if rule_type not in ProblemRuleType.choices():
                return self.error("Invalid rule_type")
            else:
                problems = problems.filter(rule_type=rule_type)

        keyword = request.GET.get("keyword", "").strip()
        if keyword:
            problems = problems.filter(Q(title__icontains=keyword) | Q(_id__icontains=keyword))
        if not user.can_mgmt_all_problem():
            problems = problems.filter(created_by=user)
        return self.success(self.paginate_data(request, problems, ProblemAdminSerializer))

    @problem_permission_required
    @validate_serializer(EditProblemSerializer)
    def put(self, request):
        data = request.data
        problem_id = data.pop("id")

        try:
            problem = Problem.objects.get(id=problem_id)
            ensure_created_by(problem, request.user)
        except Problem.DoesNotExist:
            return self.error("Problem does not exist")

        _id = data["_id"]
        if not _id:
            return self.error("Display ID is required")
        if Problem.objects.exclude(id=problem_id).filter(_id=_id, contest_id__isnull=True).exists():
            return self.error("Display ID already exists")

        error_info = self.common_checks(request)
        if error_info:
            return self.error(error_info)
        # todo check filename and score info
        tags = data.pop("tags")
        data["languages"] = list(data["languages"])

        for k, v in data.items():
            setattr(problem, k, v)
        problem.save()

        problem.tags.remove(*problem.tags.all())
        for tag in tags:
            try:
                tag = ProblemTag.objects.get(name=tag)
            except ProblemTag.DoesNotExist:
                tag = ProblemTag.objects.create(name=tag)
            problem.tags.add(tag)

        return self.success()

    @problem_permission_required
    def delete(self, request):
        id = request.GET.get("id")
        if not id:
            return self.error("Invalid parameter, id is required")
        try:
            problem = Problem.objects.get(id=id, contest_id__isnull=True)
        except Problem.DoesNotExist:
            return self.error("Problem does not exists")
        ensure_created_by(problem, request.user)
        # d = os.path.join(settings.TEST_CASE_DIR, problem.test_case_id)
        # if os.path.isdir(d):
        #     shutil.rmtree(d, ignore_errors=True)
        problem.delete()
        return self.success()


class ContestProblemAPI(ProblemBase):
    @validate_serializer(CreateContestProblemSerializer)
    def post(self, request):
        data = request.data
        try:
            contest = Contest.objects.get(id=data.pop("contest_id"))
            ensure_created_by(contest, request.user)
        except Contest.DoesNotExist:
            return self.error("Contest does not exist")

        if data["rule_type"] != contest.rule_type:
            return self.error("Invalid rule type")

        _id = data["_id"]
        if not _id:
            return self.error("Display ID is required")

        if Problem.objects.filter(_id=_id, contest=contest).exists():
            return self.error("Duplicate Display id")

        error_info = self.common_checks(request)
        if error_info:
            return self.error(error_info)

        # todo check filename and score info
        data["contest"] = contest
        tags = data.pop("tags")
        data["created_by"] = request.user
        problem = Problem.objects.create(**data)

        for item in tags:
            try:
                tag = ProblemTag.objects.get(name=item)
            except ProblemTag.DoesNotExist:
                tag = ProblemTag.objects.create(name=item)
            problem.tags.add(tag)
        return self.success(ProblemAdminSerializer(problem).data)

    def get(self, request):
        problem_id = request.GET.get("id")
        contest_id = request.GET.get("contest_id")
        user = request.user
        if problem_id:
            try:
                problem = Problem.objects.get(id=problem_id)
                ensure_created_by(problem.contest, user)
            except Problem.DoesNotExist:
                return self.error("Problem does not exist")
            return self.success(ProblemAdminSerializer(problem).data)

        if not contest_id:
            return self.error("Contest id is required")
        try:
            contest = Contest.objects.get(id=contest_id)
            ensure_created_by(contest, user)
        except Contest.DoesNotExist:
            return self.error("Contest does not exist")
        problems = Problem.objects.filter(contest=contest).order_by("-create_time")
        if user.is_admin():
            problems = problems.filter(contest__created_by=user)
        keyword = request.GET.get("keyword")
        if keyword:
            problems = problems.filter(title__contains=keyword)
        return self.success(self.paginate_data(request, problems, ProblemAdminSerializer))

    @validate_serializer(EditContestProblemSerializer)
    def put(self, request):
        data = request.data
        user = request.user

        try:
            contest = Contest.objects.get(id=data.pop("contest_id"))
            ensure_created_by(contest, user)
        except Contest.DoesNotExist:
            return self.error("Contest does not exist")

        if data["rule_type"] != contest.rule_type:
            return self.error("Invalid rule type")

        problem_id = data.pop("id")

        try:
            problem = Problem.objects.get(id=problem_id, contest=contest)
        except Problem.DoesNotExist:
            return self.error("Problem does not exist")

        _id = data["_id"]
        if not _id:
            return self.error("Display ID is required")
        if Problem.objects.exclude(id=problem_id).filter(_id=_id, contest=contest).exists():
            return self.error("Display ID already exists")

        error_info = self.common_checks(request)
        if error_info:
            return self.error(error_info)
        # todo check filename and score info
        tags = data.pop("tags")
        data["languages"] = list(data["languages"])

        for k, v in data.items():
            setattr(problem, k, v)
        problem.save()

        problem.tags.remove(*problem.tags.all())
        for tag in tags:
            try:
                tag = ProblemTag.objects.get(name=tag)
            except ProblemTag.DoesNotExist:
                tag = ProblemTag.objects.create(name=tag)
            problem.tags.add(tag)
        return self.success()

    def delete(self, request):
        id = request.GET.get("id")
        if not id:
            return self.error("Invalid parameter, id is required")
        try:
            problem = Problem.objects.get(id=id, contest_id__isnull=False)
        except Problem.DoesNotExist:
            return self.error("Problem does not exists")
        ensure_created_by(problem.contest, request.user)
        if Submission.objects.filter(problem=problem).exists():
            return self.error("Can't delete the problem as it has submissions")
        # d = os.path.join(settings.TEST_CASE_DIR, problem.test_case_id)
        # if os.path.isdir(d):
        #    shutil.rmtree(d, ignore_errors=True)
        problem.delete()
        return self.success()


class MakeContestProblemPublicAPIView(APIView):
    @validate_serializer(ContestProblemMakePublicSerializer)
    @problem_permission_required
    def post(self, request):
        data = request.data
        display_id = data.get("display_id")
        if Problem.objects.filter(_id=display_id, contest_id__isnull=True).exists():
            return self.error("Duplicate display ID")

        try:
            problem = Problem.objects.get(id=data["id"])
        except Problem.DoesNotExist:
            return self.error("Problem does not exist")

        if not problem.contest or problem.is_public:
            return self.error("Already be a public problem")
        problem.is_public = True
        problem.save()
        # https://docs.djangoproject.com/en/1.11/topics/db/queries/#copying-model-instances
        tags = problem.tags.all()
        problem.pk = None
        problem.contest = None
        problem._id = display_id
        problem.visible = False
        problem.submission_number = problem.accepted_number = 0
        problem.statistic_info = {}
        problem.save()
        problem.tags.set(tags)
        return self.success()


class AddContestProblemAPI(APIView):
    @validate_serializer(AddContestProblemSerializer)
    def post(self, request):
        data = request.data
        try:
            contest = Contest.objects.get(id=data["contest_id"])
            problem = Problem.objects.get(id=data["problem_id"])
        except (Contest.DoesNotExist, Problem.DoesNotExist):
            return self.error("Contest or Problem does not exist")

        if contest.status == ContestStatus.CONTEST_ENDED:
            return self.error("Contest has ended")
        if Problem.objects.filter(contest=contest, _id=data["display_id"]).exists():
            return self.error("Duplicate display id in this contest")

        tags = problem.tags.all()
        problem.pk = None
        problem.contest = contest
        problem.is_public = True
        problem.visible = True
        problem._id = request.data["display_id"]
        problem.submission_number = problem.accepted_number = 0
        problem.statistic_info = {}
        problem.save()
        problem.tags.set(tags)
        return self.success()


class ExportProblemAPI(APIView):
    def choose_answers(self, user, problem):
        ret = []
        for item in problem.languages:
            submission = Submission.objects.filter(problem=problem,
                                                   user_id=user.id,
                                                   language=item,
                                                   result=JudgeStatus.ACCEPTED).order_by("-create_time").first()
            if submission:
                ret.append({"language": submission.language, "code": submission.code})
        return ret

    def process_one_problem(self, zip_file, user, problem, index):
        info = ExportProblemSerializer(problem).data
        info["answers"] = self.choose_answers(user, problem=problem)
        compression = zipfile.ZIP_DEFLATED
        zip_file.writestr(zinfo_or_arcname=f"{index}/problem.json",
                          data=json.dumps(info, indent=4),
                          compress_type=compression)
        problem_test_case_dir = os.path.join(settings.TEST_CASE_DIR, problem.test_case_id)
        with open(os.path.join(problem_test_case_dir, "info")) as f:
            info = json.load(f)
        for k, v in info["test_cases"].items():
            zip_file.write(filename=os.path.join(problem_test_case_dir, v["input_name"]),
                           arcname=f"{index}/testcase/{v['input_name']}",
                           compress_type=compression)
            if not info["spj"]:
                zip_file.write(filename=os.path.join(problem_test_case_dir, v["output_name"]),
                               arcname=f"{index}/testcase/{v['output_name']}",
                               compress_type=compression)

    @validate_serializer(ExportProblemRequestSerialzier)
    def get(self, request):
        problems = Problem.objects.filter(id__in=request.data["problem_id"])
        for problem in problems:
            if problem.contest:
                ensure_created_by(problem.contest, request.user)
            else:
                ensure_created_by(problem, request.user)
        path = f"/tmp/{rand_str()}.zip"
        with zipfile.ZipFile(path, "w") as zip_file:
            for index, problem in enumerate(problems):
                self.process_one_problem(zip_file=zip_file, user=request.user, problem=problem, index=index + 1)
        delete_files.send_with_options(args=(path,), delay=300_000)
        resp = FileResponse(open(path, "rb"))
        resp["Content-Type"] = "application/zip"
        resp["Content-Disposition"] = "attachment;filename=problem-export.zip"
        return resp


class ImportProblemAPI(CSRFExemptAPIView, TestCaseZipProcessor):
    request_parsers = ()

    def post(self, request):
        form = UploadProblemForm(request.POST, request.FILES)
        if form.is_valid():
            file = form.cleaned_data["file"]
            tmp_file = f"/tmp/{rand_str()}.zip"
            with open(tmp_file, "wb") as f:
                for chunk in file:
                    f.write(chunk)
        else:
            return self.error("Upload failed")

        count = 0
        with zipfile.ZipFile(tmp_file, "r") as zip_file:
            name_list = zip_file.namelist()
            for item in name_list:
                if "/problem.json" in item:
                    count += 1
            with transaction.atomic():
                for i in range(1, count + 1):
                    with zip_file.open(f"{i}/problem.json") as f:
                        problem_info = json.load(f)
                        serializer = ImportProblemSerializer(data=problem_info)
                        if not serializer.is_valid():
                            return self.error(f"Invalid problem format, error is {serializer.errors}")
                        else:
                            problem_info = serializer.data
                            for item in problem_info["template"].keys():
                                if item not in SysOptions.language_names:
                                    return self.error(f"Unsupported language {item}")

                        problem_info["display_id"] = problem_info["display_id"][:24]
                        for k, v in problem_info["template"].items():
                            problem_info["template"][k] = build_problem_template(v["prepend"], v["template"],
                                                                                 v["append"])

                        spj = problem_info["spj"] is not None
                        rule_type = problem_info["rule_type"]
                        test_case_score = problem_info["test_case_score"]

                        # process test case
                        _, test_case_id = self.process_zip(tmp_file, spj=spj, dir=f"{i}/testcase/")

                        problem_obj = Problem.objects.create(_id=problem_info["display_id"],
                                                             title=problem_info["title"],
                                                             description=problem_info["description"]["value"],
                                                             input_description=problem_info["input_description"][
                                                                 "value"],
                                                             output_description=problem_info["output_description"][
                                                                 "value"],
                                                             hint=problem_info["hint"]["value"],
                                                             test_case_score=test_case_score if test_case_score else [],
                                                             time_limit=problem_info["time_limit"],
                                                             memory_limit=problem_info["memory_limit"],
                                                             samples=problem_info["samples"],
                                                             template=problem_info["template"],
                                                             rule_type=problem_info["rule_type"],
                                                             source=problem_info["source"],
                                                             spj=spj,
                                                             spj_code=problem_info["spj"]["code"] if spj else None,
                                                             spj_language=problem_info["spj"][
                                                                 "language"] if spj else None,
                                                             spj_version=rand_str(8) if spj else "",
                                                             languages=SysOptions.language_names,
                                                             created_by=request.user,
                                                             visible=False,
                                                             difficulty=Difficulty.MID,
                                                             total_score=sum(item["score"] for item in test_case_score)
                                                             if rule_type == ProblemRuleType.OI else 0,
                                                             test_case_id=test_case_id
                                                             )
                        for tag_name in problem_info["tags"]:
                            tag_obj, _ = ProblemTag.objects.get_or_create(name=tag_name)
                            problem_obj.tags.add(tag_obj)
        return self.success({"import_count": count})


class FPSProblemImport(CSRFExemptAPIView):
    request_parsers = ()

    def _create_problem(self, problem_data, creator):
        if problem_data["time_limit"]["unit"] == "ms":
            time_limit = problem_data["time_limit"]["value"]
        else:
            time_limit = problem_data["time_limit"]["value"] * 1000
        template = {}
        prepend = {}
        append = {}
        for t in problem_data["prepend"]:
            prepend[t["language"]] = t["code"]
        for t in problem_data["append"]:
            append[t["language"]] = t["code"]
        for t in problem_data["template"]:
            our_lang = lang = t["language"]
            if lang == "Python":
                our_lang = "Python3"
            template[our_lang] = TEMPLATE_BASE.format(prepend.get(lang, ""), t["code"], append.get(lang, ""))
        spj = problem_data["spj"] is not None
        Problem.objects.create(_id=f"fps-{rand_str(4)}",
                               title=problem_data["title"],
                               description=problem_data["description"],
                               input_description=problem_data["input"],
                               output_description=problem_data["output"],
                               hint=problem_data["hint"],
                               test_case_score=problem_data["test_case_score"],
                               time_limit=time_limit,
                               memory_limit=problem_data["memory_limit"]["value"],
                               samples=problem_data["samples"],
                               template=template,
                               rule_type=ProblemRuleType.ACM,
                               source=problem_data.get("source", ""),
                               spj=spj,
                               spj_code=problem_data["spj"]["code"] if spj else None,
                               spj_language=problem_data["spj"]["language"] if spj else None,
                               spj_version=rand_str(8) if spj else "",
                               visible=False,
                               languages=SysOptions.language_names,
                               created_by=creator,
                               difficulty=Difficulty.MID,
                               test_case_id=problem_data["test_case_id"])

    def post(self, request):
        form = UploadProblemForm(request.POST, request.FILES)
        if form.is_valid():
            file = form.cleaned_data["file"]
            with tempfile.NamedTemporaryFile("wb") as tf:
                for chunk in file.chunks(4096):
                    tf.file.write(chunk)

                tf.file.flush()
                os.fsync(tf.file)

                problems = FPSParser(tf.name).parse()
        else:
            return self.error("Parse upload file error")

        helper = FPSHelper()
        with transaction.atomic():
            for _problem in problems:
                test_case_id = rand_str()
                test_case_dir = os.path.join(settings.TEST_CASE_DIR, test_case_id)
                os.mkdir(test_case_dir)
                score = []
                for item in helper.save_test_case(_problem, test_case_dir)["test_cases"].values():
                    score.append({"score": 0, "input_name": item["input_name"],
                                  "output_name": item.get("output_name")})
                problem_data = helper.save_image(_problem, settings.UPLOAD_DIR, settings.UPLOAD_PREFIX)
                s = FPSProblemSerializer(data=problem_data)
                if not s.is_valid():
                    return self.error(f"Parse FPS file error: {s.errors}")
                problem_data = s.data
                problem_data["test_case_id"] = test_case_id
                problem_data["test_case_score"] = score
                self._create_problem(problem_data, request.user)
        return self.success({"import_count": len(problems)})


class AIProblemMixin(object):
    AI_API_BASE_URL_DEFAULT = "https://api.siliconflow.cn/v1"
    AI_MODEL_DEFAULT = "Pro/zai-org/GLM-5.1"
    AI_TIMEOUT = 300

    @staticmethod
    def check_ai_api_configured():
        """检查 AI API 是否已配置。如果未配置，抛出 APIError。"""
        api_key = os.environ.get("AI_API_KEY") or os.environ.get("SILICONFLOW_API_KEY")
        if not api_key:
            raise APIError("AI API is not configured. Please set AI_API_KEY or SILICONFLOW_API_KEY environment variable.")

    # 前端显示名 → AI API 真实模型 ID 的映射
    # 前端用户选择 "DeepSeek V3.2"，后端转成 API 所需的 "deepseek-ai/DeepSeek-V3.2"
    # 新增模型只需改这个字典一个地方
    MODEL_NAME_MAP = {
        "DeepSeek V3.2": "deepseek-ai/DeepSeek-V3.2",
        "DeepSeek R1": "deepseek-ai/DeepSeek-R1",
        "GLM-5.1 Pro": "Pro/zai-org/GLM-5.1",
    }

    @classmethod
    def _resolve_model(cls, frontend_name):
        """
        将前端传入的模型显示名解析为真实的 API 模型 ID。
        优先级：
          1. 前端传了完整 ID（含 '/'）→ 直接使用
          2. 前端传了显示名 → 按 MODEL_NAME_MAP 映射
          3. 前端未传或未命中 → 读环境变量 AI_MODEL，再退化到类默认值
        """
        if frontend_name:
            if "/" in frontend_name:
                return frontend_name
            if frontend_name in cls.MODEL_NAME_MAP:
                return cls.MODEL_NAME_MAP[frontend_name]
        return os.environ.get("AI_MODEL", cls.AI_MODEL_DEFAULT)

    @staticmethod
    def _difficulty_to_cn(difficulty):
        mapping = {
            Difficulty.LOW: "简单",
            Difficulty.MID: "中等",
            Difficulty.HIGH: "困难",
            "简单": "简单",
            "中等": "中等",
            "困难": "困难"
        }
        return mapping.get(difficulty, "中等")

    def _build_prompt(self, knowledge_tags, difficulty, language="C", extra=""):
        difficulty_cn = self._difficulty_to_cn(difficulty)
        extra_line = f"\n额外要求：{extra}" if extra else ""

        return f"""请生成一道完整的 {language} 语言编程题目。
知识点：{knowledge_tags}
难度：{difficulty_cn}
{extra_line}"""

    def _get_system_prompt(self):
        return """你是一个资深的 C 语言编程教师，同时也是 OnlineJudge (OJ) 系统的出题专家。
请根据用户提供的【知识点】和【难度】，生成一道综合性的、完整的 C 语言编程题目。

【严酷的要求】：
1. 你必须、并且只能返回合法的 JSON 格式数据！
2. 绝对不能包含任何 Markdown 格式符号（例如不要出现 ```json 或 ```）。
3. 绝对不能有任何开场白或解释性的文字。
4. 生成的题目必须同时考察且巧妙融合用户给出的所有知识点，缺一不可！题意要自然连贯。
5. 你不要过度思考，不要钻牛角尖，不要反复质疑自己，要快速完成思考！
6. 出题速度和准确性是最高优先级，必须在保证出题准确性的前提下用最快速度完成出题！

返回的 JSON 必须严格遵守以下键名：
{
  "title": "题目名称",
  "description": "题目详细描述及要求",
  "knowledge_tags": "这里照抄接收到的知识点",
  "sample_input": "提供样例输入",
  "sample_output": "提供样例输出",
  "difficulty": "照抄接收到的难度",
  "test_cases": [
    {"input": "隐藏测试用例1输入", "output": "隐藏测试用例1输出"},
    {"input": "隐藏测试用例2输入", "output": "隐藏测试用例2输出"},
    {"input": "隐藏测试用例3输入", "output": "隐藏测试用例3输出"},
    {"input": "隐藏测试用例4输入", "output": "隐藏测试用例4输出"},
    {"input": "隐藏测试用例5输入", "output": "隐藏测试用例5输出"}
  ]
}
注意：test_cases 数组内必须包含不多不少恰好 5 组隐藏测试用例。"""

    def _call_ai_model_api(self, prompt, model=None):
        import requests

        api_key = os.environ.get("AI_API_KEY") or os.environ.get("SILICONFLOW_API_KEY")
        if not api_key:
            raise RuntimeError("AI_API_KEY is not configured")

        base_url = os.environ.get("AI_API_BASE_URL", self.AI_API_BASE_URL_DEFAULT).rstrip("/")
        # 优先使用前端传入的 model，其次使用环境变量，最后使用默认值
        final_model = self._resolve_model(model)

        resp = requests.post(
            f"{base_url}/chat/completions",
            json={
                "model": final_model,
                "messages": [
                    {"role": "system", "content": self._get_system_prompt()},
                    {"role": "user", "content": prompt}
                ],
                "temperature": 0.4
            },
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json"
            },
            timeout=self.AI_TIMEOUT
        )
        resp.raise_for_status()
        data = resp.json()
        return data["choices"][0]["message"]["content"]

    @staticmethod
    def _parse_ai_response(text):
        content = text.strip()
        content = content.replace("\r\n", "\n")
        content = re.sub(r"<think>.*?</think>", "", content, flags=re.DOTALL).strip()
        content = re.sub(r"^```json\s*", "", content, flags=re.MULTILINE)
        content = re.sub(r"^```\s*", "", content, flags=re.MULTILINE)
        if content.endswith("```"):
            content = content[:-3].strip()

        start = content.find("{")
        end = content.rfind("}")
        if start != -1 and end != -1 and end > start:
            content = content[start:end + 1]
        return json.loads(content)


class AIGenerateProblemAPI(APIView, AIProblemMixin):
    @problem_permission_required
    @validate_serializer(AIGenerateProblemSerializer)
    def post(self, request):
        self.check_ai_api_configured()  # 检查 API 配置
        data = request.data
        model = data.get("model")

        prompt = self._build_prompt(
            knowledge_tags=data["knowledge_tags"],
            difficulty=data["difficulty"],
            language=data.get("language", "C"),
            extra=data.get("extra_requirements", "")
        )

        try:
            ai_raw = self._call_ai_model_api(prompt, model=model)
            result = self._parse_ai_response(ai_raw)
        except Exception as e:
            return self.error(f"AI 生成失败: {str(e)}")

        required = ["title", "description", "knowledge_tags", "sample_input", "sample_output", "difficulty"]
        for item in required:
            if item not in result:
                return self.error(f"AI response missing field: {item}")
        if "test_cases" not in result or not isinstance(result["test_cases"], list):
            result["test_cases"] = []
        return self.success(result)


class AIRegenerateProblemAPI(AIGenerateProblemAPI):
    pass


class AIBatchGenerateProblemAPI(APIView, AIProblemMixin):
    """
    批量 AI 出题接口（一次生成多道题）。

    Endpoint: POST /api/ai/generate-problems-batch/
    请求体: {"requests": [
        {"knowledge_tags": "...", "difficulty": "...", "language": "C",
         "model": "DeepSeek V3.2", "extra_requirements": ""},
        ...
    ]}
    响应: {"error": null, "data": [{生成结果1}, {生成结果2}, ...]}

    核心特性：
    - 并发调用 AI，10 道题耗时接近单道题（而非 10 倍）
    - 返回顺序严格对齐请求顺序（即使某道 AI 响应更快）
    - 单道失败不影响其它，失败项以 {"error": "..."} 占位
    """

    # 并发上限：避免打爆 AI 服务或触发限流
    MAX_WORKERS = 10

    @problem_permission_required
    @validate_serializer(AIBatchGenerateProblemSerializer)
    def post(self, request):
        self.check_ai_api_configured()  # 检查 API 配置
        requests_list = request.data["requests"]

        # 预分配结果数组，保证顺序与请求一致
        results = [None] * len(requests_list)

        with ThreadPoolExecutor(max_workers=self.MAX_WORKERS) as executor:
            future_to_idx = {
                executor.submit(self._generate_single, req): idx
                for idx, req in enumerate(requests_list)
            }
            for future in as_completed(future_to_idx):
                idx = future_to_idx[future]
                try:
                    results[idx] = future.result()
                except Exception as e:
                    # 单道失败不阻断整批：失败项返回错误对象
                    results[idx] = {"error": f"Generation failed: {str(e)}"}

        return self.success(results)

    def _generate_single(self, req):
        """在线程池中执行单道题目生成。异常会被外层 as_completed 捕获并记录为 error 项。"""
        prompt = self._build_prompt(
            req["knowledge_tags"],
            req["difficulty"],
            req.get("language") or "C",
            req.get("extra_requirements", "")
        )
        ai_raw = self._call_ai_model_api(prompt, req.get("model", ""))
        result = self._parse_ai_response(ai_raw)

        required = ["title", "description", "knowledge_tags",
                    "sample_input", "sample_output", "difficulty"]
        for item in required:
            if item not in result:
                raise RuntimeError(f"AI response missing field: {item}")
        if "test_cases" not in result or not isinstance(result["test_cases"], list):
            result["test_cases"] = []
        return result


class AISaveProblemAPI(APIView):
    @staticmethod
    def _normalize_text(value):
        if value is None:
            return ""
        return str(value).replace("\r\n", "\n")

    def _create_test_case_from_samples(self, samples):
        test_case_id = rand_str()
        test_case_dir = os.path.join(settings.TEST_CASE_DIR, test_case_id)
        os.mkdir(test_case_dir)
        try:
            os.chmod(test_case_dir, 0o710)
        except OSError:
            pass

        test_case_info = {"spj": False, "test_cases": {}}
        test_case_score = []

        for idx, sample in enumerate(samples, start=1):
            input_name = f"{idx}.in"
            output_name = f"{idx}.out"

            input_content = self._normalize_text(sample.get("input", "")).encode("utf-8")
            output_content = self._normalize_text(sample.get("output", "")).encode("utf-8")

            input_size = len(input_content)
            output_size = len(output_content)
            stripped_output_md5 = hashlib.md5(output_content.rstrip()).hexdigest()

            with open(os.path.join(test_case_dir, input_name), "wb") as f:
                f.write(input_content)
            with open(os.path.join(test_case_dir, output_name), "wb") as f:
                f.write(output_content)

            item = {
                "input_name": input_name,
                "output_name": output_name,
                "input_size": input_size,
                "output_size": output_size,
                "stripped_output_md5": stripped_output_md5
            }
            test_case_info["test_cases"][str(idx)] = item
            test_case_score.append({**item, "score": 0})

        with open(os.path.join(test_case_dir, "info"), "w", encoding="utf-8") as f:
            f.write(json.dumps(test_case_info, indent=4, ensure_ascii=False))

        try:
            for item in os.listdir(test_case_dir):
                os.chmod(os.path.join(test_case_dir, item), 0o640)
        except OSError:
            pass

        return test_case_id, test_case_score

    def _create_test_case_from_test_cases(self, test_cases):
        """
        从 AI 生成的完整测试用例数组创建评测数据文件。
        每个元素形如 {"input": "...", "output": "...", "is_sample": bool}。
        所有用例（包括标记为样例的）都会被写入测试文件用于评测，
        因为评测系统不区分样例和隐藏点，只按编号跑全部测试点。
        """
        test_case_id = rand_str()
        test_case_dir = os.path.join(settings.TEST_CASE_DIR, test_case_id)
        os.mkdir(test_case_dir)
        try:
            os.chmod(test_case_dir, 0o710)
        except OSError:
            pass

        test_case_info = {"spj": False, "test_cases": {}}
        test_case_score = []

        for idx, tc in enumerate(test_cases, start=1):
            input_name = f"{idx}.in"
            output_name = f"{idx}.out"

            input_content = self._normalize_text(tc.get("input", "")).encode("utf-8")
            output_content = self._normalize_text(tc.get("output", "")).encode("utf-8")

            input_size = len(input_content)
            output_size = len(output_content)
            stripped_output_md5 = hashlib.md5(output_content.rstrip()).hexdigest()

            with open(os.path.join(test_case_dir, input_name), "wb") as f:
                f.write(input_content)
            with open(os.path.join(test_case_dir, output_name), "wb") as f:
                f.write(output_content)

            item = {
                "input_name": input_name,
                "output_name": output_name,
                "input_size": input_size,
                "output_size": output_size,
                "stripped_output_md5": stripped_output_md5
            }
            test_case_info["test_cases"][str(idx)] = item
            test_case_score.append({**item, "score": 0})

        with open(os.path.join(test_case_dir, "info"), "w", encoding="utf-8") as f:
            f.write(json.dumps(test_case_info, indent=4, ensure_ascii=False))

        try:
            for item in os.listdir(test_case_dir):
                os.chmod(os.path.join(test_case_dir, item), 0o640)
        except OSError:
            pass

        return test_case_id, test_case_score

    @staticmethod
    def _extract_samples_from_test_cases(test_cases):
        """
        从 test_cases 中提取标记为样例的项作为 Problem.samples 字段（学生可见的样例）。
        is_sample 缺省时视为 False（即完整 test_cases 中只有显式标记才展示）。
        若无任何 is_sample=True，则返回空列表，调用方负责退化处理。
        """
        samples = []
        for tc in test_cases:
            if tc.get("is_sample"):
                samples.append({
                    "input": tc.get("input", ""),
                    "output": tc.get("output", "")
                })
        return samples

    @problem_permission_required
    @validate_serializer(AISaveProblemSerializer)
    def post(self, request):
        data = request.data

        display_id = data.get("_id") or f"AI-{rand_str(6)}"
        while Problem.objects.filter(_id=display_id, contest_id__isnull=True).exists():
            display_id = f"AI-{rand_str(6)}"

        io_mode = data.get("io_mode") or {"io_mode": "Standard IO", "input": "input.txt", "output": "output.txt"}

        test_case_id = data.get("test_case_id", "")
        test_case_score = data.get("test_case_score", [])
        test_cases = data.get("test_cases", [])

        if not test_case_id:
            # 优先级：AI 生成的完整 test_cases > 仅样例
            # AI 的 test_cases 包含隐藏用例，更适合作为评测依据；没有时退化用 samples
            if test_cases:
                test_case_id, test_case_score = self._create_test_case_from_test_cases(test_cases)
            else:
                test_case_id, test_case_score = self._create_test_case_from_samples(data["samples"])

        samples_for_problem = data["samples"]

        total_score = 0
        if data["rule_type"] == ProblemRuleType.OI:
            for item in test_case_score:
                if item["score"] <= 0:
                    return self.error("Invalid score")
                total_score += item["score"]

        problem = Problem.objects.create(
            _id=display_id,
            title=data["title"],
            description=data["description"],
            input_description=data["input_description"],
            output_description=data["output_description"],
            samples=samples_for_problem,
            hint=data.get("hint", ""),
            test_case_id=test_case_id,
            test_case_score=test_case_score,
            time_limit=data["time_limit"],
            memory_limit=data["memory_limit"],
            languages=list(data["languages"]),
            template=data.get("template", {}),
            rule_type=data["rule_type"],
            io_mode=io_mode,
            spj=False,
            spj_language=None,
            spj_code=None,
            spj_version=None,
            spj_compile_ok=False,
            visible=data.get("visible", False),
            difficulty=data.get("difficulty", Difficulty.MID),
            source=data.get("source", "AI Generated"),
            total_score=total_score,
            share_submission=data.get("share_submission", False),
            created_by=request.user
        )

        for tag_name in data.get("tags", []):
            if not tag_name:
                continue
            tag_obj, _ = ProblemTag.objects.get_or_create(name=tag_name)
            problem.tags.add(tag_obj)

        return self.success(ProblemAdminSerializer(problem).data)


class AIMyDraftsAPI(APIView):
    @problem_permission_required
    def get(self, request):
        problems = Problem.objects.filter(created_by=request.user).filter(
            Q(source__icontains="AI") | Q(_id__startswith="AI-")
        ).order_by("-create_time")
        return self.success(self.paginate_data(request, problems, ProblemAdminSerializer))
