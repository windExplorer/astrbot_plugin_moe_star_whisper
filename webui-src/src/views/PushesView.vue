<template>
  <section class="panel">
    <n-tabs v-model:value="tab" type="segment" @update:value="onTab">
      <n-tab-pane name="history" tab="推送留档">
        <div class="filters">
          <n-select v-model:value="rangeMode" :options="rangeOptions" style="width: 150px" />
          <n-select
            v-model:value="group"
            :options="groupOptions"
            style="width: 220px"
            filterable
            placeholder="全部群聊"
          />
          <n-button type="primary" size="small" @click="search">查询</n-button>
          <n-button size="small" quaternary @click="reset">重置</n-button>
          <span class="sub">共 {{ total }} 天 · 每群每天一条，永久保留</span>
        </div>

        <div class="table-wrap">
          <table>
            <thead>
              <tr>
                <th>日期</th><th>群</th><th>推送时刻</th><th>内容摘要</th><th>图卡</th><th></th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="row in rows" :key="row.group_id + row.date">
                <td>{{ row.date }}</td>
                <td>
                  <span class="nick">{{ row.group_name || "（未记录群名）" }}</span>
                  <span class="uid">{{ row.group_id }}</span>
                </td>
                <td>{{ row.ts }}</td>
                <td class="cap">{{ firstLine(row.caption) }}</td>
                <td>{{ row.has_card ? "在盘" : "缺失/未生成" }}</td>
                <td><a @click="openDetail(row)">详情</a></td>
              </tr>
              <tr v-if="!rows.length">
                <td colspan="6" class="empty">
                  {{ loading ? "加载中…" : "还没有推送留档——每日推送成功后这里会出现记录（每次推送留档一份）" }}
                </td>
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
      </n-tab-pane>

      <n-tab-pane name="events" tab="事件日志">
        <div class="filters">
          <n-select
            v-model:value="kind"
            :options="kindOptions"
            style="width: 160px"
            placeholder="全部类型"
          />
          <n-button type="primary" size="small" @click="searchEvents">查询</n-button>
          <n-button size="small" quaternary @click="loadEvents">刷新</n-button>
          <span class="sub">
            共 {{ eventsTotal }} 条 · 表内最多保留 500 条（环形清理）；每次推送的
            发起/成功/失败原因都记在这里，重启不丢
          </span>
        </div>

        <div class="events">
          <div class="ev" v-for="(ev, i) in events" :key="i">
            <span class="badge" :class="String(ev.kind)">{{ kindLabel(ev.kind) }}</span>
            <span class="ev-ts">{{ ev.ts }}</span>
            <span class="ev-msg">{{ evText(ev) }}</span>
          </div>
          <div v-if="!events.length" class="empty">
            {{ eventsLoading ? "加载中…" : "暂无推送事件——开启推送并等到推送时刻后，这里会出现每次推送的记录" }}
          </div>
        </div>

        <div class="pager" v-if="eventsTotal > eventsSize">
          <n-pagination
            v-model:page="eventsPage"
            :page-count="Math.ceil(eventsTotal / eventsSize)"
            :page-slot="7"
            size="small"
            @update:page="loadEvents"
          />
        </div>
      </n-tab-pane>
    </n-tabs>
  </section>

  <n-drawer v-model:show="drawerOpen" :width="420" placement="right">
    <n-drawer-content
      :title="detail ? `${detail.date} · ${detail.group_name || detail.group_id}` : '详情'"
      closable
    >
      <template v-if="detail">
        <ul class="kv">
          <li><span>日期</span><b>{{ detail.date }}</b></li>
          <li><span>群</span><b>{{ detail.group_name || detail.group_id }}（{{ detail.group_id }}）</b></li>
          <li><span>推送时刻</span><b>{{ detail.ts }}</b></li>
          <li><span>图卡</span><b>{{ detail.has_card ? "文件在盘" : "缺失或未生成" }}</b></li>
        </ul>
        <div class="caption">{{ detail.caption || "（无文字，本次为纯图卡推送）" }}</div>
      </template>
      <div v-else class="empty">未选择记录</div>
    </n-drawer-content>
  </n-drawer>
</template>

<script setup lang="ts">
import {
  NButton,
  NDrawer,
  NDrawerContent,
  NPagination,
  NSelect,
  NTabPane,
  NTabs,
} from "naive-ui";
import { computed, onMounted, ref } from "vue";
import { useRoute } from "vue-router";
import {
  apiGet,
  type PushEvent,
  type PushHistoryPayload,
  type PushHistoryRow,
  type PushLogPayload,
} from "../api";

const route = useRoute();

// ---------------- 推送留档 ----------------
const rangeMode = ref<string>("30");
const group = ref<string>("");
const rows = ref<PushHistoryRow[]>([]);
const total = ref(0);
const page = ref(1);
const size = ref(20);
const loading = ref(false);
const detail = ref<PushHistoryRow | null>(null);
const drawerOpen = ref(false);
const groups = ref<{ group_id: string; group_name: string; draws: number }[]>([]);

// ---------------- 事件日志 ----------------
const tab = ref<string>(String(route.query.tab || "history") === "events" ? "events" : "history");
const events = ref<PushEvent[]>([]);
const eventsTotal = ref(0);
const eventsPage = ref(1);
const eventsSize = ref(30);
const eventsLoading = ref(false);
const kind = ref<string>("");
const groupNames = ref<Record<string, string>>({});

