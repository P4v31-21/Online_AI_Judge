from django.conf.urls import url

from ..views.oj import (SubmissionAPI, SubmissionListAPI, ContestSubmissionListAPI,
                        SubmissionExistsAPI, AIScoreSubmissionAPI, GuardCheckAPI)

urlpatterns = [
    url(r"^submission/?$", SubmissionAPI.as_view(), name="submission_api"),
    url(r"^submissions/?$", SubmissionListAPI.as_view(), name="submission_list_api"),
    url(r"^submission_exists/?$", SubmissionExistsAPI.as_view(), name="submission_exists"),
    url(r"^contest_submissions/?$", ContestSubmissionListAPI.as_view(), name="contest_submission_list_api"),
    # 阶段三：AI 智能评测接口（Engine B）
    url(r"^ai/score-submission/?$", AIScoreSubmissionAPI.as_view(), name="ai_score_submission_api"),
    url(r"^ai/guard-check/?$", GuardCheckAPI.as_view(), name="ai_guard_check_api"),
]
