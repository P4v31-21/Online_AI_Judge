# -*- coding: utf-8 -*-
# Stage 3 - AI 智能评测字段迁移
# 为 Submission 表新增 ai_feedback / ai_score / ai_status 三个字段
from __future__ import unicode_literals

from django.db import migrations, models
from utils.models import JSONField


class Migration(migrations.Migration):

    dependencies = [
        ('submission', '0012_auto_20180501_0436'),
    ]

    operations = [
        migrations.AddField(
            model_name='submission',
            name='ai_feedback',
            field=JSONField(default=dict),
        ),
        migrations.AddField(
            model_name='submission',
            name='ai_score',
            field=models.IntegerField(blank=True, db_index=True, null=True),
        ),
        migrations.AddField(
            model_name='submission',
            name='ai_status',
            field=models.CharField(default='pending', db_index=True, max_length=32),
        ),
    ]
