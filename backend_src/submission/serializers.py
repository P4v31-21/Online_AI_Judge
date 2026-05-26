from .models import Submission
from utils.api import serializers
from utils.serializers import LanguageNameChoiceField


class CreateSubmissionSerializer(serializers.Serializer):
    problem_id = serializers.IntegerField()
    language = LanguageNameChoiceField()
    code = serializers.CharField(max_length=1024 * 1024)
    contest_id = serializers.IntegerField(required=False)
    captcha = serializers.CharField(required=False)


class ShareSubmissionSerializer(serializers.Serializer):
    id = serializers.CharField()
    shared = serializers.BooleanField()


class AIScoreSubmissionSerializer(serializers.Serializer):
    """
    AI 打分接口 (Engine B) 的请求参数验证器。
    对接 Beta I/Week1/AI测评设计.md 的 POST /api/ai/score-submission/
    设计要求：
      - problem_id 必传（用于读取题目描述）
      - code 与 submission_id 至少一个：
          submission_id：评测一条已有提交（推荐，能拿到完整 OJ 判题结果）
          code：教师即时贴码评测（无 OJ 结果，AI 只看代码 + 题目）
      - model：可选，前端选择的 AI 模型显示名（如 "GLM-5.1 Pro"）
    """
    problem_id = serializers.IntegerField()
    submission_id = serializers.CharField(max_length=64, required=False, allow_blank=True, default="")
    code = serializers.CharField(max_length=1024 * 1024, required=False, allow_blank=True, default="")
    model = serializers.CharField(max_length=64, required=False, allow_blank=True, default="")

    def validate(self, attrs):
        # 至少传一种代码来源
        if not attrs.get("submission_id") and not attrs.get("code"):
            raise serializers.ValidationError("Either submission_id or code is required")
        return attrs


class SubmissionModelSerializer(serializers.ModelSerializer):

    class Meta:
        model = Submission
        fields = "__all__"


# 不显示submission info的serializer, 用于ACM rule_type
class SubmissionSafeModelSerializer(serializers.ModelSerializer):
    problem = serializers.SlugRelatedField(read_only=True, slug_field="_id")

    class Meta:
        model = Submission
        exclude = ("info", "contest", "ip")


class SubmissionListSerializer(serializers.ModelSerializer):
    problem = serializers.SlugRelatedField(read_only=True, slug_field="_id")
    show_link = serializers.SerializerMethodField()

    def __init__(self, *args, **kwargs):
        self.user = kwargs.pop("user", None)
        super().__init__(*args, **kwargs)

    class Meta:
        model = Submission
        exclude = ("info", "contest", "code", "ip")

    def get_show_link(self, obj):
        # 没传user或为匿名user
        if self.user is None or not self.user.is_authenticated:
            return False
        return obj.check_user_permission(self.user)

class GuardReviewSerializer(serializers.Serializer):
    submission_id = serializers.CharField()
    action = serializers.ChoiceField(choices=["approved", "rejected"])
    review_comment = serializers.CharField(required=False, allow_blank=True, max_length=500)


class GuardCheckSerializer(serializers.Serializer):
    code = serializers.CharField(max_length=1024 * 1024)