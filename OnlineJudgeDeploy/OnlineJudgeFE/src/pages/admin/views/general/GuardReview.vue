<template>
  <div class="view guard-review-view">
    <Panel title="Guard Model 人工审核队列">
      <div slot="header">
        <el-alert
          type="warning"
          :closable="false"
          show-icon
          title="以下提交被 Guard Model 标记为潜在风险，请人工审核后决定是否允许 AI 打分。">
        </el-alert>
      </div>

      <el-table
        v-loading="loading"
        element-loading-text="loading"
        :data="reviewList"
        style="width: 100%">
        <el-table-column prop="id" label="提交ID" width="200"></el-table-column>
        <el-table-column prop="username" label="提交学生" width="140"></el-table-column>
        <el-table-column prop="problem_title" label="题目" min-width="200"></el-table-column>
        <el-table-column prop="language" label="语言" width="100"></el-table-column>
        <el-table-column label="Guard 拦截原因" min-width="320">
          <template slot-scope="{row}">
            <div class="reason-text">{{ row.guard_review_reason || '-' }}</div>
          </template>
        </el-table-column>
        <el-table-column label="提交时间" width="180">
          <template slot-scope="{row}">
            {{ row.create_time | localtime }}
          </template>
        </el-table-column>
        <el-table-column label="操作" width="270" fixed="right">
          <template slot-scope="{row}">
            <el-button type="success" size="mini" @click="handleReview(row, 'approved')">
              通过并打分
            </el-button>
            <el-button type="danger" size="mini" @click="handleReview(row, 'rejected')">
              拒绝
            </el-button>
            <el-button type="primary" size="mini" @click="viewSubmission(row)">
              查看代码
            </el-button>
          </template>
        </el-table-column>
      </el-table>

      <div class="panel-options">
        <el-pagination
          class="page"
          layout="total, prev, pager, next"
          :current-page="currentPage"
          :page-size="pageSize"
          :total="total"
          @current-change="handlePageChange">
        </el-pagination>
      </div>
    </Panel>

    <el-dialog title="查看提交代码" :visible.sync="codeDialogVisible" width="70%">
      <div class="code-dialog-meta" v-if="currentSubmission">
        <p><strong>提交ID：</strong>{{ currentSubmission.id }}</p>
        <p><strong>学生：</strong>{{ currentSubmission.username }}</p>
        <p><strong>题目：</strong>{{ currentSubmission.problem_title || '-' }}</p>
        <p><strong>语言：</strong>{{ currentSubmission.language || '-' }}</p>
      </div>
      <pre class="code-block">{{ currentCode }}</pre>
      <div slot="footer">
        <el-button @click="codeDialogVisible = false">关闭</el-button>
      </div>
    </el-dialog>
  </div>
</template>

<script>
import api from '../../api'

export default {
  name: 'GuardReview',
  data () {
    return {
      reviewList: [],
      loading: false,
      currentPage: 1,
      pageSize: 15,
      total: 0,
      codeDialogVisible: false,
      currentCode: '',
      currentSubmission: null
    }
  },
  mounted () {
    this.fetchReviewList()
  },
  methods: {
    fetchReviewList () {
      this.loading = true
      api.getGuardReviewList({
        offset: (this.currentPage - 1) * this.pageSize,
        limit: this.pageSize
      }).then(res => {
        const data = res.data.data || {}
        this.reviewList = data.results || []
        this.total = data.count || data.total || 0
      }).catch(() => {
        this.$error('获取审核列表失败')
      }).then(() => {
        this.loading = false
      })
    },
    handlePageChange (page) {
      this.currentPage = page
      this.fetchReviewList()
    },
    handleReview (item, action) {
      const msg = action === 'approved'
        ? '确定通过审核并执行 AI 打分吗？'
        : '确定拒绝该提交的 AI 打分请求吗？'
      this.$confirm(msg, '提示', {
        type: action === 'approved' ? 'success' : 'warning'
      }).then(() => {
        return api.guardReview({
          submission_id: item.id,
          action,
          review_comment: action === 'approved' ? '人工审核通过' : '人工审核拒绝'
        })
      }).then(() => {
        this.$success(action === 'approved' ? '已通过并开始 AI 打分' : '已拒绝')
        this.fetchReviewList()
      }).catch(() => {})
    },
    viewSubmission (item) {
      api.getSubmission(item.id).then(res => {
        const data = res.data.data || {}
        this.currentSubmission = Object.assign({}, item, data)
        this.currentCode = data.code || '// 暂无代码'
        this.codeDialogVisible = true
      }).catch(() => {
        this.$error('获取提交代码失败')
      })
    }
  }
}
</script>

<style scoped lang="less">
.guard-review-view {
  .reason-text {
    white-space: normal;
    word-break: break-word;
    line-height: 1.5;
  }

  .code-dialog-meta {
    margin-bottom: 10px;
    p {
      margin: 4px 0;
      color: #666;
    }
  }

  .code-block {
    max-height: 500px;
    overflow: auto;
    padding: 12px;
    border-radius: 4px;
    background: #f7f8fa;
    border: 1px solid #ebeef5;
    white-space: pre-wrap;
    word-break: break-word;
    font-size: 13px;
    line-height: 1.7;
  }
}
</style>
