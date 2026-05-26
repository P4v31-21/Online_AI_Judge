<template>
  <div class="ai-create-problem">
    <Panel :title="pageTitle">
      <!-- ========== 需求输入（支持多题，每题可选模型） ========== -->
      <div v-for="(item, index) in reqList" :key="index" class="req-card">
        <el-card shadow="never">
          <div slot="header" class="req-card-header">
            <span>题目需求 {{ index + 1 }}</span>
            <el-button
              v-if="reqList.length > 1"
              type="text"
              icon="el-icon-delete"
              @click="removeReq(index)"
              style="float: right; color: #f56c6c;"
            ></el-button>
          </div>
          <el-form label-position="top">
            <el-row :gutter="20">
              <el-col :span="6">
                <el-form-item label="知识点" required>
                  <el-input
                    v-model="item.knowledge_tags"
                    placeholder="多个知识点用逗号分隔，如：数组,循环"
                  ></el-input>
                </el-form-item>
              </el-col>
              <el-col :span="4">
                <el-form-item label="难度" required>
                  <el-radio-group v-model="item.difficulty">
                    <el-radio label="简单">简单</el-radio>
                    <el-radio label="中等">中等</el-radio>
                    <el-radio label="困难">困难</el-radio>
                  </el-radio-group>
                </el-form-item>
              </el-col>
              <el-col :span="3">
                <el-form-item label="语言">
                  <el-select v-model="item.language" placeholder="选择语言">
                    <el-option
                      v-for="lang in allLanguages"
                      :key="lang"
                      :label="lang"
                      :value="lang"
                    ></el-option>
                  </el-select>
                </el-form-item>
              </el-col>
              <el-col :span="4">
                <el-form-item label="AI 模型" required>
                  <el-select v-model="item.model" placeholder="选择模型">
                    <el-option
                      v-for="m in availableModels"
                      :key="m"
                      :label="m"
                      :value="m"
                    ></el-option>
                  </el-select>
                </el-form-item>
              </el-col>
              <el-col :span="7">
                <el-form-item label="额外要求（可选）">
                  <el-input
                    v-model="item.extra_requirements"
                    placeholder="例如：请限制数组长度"
                  ></el-input>
                </el-form-item>
              </el-col>
            </el-row>
          </el-form>
        </el-card>
      </div>

      <!-- 添加需求按钮（上限10道） -->
      <el-button
        v-if="reqList.length < 10"
        type="dashed"
        icon="el-icon-plus"
        @click="addReq"
        style="width: 100%; margin: 15px 0;"
      >添加一道题目需求</el-button>

      <el-alert
        v-if="reqList.length >= 10"
        title="已达到最大题目数量（10道）"
        type="info"
        show-icon
        style="margin-bottom: 15px;"
      ></el-alert>

      <!-- 生成按钮 -->
      <el-button type="primary" @click="generateBatch" :loading="generating">
        AI 生成全部题目
      </el-button>
      <el-button v-if="editingList.length" @click="regenerateBatch" :loading="regenerating">
        重新生成全部
      </el-button>

      <!-- 错误提示 -->
      <el-alert
        v-if="genError"
        style="margin-top: 15px"
        type="error"
        :title="genError"
        show-icon
      ></el-alert>

      <!-- ========== 生成结果：多题并列编辑区域 ========== -->
      <div v-if="editingList.length" style="margin-top: 30px;">
        <el-divider content-position="left">生成结果（共 {{ editingList.length }} 题）</el-divider>

        <div v-for="(problem, pIndex) in editingList" :key="pIndex" class="problem-editor-card">
          <el-card shadow="hover">
            <div slot="header">
              <span>题目 {{ pIndex + 1 }}：{{ problem.title || '(未命名)' }}</span>
              <el-button
                type="success"
                size="small"
                style="float: right; margin-left: 10px;"
                :loading="savingList[pIndex]"
                @click="saveProblem(pIndex)"
              >保存此题</el-button>
            </div>

            <el-form label-position="top">
              <el-row :gutter="20">
                <el-col :span="6">
                  <el-form-item label="显示 ID（可选）">
                    <el-input v-model="problem._id"></el-input>
                  </el-form-item>
                </el-col>
                <el-col :span="10">
                  <el-form-item label="题目标题" required>
                    <el-input v-model="problem.title"></el-input>
                  </el-form-item>
                </el-col>
                <el-col :span="4">
                  <el-form-item label="时间限制(ms)" required>
                    <el-input-number
                      v-model="problem.time_limit"
                      :min="100"
                      :step="100"
                    ></el-input-number>
                  </el-form-item>
                </el-col>
                <el-col :span="4">
                  <el-form-item label="内存限制(MB)" required>
                    <el-input-number
                      v-model="problem.memory_limit"
                      :min="16"
                      :step="16"
                    ></el-input-number>
                  </el-form-item>
                </el-col>
              </el-row>

              <el-form-item label="题目描述" required>
                <el-input type="textarea" :rows="6" v-model="problem.description"></el-input>
              </el-form-item>

              <el-row :gutter="20">
                <el-col :span="12">
                  <el-form-item label="输入说明" required>
                    <el-input type="textarea" :rows="4" v-model="problem.input_description"></el-input>
                  </el-form-item>
                </el-col>
                <el-col :span="12">
                  <el-form-item label="输出说明" required>
                    <el-input type="textarea" :rows="4" v-model="problem.output_description"></el-input>
                  </el-form-item>
                </el-col>
              </el-row>

              <!-- 输入输出样例 -->
              <el-form-item label="输入输出样例">
                <el-row :gutter="20">
                  <el-col :span="12">
                    <el-form-item label="样例输入" required>
                      <el-input type="textarea" :rows="3" v-model="problem.sample_input" placeholder="样例输入"></el-input>
                    </el-form-item>
                  </el-col>
                  <el-col :span="12">
                    <el-form-item label="样例输出" required>
                      <el-input type="textarea" :rows="3" v-model="problem.sample_output" placeholder="样例输出"></el-input>
                    </el-form-item>
                  </el-col>
                </el-row>
              </el-form-item>

              <!-- 测试用例区域 -->
              <el-form-item label="测试用例">
                <el-button type="text" icon="el-icon-plus" @click="addTestCase(pIndex)">添加一组测试用例</el-button>
                <div
                  v-for="(tc, tIdx) in problem.test_cases"
                  :key="tIdx"
                  style="margin-bottom: 15px; border: 1px solid #ebeef5; padding: 10px; border-radius: 4px;"
                >
                  <el-row :gutter="20" align="middle">
                    <el-col :span="10">
                      <el-form-item label="输入">
                        <el-input type="textarea" :rows="3" v-model="tc.input" placeholder="测试用例输入"></el-input>
                      </el-form-item>
                    </el-col>
                    <el-col :span="10">
                      <el-form-item label="输出">
                        <el-input type="textarea" :rows="3" v-model="tc.output" placeholder="测试用例输出"></el-input>
                      </el-form-item>
                    </el-col>
                    <el-col :span="4" style="text-align: center;">
                      <el-button type="text" icon="el-icon-delete" @click="removeTestCase(pIndex, tIdx)" style="color: #f56c6c;"></el-button>
                    </el-col>
                  </el-row>
                </div>
              </el-form-item>

              <el-row :gutter="20">
                <el-col :span="12">
                  <el-form-item label="标签（逗号分隔）">
                    <el-input v-model="problem.tagText"></el-input>
                  </el-form-item>
                </el-col>
                <el-col :span="12">
                  <el-form-item label="可提交语言" required>
                    <el-checkbox-group v-model="problem.languages">
                      <el-checkbox v-for="lang in allLanguages" :key="lang" :label="lang"></el-checkbox>
                    </el-checkbox-group>
                  </el-form-item>
                </el-col>
              </el-row>
            </el-form>
          </el-card>
        </div>
      </div>
    </Panel>
  </div>
