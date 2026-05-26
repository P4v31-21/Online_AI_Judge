# -*- coding: utf-8 -*-
# Stage 3 - Guard Model 人工审核字段迁移
from __future__ import unicode_literals

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('submission', '0013_ai_feedback'),
    ]

    operations = [
        migrations.AddField(
            model_name='submission',
            name='needs_guard_review',
            field=models.BooleanField(default=False, db_index=True, verbose_name='需要人工审核'),
        ),
        migrations.AddField(
            model_name='submission',
            name='guard_review_status',
            field=models.CharField(
                default='pending',
                db_index=True,
                max_length=20,
                choices=[('pending', '待审核'), ('approved', '人工通过'), ('rejected', '人工拒绝')],
                verbose_name='审核状态',
            ),
        ),
        migrations.AddField(
            model_name='submission',
            name='guard_review_reason',
            field=models.TextField(blank=True, verbose_name='Guard 拦截原因'),
        ),
        migrations.AddField(
            model_name='submission',
            name='guard_reviewed_by',
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=models.SET_NULL,
                related_name='reviewed_submissions',
                to='account.User',
                verbose_name='审核人',
            ),
        ),
        migrations.AddField(
            model_name='submission',
            name='guard_review_time',
            field=models.DateTimeField(blank=True, null=True, verbose_name='审核时间'),
        ),
    ]
