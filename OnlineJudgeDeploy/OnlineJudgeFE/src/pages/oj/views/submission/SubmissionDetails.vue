<template>
  <Row type="flex" justify="space-around">
    <Col :span="20" id="status">
      <Alert :type="status.type" showIcon>
        <span class="title">{{$t('m.' + status.statusName.replace(/ /g, "_"))}}</span>
        <div slot="desc" class="content">
          <template v-if="isCE">
            <pre>{{submission.statistic_info.err_info}}</pre>
          </template>
          <template v-else>
            <span>{{$t('m.Time')}}: {{submission.statistic_info.time_cost | submissionTime}}</span>
            <span>{{$t('m.Memory')}}: {{submission.statistic_info.memory_cost | submissionMemory}}</span>
            <span>{{$t('m.Lang')}}: {{submission.language}}</span>
            <span>{{$t('m.Author')}}: {{submission.username}}</span>
          </template>
        </div>
      </Alert>
    </Col>

    <!-- AI 评价区域（非 CE） -->
    <Col v-if="!isCE" :span="20">
      <Card dis-hover style="margin-top: 20px;">
        <p slot="title">
          <Icon type="ios-color-wand" size="18"></Icon>
          AI 智能评价
        </p>

        <div v-if="!aiResult">
          <p>点击下方按钮，AI 将综合分析题目描述、您的代码以及 OI 判题结果（仅总分和各测试点通过情况），给出专业评价与学习建议。</p>
          <p style="color: #999; font-size: 13px;">⚠️ 为确保测试用例安全，AI 不会获取任何测试用例的输入/输出内容以及沙箱运行输出。</p>
        </div>

        <!-- AI 评价按钮 -->
        <Button
          type="primary"
          icon="ios-color-wand"
          :loading="aiLoading"
          @click="requestAIEvaluation"
          style="margin-bottom: 15px;"
        >
          {{ aiResult ? '重新请求 AI 评价' : '请求 AI 评价' }}
        </Button>

        <!-- AI 评价结果展示 -->
        <div v-if="aiResult" class="ai-result-container">
          <Divider />

          <!-- 判题结果摘要 -->
          <div class="judge-summary">
            <h4>OI 判题结果</h4>
            <Row :gutter="16">
              <Col :span="6">
                <Card class="summary-card" :padding="12">
                  <p class="summary-label">总分</p>
                  <p class="summary-value" :style="{ color: scoreColor }">{{ aiResult.total_score }} / 100</p>
                </Card>
              </Col>
              <Col :span="6">
                <Card class="summary-card" :padding="12">
                  <p class="summary-label">整体状态</p>
                  <Tag :color="statusTagColor">{{ aiResult.status || '-' }}</Tag>
                </Card>
              </Col>
              <Col :span="6">
                <Card class="summary-card" :padding="12">
                  <p class="summary-label">错误类型</p>
                  <p class="summary-value-small">{{ aiResult.error_type || '无' }}</p>
                </Card>
              </Col>
              <Col :span="6">
                <Card class="summary-card" :padding="12">
                  <p class="summary-label">时间复杂度</p>
                  <p class="summary-value-small">{{ aiResult.complexity || '-' }}</p>
                </Card>
              </Col>
            </Row>
          </div>

          <Divider />

          <!-- AI 综合评价 -->
          <div class="ai-feedback">
            <h4>综合反馈</h4>
            <Alert type="information" showIcon>
              <div slot="desc" class="feedback-content" v-katex>
                <div v-html="renderedFeedback"></div>
              </div>
            </Alert>
          </div>

          <!-- 优化建议 -->
          <div v-if="aiResult.suggestion" style="margin-top: 15px;">
            <h4>优化建议</h4>
            <Card :padding="16" dis-hover>
              <p>{{ aiResult.suggestion }}</p>
            </Card>
          </div>

          <Row :gutter="16" style="margin-top: 15px;">
            <!-- 优点 -->
            <Col :span="12" v-if="aiResult.strengths && aiResult.strengths.length">
              <h4 style="color: #19be6b;">✅ 代码优点</h4>
              <ul class="point-list">
                <li v-for="(item, idx) in aiResult.strengths" :key="'s' + idx">{{ item }}</li>
              </ul>
            </Col>

            <!-- 待改进 -->
            <Col :span="12" v-if="aiResult.weaknesses && aiResult.weaknesses.length">
              <h4 style="color: #ff9900;">⚠️ 待改进</h4>
              <ul class="point-list">
                <li v-for="(item, idx) in aiResult.weaknesses" :key="'w' + idx">{{ item }}</li>
              </ul>
            </Col>
          </Row>

          <!-- 生成时间 -->
          <p style="color: #999; font-size: 12px; margin-top: 15px;">
            评价生成时间：{{ aiResult.generated_at || '刚刚' }}
          </p>
        </div>
      </Card>
    </Col>

    <!-- 原有：测试点详情表格（后台返 info 就显示） -->
    <Col v-if="submission.info && !isCE" :span="20">
      <Table stripe :loading="loading" :disabled-hover="true" :columns="columns" :data="submission.info.data"></Table>
    </Col>

    <!-- 原有：代码高亮展示 -->
    <Col :span="20">
      <Highlight :code="submission.code" :language="submission.language" :border-color="status.color"></Highlight>
    </Col>

    <!-- 原有：分享按钮 -->
    <Col v-if="submission.can_unshare" :span="20">
      <div id="share-btn">
        <Button v-if="submission.shared"
                type="warning" size="large" @click="shareSubmission(false)">
          {{$t('m.UnShare')}}
        </Button>
        <Button v-else
                type="primary" size="large" @click="shareSubmission(true)">
          {{$t('m.Share')}}
        </Button>
      </div>
    </Col>
  </Row>