</template>

<script>
import api from '../../api'

export default {
  name: 'AiCreateProblem',
  data() {
    return {
      generating: false,
      regenerating: false,
      savingList: [],
      genError: '',
      // 可用模型列表
      availableModels: ['GLM-5.1 Pro', 'DeepSeek V3.2', 'DeepSeek R1'],
      // 原始需求列表（每个需求包含模型选择）
      reqList: [
        {
          knowledge_tags: '',
          difficulty: '中等',
          language: 'C',
          model: 'GLM-5.1 Pro',   // 默认模型
          extra_requirements: ''
        }
      ],
      allLanguages: ['C', 'C++', 'Java', 'Python3', 'Golang', 'JavaScript'],
      editingList: []
    }
  },
  computed: {
    pageTitle() {
      return 'AI 出题（支持批量）'
    }
  },
  methods: {
    // ================== 需求管理 ==================
    addReq() {
      if (this.reqList.length >= 10) {
        this.$message.warning('最多同时生成10道题目');
        return;
      }
      this.reqList.push({
        knowledge_tags: '',
        difficulty: '中等',
        language: 'C',
        model: 'GLM-5.1 Pro',   // 默认模型
        extra_requirements: ''
      });
    },
    removeReq(index) {
      if (this.reqList.length <= 1) {
        this.$message.warning('至少保留一道题目需求');
        return;
      }
      this.reqList.splice(index, 1);
    },

    // ================== 难度映射 ==================
    mapDifficulty(value) {
      const m = { '简单': 'Low', '中等': 'Mid', '困难': 'High', 'Low': 'Low', 'Mid': 'Mid', 'High': 'High' };
      return m[value] || 'Mid';
    },

    // ================== 构建单个题目编辑对象 ==================
    buildSingleProblem(data, reqItem) {
      const tags = (data.knowledge_tags || reqItem.knowledge_tags || '')
        .split(/[，,]/)
        .map(x => x.trim())
        .filter(Boolean);

      let testCases = [];
      if (data.test_cases && Array.isArray(data.test_cases) && data.test_cases.length) {
        testCases = data.test_cases.map(tc => ({
          input: tc.input || '',
          output: tc.output || ''
        }));
      }

      let sampleInput = data.sample_input || '';
      let sampleOutput = data.sample_output || '';
      if ((!sampleInput && !sampleOutput) && data.samples && Array.isArray(data.samples) && data.samples.length) {
        sampleInput = data.samples[0].input || '';
        sampleOutput = data.samples[0].output || '';
      }

      return {
        _id: '',
        title: data.title || '',
        description: data.description || '',
        input_description: data.input_description || '<p>请根据题意读取输入。</p>',
        output_description: data.output_description || '<p>请按题意输出结果。</p>',
        sample_input: sampleInput,
        sample_output: sampleOutput,
        test_cases: testCases,
        time_limit: 1000,
        memory_limit: 256,
        languages: [reqItem.language || 'C'],
        template: {},
        rule_type: 'ACM',
        io_mode: { io_mode: 'Standard IO', input: 'input.txt', output: 'output.txt' },
        visible: false,
        difficulty: this.mapDifficulty(data.difficulty),
        tags,
        tagText: tags.join(','),
        hint: '',
        source: 'AI Generated',
        share_submission: false
      };
    },

    // ================== 批量生成（发送模型参数） ==================
    generateBatch() {
      const hasKnowledge = this.reqList.some(item => item.knowledge_tags.trim() !== '');
      if (!hasKnowledge) {
        this.$error('请至少填写一道题目的知识点');
        return;
      }
      this.generating = true;
      this.genError = '';
      // 调用批量接口，传递包含 model 的 reqList
      api.generateProblemsBatch(this.reqList).then(res => {
        const dataList = res.data.data;
        if (!dataList || dataList.length !== this.reqList.length) {
          this.genError = '生成的题目数量与需求不符，请稍后重试';
          this.generating = false;
          return;
        }
        this.editingList = dataList.map((data, idx) => {
          return this.buildSingleProblem(data, this.reqList[idx]);
        });
        this.savingList = new Array(this.editingList.length).fill(false);
        this.generating = false;
      }).catch(err => {
        this.generating = false;
        this.genError = (err && err.data && err.data.data) || '批量生成失败，请稍后重试';
      });
    },
    regenerateBatch() {
      if (!this.reqList.length) return;
      this.regenerating = true;
      this.genError = '';
      api.generateProblemsBatch(this.reqList).then(res => {
        const dataList = res.data.data;
        if (!dataList || dataList.length !== this.reqList.length) {
          this.genError = '重新生成失败，题目数量不匹配';
          this.regenerating = false;
          return;
        }
        this.editingList = dataList.map((data, idx) => {
          return this.buildSingleProblem(data, this.reqList[idx]);
        });
        this.regenerating = false;
      }).catch(err => {
        this.regenerating = false;
        this.genError = (err && err.data && err.data.data) || '重新生成失败';
      });
    },

    // ================== 测试用例操作 ==================
    addTestCase(problemIndex) {
      this.editingList[problemIndex].test_cases.push({
        input: '',
        output: ''
      });
    },
    removeTestCase(problemIndex, caseIndex) {
      this.editingList[problemIndex].test_cases.splice(caseIndex, 1);
    },

    // ================== 保存单个题目 ==================
    saveProblem(problemIndex) {
      const problem = this.editingList[problemIndex];
      if (!problem || !problem.title || !problem.description) {
        this.$error('请补全题目标题和描述');
        return;
      }
      const tags = problem.tagText
        .split(/[，,]/)
        .map(x => x.trim())
        .filter(Boolean);
      const data = {
        ...problem,
        tags
      };
      this.$set(this.savingList, problemIndex, true);
      api.saveDraftProblem(data).then(() => {
        this.$set(this.savingList, problemIndex, false);
        this.$success('题目保存成功');
      }).catch(() => {
        this.$set(this.savingList, problemIndex, false);
      });
    }
  }
}
</script>

<style scoped lang="less">
.ai-create-problem {
  .req-card {
    margin-bottom: 15px;
    .req-card-header {
      font-weight: bold;
    }
  }
  .problem-editor-card {
    margin-bottom: 25px;
  }
  .el-input-number {
    width: 100%;
  }
  .el-form-item {
    margin-bottom: 18px;
  }
}
</style>
