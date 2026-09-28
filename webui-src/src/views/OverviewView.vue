<template>
  <div v-if="loading" class="empty">正在加载总览…</div>
  <div v-else-if="errorMsg" class="empty err">{{ errorMsg }}</div>
  <template v-else>
    <section class="stats">
      <div class="stat" v-for="card in statCards" :key="card.label">
        <div class="k">{{ card.label }}</div>
        <div class="v">{{ card.value }}</div>
        <div class="d">{{ card.desc }}</div>
      </div>
    </section>

    <section class="panel">
      <div class="head">
        <b>近 14 天趋势</b>
        <span class="sub">柱=每日抽签数 · 线=平均幸运指数</span>
      </div>
      <EChart :option="trendOption" height="280px" />
    </section>

    <div class="grid2">
      <section class="panel">
        <div class="head"><b>近 14 天吉凶分布</b></div>
        <EChart :option="gradeOption" height="260px" />
      </section>
      <section class="panel">
        <div class="head"><b>今日概况</b><span class="sub">{{ data?.today }}</span></div>
        <ul class="kv">
          <li><span>今日抽签</span><b>{{ data?.day?.draws ?? 0 }}</b></li>
          <li><span>今日人数</span><b>{{ data?.day?.users ?? 0 }}</b></li>
          <li><span>今日均分</span><b>{{ data?.day?.avg_score ?? 0 }}</b></li>
          <li><span>吉签 / 凶签</span><b>{{ data?.day?.lucky ?? 0 }} / {{ data?.day?.unlucky ?? 0 }}</b></li>
          <li><span>库内记录</span><b>{{ data?.counts?.fortunes ?? 0 }} 签</b></li>
          <li><span>累计星尘</span><b>{{ data?.counts?.ledger ?? 0 }} 笔流水</b></li>
        </ul>
        <div class="chips">
          <span class="chip" v-for="(v, k) in data?.switches || {}" :key="k">
            {{ labelOf(String(k)) }}：{{ formatSwitch(v) }}
          </span>
        </div>
      </section>
    </div>

    <section class="panel">
      <div class="head"><b>最近抽签</b><span class="sub">最新 10 条</span></div>
      <div class="table-wrap">
        <table>
          <thead>
            <tr>
              <th>日期</th><th>用户</th><th>吉凶</th><th>指数</th><th>连签</th>
              <th>群</th><th>幸运色</th><th>图卡</th><th></th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="row in data?.recent || []" :key="row.uid + row.date">
              <td>{{ row.date }}</td>
              <td class="user-cell">
                <UserAvatar :uid="row.uid" :src="row.avatar" :name="row.nickname" :size="24" />
                <span>{{ row.nickname || row.uid }}</span>
              </td>
              <td><span class="grade" :style="{ background: gradeColor(row.grade) }">{{ row.grade }}</span></td>
              <td>{{ row.score }}</td>
              <td>{{ row.streak }}</td>
              <td>{{ row.group_name || row.group_id || "私聊" }}</td>
              <td>{{ row.lucky_color || "-" }}</td>
              <td>{{ row.has_card ? "已生成" : "—" }}</td>
              <td><a @click="openUser(row.uid)">查看</a></td>
            </tr>
            <tr v-if="!(data?.recent || []).length"><td colspan="9" class="empty">还没有抽签记录</td></tr>
          </tbody>
        </table>
      </div>
    </section>

    <section class="panel">
      <div class="head">
        <b>最近活跃用户</b>
        <span class="sub">点击查看档案与运势日历（完整名单见「用户查询」页）</span>
      </div>
      <div class="users">
        <div class="user" v-for="u in data?.recent_users || []" :key="u.uid" @click="openUser(u.uid)">
          <UserAvatar :uid="u.uid" :src="u.avatar" :name="u.nickname" :size="36" />
          <div class="info">
            <div class="nick">{{ u.nickname || "（未记录昵称）" }}</div>
            <div class="uid">QQ {{ u.uid }}</div>
          </div>
          <div class="mini">
            {{ u.draws }} 签<br />
            {{ u.last_date }}
          </div>
        </div>
        <div v-if="!(data?.recent_users || []).length" class="sub">暂无数据</div>
      </div>
    </section>
  </template>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from "vue";