const rangeOptions = [
  { label: "近 7 天", value: "7" },
  { label: "近 30 天", value: "30" },
  { label: "近 90 天", value: "90" },
  { label: "全部留档", value: "all" },
];

const KIND_LABELS: Record<string, string> = {
  init: "启动",
  cycle: "推送",
  retry: "重试",
  empty: "空跑",
  ok: "成功",
  no_platform: "未匹配",
  skip: "跳过",
  error: "失败",
  loop_error: "异常",
};

const kindOptions = computed(() => [
  { label: "全部类型", value: "" },
  ...Object.entries(KIND_LABELS).map(([value, label]) => ({ label, value })),
]);

const groupOptions = computed(() => [
  { label: "全部群聊", value: "" },
  ...groups.value.map((g) => ({
    label: `${g.group_name || g.group_id}（${g.draws}）`,
    value: g.group_id,
  })),
]);

function kindLabel(k: string) {
  return KIND_LABELS[k] || k;
}

// 事件文案里的「群 <号>」翻译成「群 <名>（<号>）」（映射取不到就原样显示）
function evText(ev: PushEvent): string {
  const name = groupNames.value[String(ev.gid || "")] || "";
  if (!name) return ev.message;
  return ev.message.replace(`群 ${ev.gid}`, `群 ${name}（${ev.gid}）`);
}

function firstLine(text: string): string {
  const t = String(text || "").trim();
  if (!t) return "（纯图卡推送）";
  return t.split("\n")[0] || t;
}

function openDetail(row: PushHistoryRow) {
  detail.value = row;
  drawerOpen.value = true;
}

async function load() {
  loading.value = true;
  try {
    const params: Record<string, any> = { page: page.value, size: size.value };
    if (rangeMode.value !== "all") params.days = rangeMode.value;
    if (group.value) params.group_id = group.value;
    const data = await apiGet<PushHistoryPayload>("pushhistory", params);
    rows.value = data.rows || [];
    total.value = data.history?.total || 0;
    groups.value = data.groups || [];
  } finally {
    loading.value = false;
  }
}

async function loadEvents() {
  eventsLoading.value = true;
  try {
    const params: Record<string, any> = {
      page: eventsPage.value,
      size: eventsSize.value,
    };
    if (kind.value) params.kind = kind.value;
    const data = await apiGet<PushLogPayload>("pushlog", params);
    events.value = data.events || [];
    eventsTotal.value = data.events_meta?.total || 0;
    groupNames.value = data.group_names || {};
  } finally {
    eventsLoading.value = false;
  }
}

function search() {
  page.value = 1;
  load();
}

function searchEvents() {
  eventsPage.value = 1;
  loadEvents();
}

function reset() {
  rangeMode.value = "30";
  group.value = "";
  page.value = 1;
  load();
}

function onTab(name: string) {
  if (name === "events") loadEvents();
  else load();
}

onMounted(() => {
  load();
  if (tab.value === "events") loadEvents();
});
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
  gap: 10px;
  flex-wrap: wrap;
  margin: 10px 0 12px;
}
.sub {
  color: var(--msw-sub);
  font-size: 12px;
}
.table-wrap {
  max-height: 560px;
  overflow: auto;
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
td.cap {
  max-width: 380px;
  overflow: hidden;
  text-overflow: ellipsis;
}
.nick {
  font-weight: 600;
  margin-right: 6px;
}
.uid {
  color: var(--msw-sub);
  font-size: 11px;
}
.pager {
  margin-top: 10px;
  display: flex;
  justify-content: flex-end;
}
a {
  color: var(--msw-accent);
  cursor: pointer;
}
.empty {
  color: var(--msw-sub);
  font-size: 13px;
  padding: 18px 0;
  text-align: center;
}
.kv {
  list-style: none;
  padding: 0;
  margin: 0 0 12px;
}
.kv li {
  display: flex;
  justify-content: space-between;
  padding: 5px 0;
  border-bottom: 1px dashed var(--msw-line);
  font-size: 13px;
  gap: 12px;
}
.kv li span {
  color: var(--msw-sub);
  flex: none;
}
.caption {
  white-space: pre-wrap;
  word-break: break-all;
  background: rgba(232, 106, 138, 0.06);
  border: 1px solid var(--msw-line);
  border-radius: 10px;
  padding: 10px 12px;
  font-size: 13px;
  line-height: 1.7;
}
.events {
  margin-top: 4px;
}
.ev {
  display: flex;
  align-items: baseline;
  gap: 8px;
  padding: 6px 0;
  border-bottom: 1px dashed var(--msw-line);
  font-size: 12.5px;
}
.ev:last-child {
  border-bottom: none;
}
.ev-ts {
  color: var(--msw-sub);
  white-space: nowrap;
  font-variant-numeric: tabular-nums;
}
.ev-msg {
  min-width: 0;
  word-break: break-all;
}
.badge {
  flex: none;
  padding: 1px 8px;
  border-radius: 8px;
  font-size: 11px;
  color: #fff;
  background: var(--msw-sub);
}
.badge.ok {
  background: #3d9a6c;
}
.badge.cycle,
.badge.init,
.badge.retry {
  background: #5b8fd6;
}
.badge.no_platform,
.badge.skip {
  background: #d08b3c;
}
.badge.error,
.badge.loop_error {
  background: #c05656;
}
</style>
