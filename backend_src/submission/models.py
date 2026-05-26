from django.db import models

from utils.constants import ContestStatus
from utils.models import JSONField
from problem.models import Problem
from contest.models import Contest

from utils.shortcuts import rand_str


class JudgeStatus:
    COMPILE_ERROR = -2
    WRONG_ANSWER = -1
    ACCEPTED = 0
    CPU_TIME_LIMIT_EXCEEDED = 1
    REAL_TIME_LIMIT_EXCEEDED = 2
    MEMORY_LIMIT_EXCEEDED = 3
    RUNTIME_ERROR = 4
    SYSTEM_ERROR = 5
    PENDING = 6
    JUDGING = 7
    PARTIALLY_ACCEPTED = 8


class Submission(models.Model):
    id = models.TextField(default=rand_str, primary_key=True, db_index=True)
    contest = models.ForeignKey(Contest, null=True, on_delete=models.CASCADE)
    problem = models.ForeignKey(Problem, on_delete=models.CASCADE)
    create_time = models.DateTimeField(auto_now_add=True)
    user_id = models.IntegerField(db_index=True)
    username = models.TextField()
    code = models.TextField()
    result = models.IntegerField(db_index=True, default=JudgeStatus.PENDING)
    # 从JudgeServer返回的判题详情
    info = JSONField(default=dict)
    language = models.TextField()
    shared = models.BooleanField(default=False)
    # 存储该提交所用时间和内存值，方便提交列表显示
    # {time_cost: "", memory_cost: "", err_info: "", score: 0}
    statistic_info = JSONField(default=dict)
    ip = models.TextField(null=True)

    # ============ AI 评测相关字段（阶段三新增） ============
    # AI 完整反馈结果（Engine B 的 JSON 输出，结构对齐 Beta I/Week1/AI测评设计.md）
    # 包含：total_score / status / test_case_scores / error_type /
    #       suggestion / complexity / feedback / strengths / weaknesses
    ai_feedback = JSONField(default=dict)
    # AI 给出的总评分（0~100），抽出来便于做统计/排序/导出
    ai_score = models.IntegerField(null=True, blank=True, db_index=True)
    # AI 评测状态机：pending / done / blocked_by_guard / failed
    # blocked_by_guard 表示 Guard Model 检测到注入攻击，未交给 Grading
    ai_status = models.CharField(max_length=32, default="pending", db_index=True)

    # ============ 新增：Guard 人工审核相关字段 ============
    needs_guard_review = models.BooleanField(default=False, db_index=True,
                                             verbose_name="需要人工审核")
    guard_review_status = models.CharField(max_length=20, default="pending", db_index=True,
                                           choices=[
                                               ("pending", "待审核"),
                                               ("approved", "人工通过"),
                                               ("rejected", "人工拒绝"),
                                           ],
                                           verbose_name="审核状态")
    guard_review_reason = models.TextField(blank=True, verbose_name="Guard 拦截原因")
    guard_reviewed_by = models.ForeignKey(
        'account.User', null=True, blank=True, on_delete=models.SET_NULL,
        related_name="reviewed_submissions", verbose_name="审核人"
    )
    guard_review_time = models.DateTimeField(null=True, blank=True, verbose_name="审核时间")

    def check_user_permission(self, user, check_share=True):
        if self.user_id == user.id or user.is_super_admin() or user.can_mgmt_all_problem() or self.problem.created_by_id == user.id:
            return True

        if check_share:
            if self.contest and self.contest.status != ContestStatus.CONTEST_ENDED:
                return False
            if self.problem.share_submission or self.shared:
                return True
        return False

    class Meta:
        db_table = "submission"
        ordering = ("-create_time",)

    def __str__(self):
        return self.id