import { useMessage } from "naive-ui";
import { useRouter } from "vue-router";
import EChart from "../EChart.vue";
import UserAvatar from "../components/UserAvatar.vue";
import { apiGet, type Overview } from "../api";
import { GRADE_COLORS, GRADE_ORDER, chartPalette, gradeColor } from "../theme";
import { isDark } from "../store";

const router = useRouter();
const message = useMessage();

const loading = ref(true);
const errorMsg = ref("");
const data = ref<Overview | null>(null);

const SWITCH_LABELS: Record<string, string> = {
  timezone: "时区",
  output_mode: "出签方式",
  economy_enabled: "道具经济",
  llm_enabled: "LLM 星语",
  draw_enabled: "AI 封面图",
  daily_push_enabled: "每日推送",
  daily_push_time: "推送时刻",
  draw_workflow: "工作流",
};

function labelOf(key: string) {
  return SWITCH_LABELS[key] || key;
}
function formatSwitch(v: any) {
  if (typeof v === "boolean") return v ? "开" : "关";
  if (v === "" || v === null || v === undefined) return "未设置";
  return String(v);
}

const statCards = computed(() => {
  const t = data.value?.totals;
  const s = data.value?.counts || {};
  return [
    { label: "累计抽签", value: t?.draws ?? 0, desc: `覆盖 ${t?.days ?? 0} 天` },
    { label: "参与用户", value: t?.users ?? 0, desc: `${t?.groups ?? 0} 个群 / 私聊` },
    { label: "今日抽签", value: data.value?.day?.draws ?? 0, desc: `${data.value?.day?.users ?? 0} 人参与` },
    { label: "今日均分", value: data.value?.day?.avg_score ?? 0, desc: "幸运指数均值" },
    { label: "图卡文件", value: t?.cards ?? 0, desc: "已生成卡面" },
    { label: "档案记录", value: s.profiles ?? 0, desc: `${s.draw_jobs ?? 0} 次绘图任务` },
  ];
});

function gradeList(map: Record<string, number> | undefined) {
  const src = map || {};
  return GRADE_ORDER.filter((g) => src[g] != null).map((g) => ({
    name: g,
    value: Number(src[g] || 0),
  }));
}

const palette = computed(() => chartPalette(isDark.value));

const trendOption = computed(() => {
  const p = palette.value;
  const rows = data.value?.trend || [];
  return {
    tooltip: {
      trigger: "axis",
      backgroundColor: p.tooltipBg,
      borderWidth: 0,
      textStyle: { color: p.tooltipText, fontSize: 12 },
    },
    legend: { data: ["抽签数", "幸运指数"], textStyle: { color: p.textDim }, top: 0 },
    grid: { left: 40, right: 40, top: 36, bottom: 24 },
    xAxis: {
      type: "category",
      data: rows.map((r) => String(r.date).slice(5)),
      axisLine: { lineStyle: { color: p.axis } },
      axisLabel: { color: p.textDim, fontSize: 11 },
    },
    yAxis: [
      {
        type: "value",
        axisLabel: { color: p.textDim, fontSize: 11 },
        splitLine: { lineStyle: { color: p.split } },
      },
      {
        type: "value",
        min: 0,
        max: 100,
        axisLabel: { color: p.textDim, fontSize: 11 },
        splitLine: { show: false },
      },
    ],
    series: [
      {
        name: "抽签数",
        type: "bar",
        barMaxWidth: 22,
        itemStyle: { color: "#E86A8A", borderRadius: [4, 4, 0, 0] },
        data: rows.map((r) => r.draws),
      },
      {
        name: "幸运指数",
        type: "line",
        yAxisIndex: 1,
        smooth: true,
        symbolSize: 6,
        lineStyle: { width: 2.5, color: "#8A6AD6" },
        itemStyle: { color: "#8A6AD6" },
        areaStyle: { color: p.area },
        data: rows.map((r) => r.avg_score),
      },
    ],
  };
});

