import django, os
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "oj.settings")
django.setup()
from submission.models import Submission
from submission.views.oj import AIScoreSubmissionAPI
sub = Submission.objects.last()
api = AIScoreSubmissionAPI()
judge_result = api._extract_safe_judge_result(sub)
print("judge_result:", judge_result)
try:
    res = api._call_grading_model(
        problem=sub.problem,
        student_code=sub.code,
        judge_result=judge_result,
        model_name="GLM-5.1 Pro"
    )
    print("RES:", res)
except Exception as e:
    import traceback
    traceback.print_exc()