</template>

<script>
import api from '@oj/api'
import { JUDGE_STATUS } from '@/utils/constants'
import utils from '@/utils/utils'
import Highlight from '@/pages/oj/components/Highlight'

export default {
  name: 'submissionDetails',
  components: {
    Highlight
  },
  data () {
    return {
      columns: [
        {
          title: this.$i18n.t('m.ID'),
          align: 'center',
          type: 'index'
        },
        {
          title: this.$i18n.t('m.Status'),
          align: 'center',
          render: (h, params) => {
            return h('Tag', {
              props: {
                color: JUDGE_STATUS[params.row.result].color
              }
            }, this.$i18n.t('m.' + JUDGE_STATUS[params.row.result].name.replace(/ /g, '_')))
          }
        },
        {
          title: this.$i18n.t('m.Memory'),
          align: 'center',
          render: (h, params) => {
            return h('span', utils.submissionMemoryFormat(params.row.memory))
          }
        },
        {
          title: this.$i18n.t('m.Time'),
          align: 'center',
          render: (h, params) => {
            return h('span', utils.submissionTimeFormat(params.row.cpu_time))
          }
        }
      ],
      submission: {
        result: '0',
        code: '',
        info: {
          data: []
        },
        statistic_info: {
          time_cost: '',
          memory_cost: ''
        }
      },
      isConcat: false,
      loading: false,

      //AI 评价相关数据
      aiLoading: false,
      aiResult: null
    }
  },
  mounted () {
    this.getSubmission()
  },
  methods: {
    getSubmission () {
      this.loading = true
      api.getSubmission(this.$route.params.id).then(res => {
        this.loading = false
        let data = res.data.data
        if (data.info && data.info.data && !this.isConcat) {
          if (data.info.data[0].score !== undefined) {
            this.isConcat = true
            const scoreColumn = {
              title: this.$i18n.t('m.Score'),
              align: 'center',
              key: 'score'
            }
            this.columns.push(scoreColumn)
            this.loadingTable = false
          }
          if (this.isAdminRole) {
            this.isConcat = true
            const adminColumn = [
              {
                title: this.$i18n.t('m.Real_Time'),
                align: 'center',
                render: (h, params) => {
                  return h('span', utils.submissionTimeFormat(params.row.real_time))
                }
              },
              {
                title: this.$i18n.t('m.Signal'),
                align: 'center',
                key: 'signal'
              }
            ]
            this.columns = this.columns.concat(adminColumn)
          }
        }

        // 如果后端在获取提交时返回了已有的 AI 评价，则展示
        if (data.ai_feedback || data.ai_evaluation) {
          this.aiResult = data.ai_feedback || data.ai_evaluation
        }

        this.submission = data
      }, () => {
        this.loading = false
      })
    },
    shareSubmission (shared) {
      let data = { id: this.submission.id, shared: shared }
      api.updateSubmission(data).then(res => {
        this.getSubmission()
        this.$success(this.$i18n.t('m.Succeeded'))
      }, () => {})
    },

    //AI 评价方法
    requestAIEvaluation () {
      this.aiLoading = true
      const data = {
        problem_id: this.submission.problem,      // 题目 ID
        code: this.submission.code,               // 学生代码
        submission_id: this.submission.id,        // 提交 ID（可选，用于关联）
        model: 'GLM-5.1 Pro'                      // 可选：选择的模型
      }

      api.getAIEvaluation(data).then(res => {
        this.aiResult = (res && res.data && res.data.data) ? res.data.data : (res.data || null)
        this.aiLoading = false
        this.$success('AI 评价完成')
      }).catch(() => {
        this.aiLoading = false
        // 错误已在全局拦截器中提示
      })
    }
  },
  computed: {
    status () {
      return {
        type: JUDGE_STATUS[this.submission.result].type,
        statusName: JUDGE_STATUS[this.submission.result].name,
        color: JUDGE_STATUS[this.submission.result].color
      }
    },
    isCE () {
      return this.submission.result === -2
    },
    isAdminRole () {
      return this.$store.getters.isAdminRole
    },

    //AI 评价辅助计算属性
    scoreColor () {
      if (!this.aiResult) return '#333'
      const score = this.aiResult.total_score || 0
      if (score >= 80) return '#19be6b'
      if (score >= 60) return '#ff9900'
      return '#ed3f14'
    },
    statusTagColor () {
      if (!this.aiResult) return 'default'
      const status = this.aiResult.status || ''
      if (status === 'Accepted' || status === 'AC') return 'green'
      if (status === 'Partial') return 'orange'
      if (status === 'Wrong Answer' || status === 'WA') return 'red'
      return 'default'
    },
    renderedFeedback () {
      if (!this.aiResult || !this.aiResult.feedback) return ''
      return this.aiResult.feedback.replace(/\n/g, '<br/>')
    }
  }
}
</script>