const gradeOption = computed(() => {
  const p = palette.value;
  const items = gradeList(data.value?.grades);
  return {
    tooltip: { trigger: "item", backgroundColor: p.tooltipBg, borderWidth: 0, textStyle: { color: p.tooltipText } },
    legend: { bottom: 0, textStyle: { color: p.textDim, fontSize: 11 } },
    series: [
      {
        type: "pie",
        radius: ["42%", "68%"],
        center: ["50%", "46%"],
        avoidLabelOverlap: true,
        itemStyle: { borderWidth: 2, borderColor: isDark.value ? "#262336" : "#fff" },
        label: { color: p.text, fontSize: 11, formatter: "{b} {c}" },
        data: items.map((it) => ({
          ...it,
          itemStyle: { color: GRADE_COLORS[it.name] || "#E86A8A" },
        })),
      },
    ],
  };
});

function openUser(uid: string) {
  router.push({ path: "/user", query: { uid } });
}

async function load() {
  loading.value = true;
  errorMsg.value = "";
  try {
    data.value = await apiGet<Overview>("overview", { days: 14 });
  } catch (e: any) {
    errorMsg.value = "加载失败：" + (e?.message || e);
    message.error(errorMsg.value);
  } finally {
    loading.value = false;
  }
}

onMounted(load);
</script>

<style scoped>
.stats {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(150px, 1fr));
  gap: 12px;
  margin-bottom: 14px;
}
.stat {
  background: var(--msw-panel);
  border: 1px solid var(--msw-line);
  border-radius: 14px;
  padding: 12px 14px;
}
.stat .k {
  color: var(--msw-sub);
  font-size: 12px;
}
.stat .v {
  font-size: 24px;
  font-weight: 700;
  margin: 4px 0 2px;
  color: var(--msw-accent);
}
.stat .d {
  color: var(--msw-sub);
  font-size: 11px;
}
.panel {
  background: var(--msw-panel);
  border: 1px solid var(--msw-line);
  border-radius: 14px;
  padding: 14px 16px;
  margin-bottom: 14px;
}
.head {
  display: flex;
  align-items: baseline;
  gap: 10px;
  margin-bottom: 8px;
}
.head b {
  font-size: 14px;
}
.sub {
  color: var(--msw-sub);
  font-size: 12px;
}
.grid2 {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 14px;
}
@media (max-width: 900px) {
  .grid2 {
    grid-template-columns: 1fr;
  }
}
.kv {
  list-style: none;
  padding: 0;
  margin: 0 0 10px;
}
.kv li {
  display: flex;
  justify-content: space-between;
  padding: 5px 0;
  border-bottom: 1px dashed var(--msw-line);
  font-size: 13px;
}
.kv li span {
  color: var(--msw-sub);
}
.chips {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}
.chip {
  font-size: 12px;
  padding: 3px 10px;
  border-radius: 10px;
  background: rgba(232, 106, 138, 0.1);
  color: var(--msw-text);
}
.chip.link {
  cursor: pointer;
}
.chip.link:hover {
  background: var(--msw-accent);
  color: #fff;
}
.user-cell {
  display: flex;
  align-items: center;
  gap: 6px;
}
.users {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(248px, 1fr));
  gap: 8px;
}
.user {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 6px 8px;
  border: 1px solid var(--msw-line);
  border-radius: 12px;
  cursor: pointer;
  transition: border-color 0.15s, background 0.15s;
}
.user:hover {
  border-color: var(--msw-accent);
  background: rgba(232, 106, 138, 0.06);
}
.user .info {
  flex: 1;
  min-width: 0;
}
.user .nick {
  font-size: 13px;
  font-weight: 600;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
.user .uid {
  color: var(--msw-sub);
  font-size: 11px;
}
.user .mini {
  color: var(--msw-sub);
  font-size: 11px;
  text-align: right;
  white-space: nowrap;
}
.table-wrap {
  max-height: 360px;
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
.empty {
  color: var(--msw-sub);
  font-size: 13px;
  padding: 18px 0;
  text-align: center;
}
.empty.err {
  color: #c05656;
}
</style>
