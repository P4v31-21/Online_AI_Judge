<template>
  <div class="view">
    <Panel title="我的 AI 草稿">
      <el-table :data="drafts" v-loading="loading">
        <el-table-column prop="id" label="ID" width="90"></el-table-column>
        <el-table-column prop="_id" label="Display ID" width="150"></el-table-column>
        <el-table-column prop="title" label="标题"></el-table-column>
        <el-table-column prop="difficulty" label="难度" width="100"></el-table-column>
        <el-table-column prop="create_time" label="创建时间" width="190"></el-table-column>
        <el-table-column label="操作" width="120">
          <template slot-scope="scope">
            <el-button type="text" @click="goEdit(scope.row.id)">编辑</el-button>
          </template>
        </el-table-column>
      </el-table>
      <el-pagination
        class="page"
        layout="prev, pager, next"
        @current-change="changePage"
        :page-size="limit"
        :total="total">
      </el-pagination>
    </Panel>
  </div>
</template>

<script>
import api from '../../api'

export default {
  name: 'MyDrafts',
  data () {
    return {
      loading: false,
      drafts: [],
      total: 0,
      page: 1,
      limit: 10
    }
  },
  mounted () {
    this.getDrafts()
  },
  methods: {
    getDrafts (page = 1) {
      this.loading = true
      this.page = page
      api.getMyDrafts(page, this.limit).then(res => {
        this.loading = false
        this.drafts = res.data.data.results
        this.total = res.data.data.total
      }).catch(() => {
        this.loading = false
      })
    },
    changePage (page) {
      this.getDrafts(page)
    },
    goEdit (id) {
      this.$router.push({name: 'edit-problem', params: {problemId: id}})
    }
  }
}
</script>

<style scoped>
.page {
  margin-top: 20px;
  text-align: right;
}
</style>