<style scoped lang="less">
  #status {
    .title {
      font-size: 20px;
    }
    .content {
      margin-top: 10px;
      font-size: 14px;
      span {
        margin-right: 10px;
      }
      pre {
        white-space: pre-wrap;
        word-wrap: break-word;
        word-break: break-all;
      }
    }
  }

  .admin-info {
    margin: 5px 0;
    &-content {
      font-size: 16px;
      padding: 10px;
    }
  }

  #share-btn {
    float: right;
    margin-top: 5px;
    margin-right: 10px;
  }

  pre {
    border: none;
    background: none;
  }

  //AI 评价样式
  .ai-result-container {
    h4 {
      margin-bottom: 10px;
      font-size: 16px;
    }
    .judge-summary {
      .summary-card {
        text-align: center;
        .summary-label {
          font-size: 13px;
          color: #999;
          margin-bottom: 5px;
        }
        .summary-value {
          font-size: 24px;
          font-weight: bold;
        }
        .summary-value-small {
          font-size: 15px;
          font-weight: 500;
          color: #333;
        }
      }
    }
    .ai-feedback {
      .feedback-content {
        line-height: 1.8;
        font-size: 14px;
        p {
          margin-bottom: 8px;
        }
      }
    }
    .point-list {
      list-style: none;
      padding-left: 0;
      li {
        padding: 8px 0;
        border-bottom: 1px dashed #e9eaec;
        &:last-child {
          border-bottom: none;
        }
      }
    }
  }
</style>
