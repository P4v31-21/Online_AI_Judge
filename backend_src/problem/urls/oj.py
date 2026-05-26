from django.conf.urls import url

from ..views.oj import ProblemTagAPI, ProblemAPI, ContestProblemAPI, PickOneAPI
from ..views.admin import (AIGenerateProblemAPI, AIRegenerateProblemAPI, AISaveProblemAPI,
                           AIMyDraftsAPI, AIBatchGenerateProblemAPI)

urlpatterns = [
    url(r"^problem/tags/?$", ProblemTagAPI.as_view(), name="problem_tag_list_api"),
    url(r"^problem/?$", ProblemAPI.as_view(), name="problem_api"),
    url(r"^pickone/?$", PickOneAPI.as_view(), name="pick_one_api"),
    url(r"^contest/problem/?$", ContestProblemAPI.as_view(), name="contest_problem_api"),
    url(r"^ai/generate-problem/?$", AIGenerateProblemAPI.as_view(), name="ai_generate_problem_api"),
    url(r"^ai/generate-problems-batch/?$", AIBatchGenerateProblemAPI.as_view(),
        name="ai_batch_generate_problem_api"),
    url(r"^ai/regenerate/?$", AIRegenerateProblemAPI.as_view(), name="ai_regenerate_problem_api"),
    url(r"^ai/save-problem/?$", AISaveProblemAPI.as_view(), name="ai_save_problem_api"),
    url(r"^ai/my-drafts/?$", AIMyDraftsAPI.as_view(), name="ai_my_drafts_api"),
]
