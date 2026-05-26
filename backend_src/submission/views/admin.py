import logging
from account.decorators import problem_permission_required, super_admin_required
from judge.tasks import judge_task
# from judge.dispatcher import JudgeDispatcher
from django.utils import timezone
from utils.api import APIView, validate_serializer
from ..models import Submission
from ..serializers import GuardReviewSerializer
from .oj import AIScoreSubmissionAPI

logger = logging.getLogger(__name__)


class SubmissionRejudgeAPI(APIView):
    @super_admin_required
    def get(self, request):
        id = request.GET.get("id")
        if not id:
            return self.error("Parameter error, id is required")
        try:
            submission = Submission.objects.select_related("problem").get(id=id, contest_id__isnull=True)
        except Submission.DoesNotExist:
            return self.error("Submission does not exists")
        submission.statistic_info = {}
        submission.save()

        judge_task.send(submission.id, submission.problem.id)
        return self.success()
    

# =============================================================================
# Guard Model 人工审核接口
# =============================================================================
class GuardReviewAPI(APIView):
    """
    管理员/教师 对 Guard Model 拦截的提交进行人工审核
    Endpoint: 
        GET  /api/admin/guard-review/     → 获取待审核列表
        POST /api/admin/guard-review/     → 审核通过或拒绝
    """

    @problem_permission_required
    def get(self, request):
        """获取待人工审核的提交列表"""
        submissions = Submission.objects.filter(
            needs_guard_review=True,
            guard_review_status="pending"
        ).select_related('problem', 'guard_reviewed_by').order_by('-create_time')

        # 支持分页
        data = self.paginate_data(request, submissions)
        # 可根据需要自定义序列化器，这里简单返回关键字段
        result = []
        for sub in data['results']:
            result.append({
                "id": sub.id,
                "username": sub.username,
                "problem_id": sub.problem_id,
                "problem_title": sub.problem.title if sub.problem else "",
                "create_time": sub.create_time.isoformat() if sub.create_time else None,
                "guard_review_reason": sub.guard_review_reason,
                "code_length": len(sub.code) if sub.code else 0,
                "language": sub.language
            })

        data['results'] = result
        return self.success(data)

    @problem_permission_required
    @validate_serializer(GuardReviewSerializer)
    def post(self, request):
        """执行人工审核"""
        data = request.data
        try:
            submission = Submission.objects.select_related('problem').get(id=data["submission_id"])
        except Submission.DoesNotExist:
            return self.error("提交记录不存在")

        if not submission.needs_guard_review:
            return self.error("该提交无需人工审核")

        action = data["action"]
        comment = data.get("review_comment", "")

        if action == "approved":
            # 人工审核通过 → 执行 AI 打分
            submission.guard_review_status = "approved"
            submission.needs_guard_review = False
            submission.guard_reviewed_by = request.user
            submission.guard_review_time = timezone.now()
            submission.save()

            # 调用 AI 打分（跳过 Guard）
            try:
                ai_api = AIScoreSubmissionAPI()
                grading_result = ai_api._call_grading_model(
                    problem=submission.problem,
                    student_code=submission.code,
                    judge_result=ai_api._extract_safe_judge_result(submission),
                    model_name="GLM-5.1 Pro"
                )
                ai_api._persist_feedback(submission, grading_result, status="done")
                return self.success({"message": "审核通过，已完成 AI 打分"})
            except Exception as e:
                logger.error(f"人工审核通过后 AI 打分失败: {e}")
                return self.success({"message": "审核通过，但 AI 打分执行失败，请稍后重试"})

        elif action == "rejected":
            # 拒绝
            submission.guard_review_status = "rejected"
            submission.needs_guard_review = False
            submission.ai_status = "rejected_by_guard"
            submission.guard_reviewed_by = request.user
            submission.guard_review_time = timezone.now()
            submission.guard_review_reason = comment or submission.guard_review_reason
            submission.save()
            return self.success({"message": "已拒绝该提交的 AI 打分请求"})

        return self.error("无效的操作类型")