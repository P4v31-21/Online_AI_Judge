from django.conf.urls import url
from django.urls import path

from ..views.admin import GuardReviewAPI, SubmissionRejudgeAPI

urlpatterns = [
    url(r"^submission/rejudge?$", SubmissionRejudgeAPI.as_view(), name="submission_rejudge_api"),
    path('guard-review/', GuardReviewAPI.as_view(), name='guard-review'),
]
