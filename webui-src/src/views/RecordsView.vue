<template>
  <section class="panel">
    <div class="filters">
      <n-select v-model:value="rangeMode" :options="rangeOptions" style="width: 150px" />
      <n-date-picker
        v-if="rangeMode === 'custom'"
        v-model:value="customRange"
        type="daterange"
        clearable
        style="width: 260px"
      />
      <n-select v-model:value="grade" :options="gradeOptions" style="width: 120px" placeholder="吉凶档位" />
      <n-select
        v-model:value="group"
        :options="groupOptions"
        style="width: 220px"
        filterable
        placeholder="全部群聊"
      />
      <n-input
        v-model:value="keyword"
        placeholder="按 QQ 号或昵称搜索"
        style="width: 200px"
        clearable
        @keyup.enter="search"
      />
      <n-button type="primary" size="small" @click="search">查询</n-button>
      <n-button size="small" quaternary @click="reset">重置</n-button>
      <span class="sub">共 {{ total }} 条</span>
    </div>

    <div class="table-wrap">
      <table>
        <thead>
          <tr>
            <th>日期</th><th>用户</th><th>吉凶</th><th>指数</th><th>连签</th>
            <th>来源</th><th>幸运色</th><th>幸运物</th><th>LLM</th><th>图卡</th><th></th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="row in rows" :key="row.uid + row.date">
            <td>{{ row.date }}</td>
            <td>
              <span class="nick">{{ row.nickname || row.uid }}</span>
              <span class="uid">{{ row.uid }}</span>
            </td>
            <td><span class="grade" :style="{ background: gradeColor(row.grade) }">{{ row.grade }}</span></td>
            <td>{{ row.score }}</td>
            <td>{{ row.streak }}</td>
            <td>{{ row.group_name || row.group_id || "私聊" }}</td>
            <td>{{ row.lucky_color || "-" }}</td>
            <td>{{ row.lucky_item || "-" }}</td>
            <td>{{ row.llm_used ? "✓" : "—" }}</td>
            <td>{{ row.has_card ? "已生成" : "—" }}</td>
            <td><a @click="detail = row">详情</a></td>
          </tr>
          <tr v-if="!rows.length">
            <td colspan="11" class="empty">{{ loading ? "加载中…" : "没有符合条件的记录" }}</td>
          </tr>
        </tbody>
      </table>
    </div>

    <div class="pager" v-if="total > size">
      <n-pagination
        v-model:page="page"
        :page-count="Math.ceil(total / size)"
        :page-slot="7"
        size="small"
        @update:page="load"
      />
    </div>
  </section>

  <n-drawer v-model:show="drawerOpen" :width="420" placement="right">
    <n-drawer-content :title="detail ? `${detail.date} · ${detail.nickname || detail.uid}` : '详情'" closable>
      <template v-if="detail">
        <ul class="kv">
          <li><span>QQ 号</span><b>{{ detail.uid }}</b></li>
          <li><span>吉凶 / 指数</span><b>{{ detail.grade }} · {{ detail.score }}</b></li>
          <li><span>连签</span><b>{{ detail.streak }} 天</b></li>
          <li><span>来源</span><b>{{ detail.group_name || detail.group_id || "私聊" }}</b></li>
          <li><span>幸运色 / 物</span><b>{{ detail.lucky_color || "-" }} / {{ detail.lucky_item || "-" }}</b></li>
          <li><span>抽签时刻</span><b>{{ detail.created_at }}</b></li>
          <li><span>图卡</span><b>{{ detail.has_card ? "已生成" : "无卡文件" }}</b></li>
          <li><span>LLM 签文</span><b>{{ detail.llm_used ? "使用" : "未使用" }}</b></li>
        </ul>
        <div class="sign">{{ detail.sign_text || "（无签文）" }}</div>
        <n-button size="small" @click="openUser(detail.uid)">查看该用户</n-button>
      </template>
      <div v-else class="empty">未选择记录</div>
    </n-drawer-content>
  </n-drawer>
</template>

<script setup lang="ts">
import { NButton, NInput, NDatePicker, NDrawer, NDrawerContent, NPagination, NSelect, useMessage } from "naive-ui";
import { computed, onMounted, ref, watch } from "vue";
import { useRouter } from "vue-router";
import { apiGet, type RecordRow, type RecordsPayload } from "../api";
import { gradeColor } from "../theme";

const router = useRouter();
const message = useMessage();

const rangeMode = ref<string>("30");
const customRange = ref<[number, number] | null>(null);
const grade = ref<string>("");
const group = ref<string>("");
const keyword = ref("");

const rows = ref<RecordRow[]>([]);
const total = ref(0);
const page = ref(1);
const size = ref(20);
const loading = ref(false);
const detail = ref<RecordRow | null>(null);
const drawerOpen = ref(false);
const groups = ref<{ group_id: string; group_name: string; draws: number }[]>([]);

const rangeOptions = [
  { label: "近 7 天", value: "7" },
  { label: "近 30 天", value: "30" },
  { label: "近 90 天", value: "90" },
  { label: "全部记录", value: "all" },
  { label: "自定义区间", value: "custom" },
];

const gradeOptions = computed(() => [
  { label: "全部档位", value: "" },
  ...["大吉", "吉", "中吉", "小吉", "凶", "大凶"].map((g) => ({ label: g, value: g })),
]);

const groupOptions = computed(() => [
  { label: "全部群聊", value: "" },
  ...groups.value.map((g) => ({
    label: `${g.group_name || g.group_id}（${g.draws}）`,
    value: g.group_id,
  })),
]);

function fmtDate(ts: number): string {
  const d = new Date(ts);
  const m = String(d.getMonth() + 1).padStart(2, "0");
  const day = String(d.getDate()).padStart(2, "0");
  return `${d.getFullYear()}-${m}-${day}`;
}

function params(): Record<string, any> {
  const p: Record<string, any> = { page: page.value, size: size.value };
  if (rangeMode.value === "custom") {
    if (customRange.value && customRange.value.length === 2) {
      p.date_from = fmtDate(customRange.value[0]);
      p.date_to = fmtDate(customRange.value[1]);
    }
  } else if (rangeMode.value !== "all") {
    p.days = Number(rangeMode.value);
  }
  if (grade.value) p.grade = grade.value;
  if (group.value) p.group_id = group.value;
  if (keyword.value.trim()) p.q = keyword.value.trim();
  return p;
}

async function load() {
  loading.value = true;
  try {
    const data = await apiGet<RecordsPayload>("records", params());
    rows.value = data.records.rows;
    total.value = data.records.total;
    groups.value = data.groups || [];
    if (!group.value && data.groups?.length) {
      // 首次加载时把群列表准备好即可，不自动选中
    }
  } catch (e: any) {
    message.error("加载记录失败：" + (e?.message || e));
  } finally {
    loading.value = false;
  }
}

function search() {
  page.value = 1;
  load();
}

function reset() {
  rangeMode.value = "30";
  customRange.value = null;
  grade.value = "";
  group.value = "";
  keyword.value = "";
  page.value = 1;
  load();
}

function openUser(uid: string) {
  router.push({ path: "/user", query: { uid } });
}

watch(detail, (v) => {
  drawerOpen.value = Boolean(v);
});
watch(drawerOpen, (v) => {
  if (!v) detail.value = null;
});

onMounted(load);
</script>

<style scoped>
.panel {
  background: var(--msw-panel);
  border: 1px solid var(--msw-line);
  border-radius: 14px;
  padding: 14px 16px;
}
.filters {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
  margin-bottom: 12px;
}
.sub {
  color: var(--msw-sub);
  font-size: 12px;
}
.table-wrap {
  overflow: auto;
  max-height: 62vh;
}
table {
  width: 100%;
  border-collapse: collapse;
  font-size: 12.5px;
}
th,
td {
  text-align: left;
  padding: 7px 8px;
  border-bottom: 1px solid var(--msw-line);
  white-space: nowrap;
}
th {
  color: var(--msw-sub);
  font-weight: 500;
  position: sticky;
  top: 0;
  background: var(--msw-panel);
}
.nick {
  margin-right: 6px;
}
.uid {
  color: var(--msw-sub);
  font-size: 11px;
}
.grade {
  display: inline-block;
  padding: 1px 8px;
  border-radius: 8px;
  color: #fff;
  font-size: 11.5px;
}
a {
  color: var(--msw-accent);
  cursor: pointer;
}
.pager {
  display: flex;
  justify-content: flex-end;
  margin-top: 12px;
}
.empty {
  color: var(--msw-sub);
  text-align: center;
  padding: 20px 0;
}
.kv {
  list-style: none;
  padding: 0;
  margin: 0 0 12px;
}
.kv li {
  display: flex;
  justify-content: space-between;
  gap: 12px;
  padding: 6px 0;
  border-bottom: 1px dashed var(--msw-line);
  font-size: 13px;
}
.kv li span {
  color: var(--msw-sub);
}
.sign {
  white-space: pre-wrap;
  font-size: 13px;
  line-height: 1.7;
  background: rgba(232, 106, 138, 0.08);
  border-radius: 10px;
  padding: 10px 12px;
  margin-bottom: 12px;
}
</style>
