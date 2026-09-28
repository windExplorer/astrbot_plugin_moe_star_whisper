<template>
  <section class="bar">
    <n-radio-group v-model:value="days" size="small" @update:value="load">
      <n-radio-button v-for="d in dayOptions" :key="d.value" :value="d.value">{{ d.label }}</n-radio-button>
    </n-radio-group>
    <span class="sub" v-if="data">
      区间 {{ data.range_from }} ~ {{ data.range_to }} · 六维样本 {{ data.dims_sampled }} 签
    </span>
  </section>

  <div v-if="loading" class="empty">正在加载统计…</div>
  <div v-else-if="errorMsg" class="empty err">{{ errorMsg }}</div>
  <template v-else-if="data">
    <section class="stats">
      <div class="stat"><div class="k">区间抽签</div><div class="v">{{ sumDraws }}</div><div class="d">日均 {{ avgDraws }}</div></div>
      <div class="stat"><div class="k">吉签占比</div><div class="v">{{ luckyRate }}%</div><div class="d">大吉 + 吉</div></div>
      <div class="stat"><div class="k">绘图成功率</div><div class="v">{{ data.jobs.success_rate }}%</div><div class="d">{{ data.jobs.ok }}/{{ data.jobs.total }} 次</div></div>
      <div class="stat"><div class="k">星尘发放</div><div class="v">{{ data.ledger.income }}</div><div class="d">消耗 {{ data.ledger.spend }}</div></div>
      <div class="stat"><div class="k">历史累计抽签</div><div class="v">{{ allDraws }}</div><div class="d">全量统计</div></div>
      <div class="stat"><div class="k">星座覆盖</div><div class="v">{{ data.constellations.length }}</div><div class="d">已绑定生日</div></div>
      <div class="stat"><div class="k">群聊抽签</div><div class="v">{{ groupDraws }}</div><div class="d">私聊 {{ data.private.draws }} 次</div></div>
      <div class="stat"><div class="k">活跃群数</div><div class="v">{{ data.groups_all.length }}</div><div class="d">区间内有人抽签</div></div>
    </section>

    <div class="grid2">
      <section class="panel">
        <div class="head"><b>吉凶档位分布</b><span class="sub">区间内</span></div>
        <EChart :option="gradePie" height="264px" />
      </section>
      <section class="panel">
        <div class="head"><b>六维平均星数</b><span class="sub">恋爱 / 学业 / 财运 / 健康 / 社交 / 摸鱼</span></div>
        <EChart :option="dimRadar" height="264px" />
      </section>
    </div>

    <section class="panel">
      <div class="head"><b>每日档位构成</b><span class="sub">堆叠柱：每天的吉凶分布</span></div>
      <EChart :option="gradeStack" height="300px" />
    </section>

    <div class="grid2">
      <section class="panel">
        <div class="head"><b>抽签时段分布</b><span class="sub">0 ~ 23 点</span></div>
        <EChart :option="hourBar" height="250px" />
      </section>
      <section class="panel">
        <div class="head"><b>幸运色 Top</b><span class="sub">色块为当日幸运色</span></div>
        <EChart :option="colorBar" height="250px" />
      </section>
    </div>

    <div class="grid2">
      <section class="panel">
        <div class="head"><b>幸运物 Top 10</b></div>
        <EChart :option="itemBar" height="280px" />
      </section>
      <section class="panel">
        <div class="head"><b>星座分布</b><span class="sub">来自绑定的生日</span></div>
        <EChart :option="constelPie" height="280px" />
      </section>
    </div>

    <div class="grid2">
      <section class="panel">
        <div class="head"><b>星尘收支</b><span class="sub">按日：发放 / 消耗</span></div>
        <EChart :option="ledgerOption" height="250px" />
      </section>
      <section class="panel">
        <div class="head"><b>绘图任务</b><span class="sub">萌绘联动质量</span></div>
        <EChart :option="jobsOption" height="190px" />
        <ul class="kv">
          <li v-for="(v, k) in data.jobs.by_status" :key="k">
            <span>{{ statusLabel(String(k)) }}</span>
            <b>{{ v.n }} 次 · 平均 {{ v.avg_ms }}ms</b>
          </li>
          <li v-if="!Object.keys(data.jobs.by_status).length"><span>暂无绘图任务</span><b>—</b></li>
        </ul>
      </section>
    </div>

    <section class="panel">
      <div class="head">
        <b>群聊使用分布</b>
        <span class="sub">
          口径：每条记录 = 该用户<b>当天第一次抽签所在的那个群</b>——一天一签（主键 user_id+date），
          当天换到别的群再抽不会新增记录，换签卡也不改群归属，所以一人一天只计入一个群，不会重复计算。
        </span>
      </div>
      <div class="grid2">
        <div>
          <div class="head"><b>抽签占比</b><span class="sub">Top 8 + 其他群</span></div>
          <EChart :option="groupPie" height="250px" />
        </div>
        <div>
          <div class="head">
            <b>群活跃榜</b>
            <span class="sub">
              {{ data.groups_all.length }} 个群有人抽签 · 私聊 {{ data.private.draws }} 次（{{ data.private.users }} 人）
            </span>
          </div>
          <div class="table-wrap">
            <table>
              <thead>
                <tr><th>#</th><th>群</th><th>抽签</th><th>人数</th><th>均分</th><th>大吉</th><th>凶签</th><th>图卡</th><th>最近</th></tr>
              </thead>
              <tbody>
                <tr v-for="(g, i) in data.groups_all.slice(0, 20)" :key="g.group_id">
                  <td>{{ i + 1 }}</td>
                  <td>{{ g.group_name || g.group_id }}</td>
                  <td>{{ g.draws }}</td>
                  <td>{{ g.users }}</td>
                  <td>{{ g.avg_score }}</td>
                  <td>{{ g.great }}</td>
                  <td>{{ g.bad }}</td>
                  <td>{{ g.cards }}</td>
                  <td>{{ g.last_date }}</td>
                </tr>
                <tr v-if="!data.groups_all.length">
                  <td colspan="9" class="empty">区间内还没有群聊抽签数据</td>
                </tr>
              </tbody>
            </table>
          </div>
        </div>
      </div>
    </section>

    <div class="grid2">
      <section class="panel">
        <div class="head"><b>连签档位分布</b><span class="sub">抽签时的连签天数</span></div>
        <EChart :option="streakBar" height="240px" />
      </section>
      <section class="panel">
        <div class="head"><b>星尘流水构成</b><span class="sub">按原因聚合</span></div>
        <ul class="kv">
          <li v-for="r in data.ledger.by_reason" :key="r.reason">
            <span>{{ reasonLabel(r.reason) }}</span>
            <b>{{ r.total > 0 ? "+" : "" }}{{ r.total }}（{{ r.n }} 笔）</b>
          </li>
          <li v-if="!data.ledger.by_reason.length"><span>暂无流水</span><b>—</b></li>
        </ul>
      </section>
    </div>
  </template>
</template>

<script setup lang="ts">
import { NRadioButton, NRadioGroup, useMessage } from "naive-ui";
import { computed, onMounted, ref } from "vue";
import EChart from "../EChart.vue";
import { apiGet, type StatsPayload } from "../api";
import { DIM_KEYS, GRADE_COLORS, GRADE_ORDER, PALETTE, chartPalette } from "../theme";
import { reasonLabel, statusLabel } from "../labels";
import { isDark } from "../store";

const message = useMessage();
const days = ref(30);
const loading = ref(true);
const errorMsg = ref("");
const data = ref<StatsPayload | null>(null);

const dayOptions = [
  { label: "7 天", value: 7 },
  { label: "14 天", value: 14 },
  { label: "30 天", value: 30 },
  { label: "90 天", value: 90 },
  { label: "365 天", value: 365 },
];

const palette = computed(() => chartPalette(isDark.value));
const tip = computed(() => ({
  backgroundColor: palette.value.tooltipBg,
  borderWidth: 0,
  textStyle: { color: palette.value.tooltipText, fontSize: 12 },
}));
const axisCommon = computed(() => ({
  axisLine: { lineStyle: { color: palette.value.axis } },
  axisLabel: { color: palette.value.textDim, fontSize: 11 },
  splitLine: { lineStyle: { color: palette.value.split } },
}));

const sumDraws = computed(() => (data.value?.trend || []).reduce((s, r) => s + r.draws, 0));
const avgDraws = computed(() => {
  const n = (data.value?.trend || []).length;
  return n ? (sumDraws.value / n).toFixed(1) : "0";
});
const allDraws = computed(() =>
  Object.values(data.value?.grades_all || {}).reduce((s, v) => s + Number(v || 0), 0)
);
const luckyRate = computed(() => {
  const g = data.value?.grades || {};
  const total = Object.values(g).reduce((s, v) => s + Number(v || 0), 0);
  if (!total) return 0;
  return Math.round(((Number(g["大吉"] || 0) + Number(g["吉"] || 0)) / total) * 100);
});

const gradePie = computed(() => ({
  tooltip: { trigger: "item", ...tip.value },
  legend: { bottom: 0, textStyle: { color: palette.value.textDim, fontSize: 11 } },
  series: [
    {
      type: "pie",
      radius: ["40%", "66%"],
      center: ["50%", "45%"],
      itemStyle: { borderWidth: 2, borderColor: isDark.value ? "#262336" : "#fff" },
      label: { color: palette.value.text, fontSize: 11, formatter: "{b} {c}" },
      data: GRADE_ORDER.filter((g) => (data.value?.grades || {})[g] != null).map((g) => ({
        name: g,
        value: Number((data.value?.grades || {})[g] || 0),
        itemStyle: { color: GRADE_COLORS[g] },
      })),
    },
  ],
}));

const dimRadar = computed(() => {
  const dims = data.value?.dims || {};
  return {
    tooltip: { ...tip.value },
    radar: {
      indicator: DIM_KEYS.map((k) => ({ name: k, max: 5 })),
      radius: "64%",
      axisName: { color: palette.value.textDim, fontSize: 11 },
      splitLine: { lineStyle: { color: palette.value.split } },
      axisLine: { lineStyle: { color: palette.value.split } },
    },
    series: [
      {
        type: "radar",
        symbolSize: 5,
        lineStyle: { color: "#E86A8A", width: 2 },
        itemStyle: { color: "#E86A8A" },
        areaStyle: { color: "rgba(232,106,138,.25)" },
        data: [{ value: DIM_KEYS.map((k) => Number(dims[k] || 0)), name: "平均星数" }],
      },
    ],
  };
});

const gradeStack = computed(() => {
  const rows = data.value?.trend || [];
  const lookup: Record<string, Record<string, number>> = {};
  for (const item of data.value?.grade_daily || []) {
    lookup[item.date] = lookup[item.date] || {};
    lookup[item.date][item.grade] = item.n;
  }
  return {
    tooltip: { trigger: "axis", axisPointer: { type: "shadow" }, ...tip.value },
    legend: { top: 0, textStyle: { color: palette.value.textDim, fontSize: 11 } },
    grid: { left: 42, right: 20, top: 34, bottom: 26 },
    xAxis: { type: "category", data: rows.map((r) => String(r.date).slice(5)), ...axisCommon.value },
    yAxis: { type: "value", ...axisCommon.value },
    series: GRADE_ORDER.map((g) => ({
      name: g,
      type: "bar",
      stack: "grade",
      barMaxWidth: 26,
      itemStyle: { color: GRADE_COLORS[g] },
      data: rows.map((r) => lookup[r.date]?.[g] || 0),
    })),
  };
});

const hourBar = computed(() => ({
  tooltip: { trigger: "axis", ...tip.value },
  grid: { left: 42, right: 16, top: 18, bottom: 26 },
  xAxis: {
    type: "category",
    data: Array.from({ length: 24 }, (_, i) => String(i)),
    ...axisCommon.value,
  },
  yAxis: { type: "value", ...axisCommon.value },
  series: [
    {
      type: "bar",
      barMaxWidth: 16,
      itemStyle: { color: "#8A6AD6", borderRadius: [3, 3, 0, 0] },
      data: data.value?.hours || [],
    },
  ],
}));

const colorBar = computed(() => {
  const items = [...(data.value?.lucky_colors || [])].reverse();
  return {
    tooltip: { trigger: "axis", axisPointer: { type: "shadow" }, ...tip.value },
    grid: { left: 78, right: 30, top: 12, bottom: 24 },
    xAxis: { type: "value", ...axisCommon.value },
    yAxis: {
      type: "category",
      data: items.map((c) => c.name),
      ...axisCommon.value,
      axisLabel: { color: palette.value.text, fontSize: 11 },
    },
    series: [
      {
        type: "bar",
        barMaxWidth: 14,
        label: { show: true, position: "right", color: palette.value.textDim, fontSize: 11 },
        data: items.map((c) => ({
          value: c.n,
          itemStyle: { color: c.hex || "#E86A8A", borderRadius: [0, 4, 4, 0] },
        })),
      },
    ],
  };
});

const itemBar = computed(() => {
  const items = [...(data.value?.lucky_items || [])].reverse();
  return {
    tooltip: { trigger: "axis", axisPointer: { type: "shadow" }, ...tip.value },
    grid: { left: 98, right: 34, top: 12, bottom: 24 },
    xAxis: { type: "value", ...axisCommon.value },
    yAxis: {
      type: "category",
      data: items.map((c) => c.name),
      ...axisCommon.value,
      axisLabel: { color: palette.value.text, fontSize: 11 },
    },
    series: [
      {
        type: "bar",
        barMaxWidth: 14,
        label: { show: true, position: "right", color: palette.value.textDim, fontSize: 11 },
        itemStyle: { color: "#E8C46A", borderRadius: [0, 4, 4, 0] },
        data: items.map((c) => c.n),
      },
    ],
  };
});

const groupDraws = computed(() =>
  (data.value?.groups_all || []).reduce((s, g) => s + Number(g.draws || 0), 0)
);

const groupPie = computed(() => ({
  tooltip: { trigger: "item", ...tip.value },
  legend: {
    type: "scroll",
    bottom: 0,
    textStyle: { color: palette.value.textDim, fontSize: 11 },
  },
  series: [
    {
      type: "pie",
      radius: ["38%", "64%"],
      center: ["50%", "44%"],
      itemStyle: { borderWidth: 2, borderColor: isDark.value ? "#262336" : "#fff" },
      label: { show: false },
      emphasis: { label: { show: true, color: palette.value.text, fontSize: 12, formatter: "{b}\n{c} 次" } },
      data: (data.value?.group_share || []).map((g, i) => ({
        name: g.name,
        value: g.value,
        itemStyle: { color: PALETTE[i % PALETTE.length] },
      })),
    },
  ],
}));

const constelPie = computed(() => ({
  tooltip: { trigger: "item", ...tip.value },
  legend: { type: "scroll", bottom: 0, textStyle: { color: palette.value.textDim, fontSize: 11 } },
  series: [
    {
      type: "pie",
      radius: ["34%", "62%"],
      center: ["50%", "44%"],
      itemStyle: { borderWidth: 2, borderColor: isDark.value ? "#262336" : "#fff" },
      label: { color: palette.value.text, fontSize: 11, formatter: "{b} {c}" },
      data: (data.value?.constellations || []).map((c, i) => ({
        name: c.name,
        value: c.n,
        itemStyle: { color: PALETTE[i % PALETTE.length] },
      })),
    },
  ],
}));

const ledgerOption = computed(() => {
  const rows = data.value?.ledger?.by_day || [];
  return {
    tooltip: { trigger: "axis", ...tip.value },
    legend: { top: 0, textStyle: { color: palette.value.textDim, fontSize: 11 } },
    grid: { left: 46, right: 20, top: 34, bottom: 26 },
    xAxis: { type: "category", data: rows.map((r) => String(r.day).slice(5)), ...axisCommon.value },
    yAxis: { type: "value", ...axisCommon.value },
    series: [
      {
        name: "发放",
        type: "bar",
        barMaxWidth: 20,
        itemStyle: { color: "#7BC48A", borderRadius: [4, 4, 0, 0] },
        data: rows.map((r) => r.income),
      },
      {
        name: "消耗",
        type: "bar",
        barMaxWidth: 20,
        itemStyle: { color: "#E89A6A", borderRadius: [4, 4, 0, 0] },
        data: rows.map((r) => r.spend),
      },
    ],
  };
});

const jobsOption = computed(() => {
  const rows = data.value?.jobs?.by_day || [];
  return {
    tooltip: { trigger: "axis", ...tip.value },
    legend: { top: 0, textStyle: { color: palette.value.textDim, fontSize: 11 } },
    grid: { left: 42, right: 20, top: 34, bottom: 24 },
    xAxis: { type: "category", data: rows.map((r) => String(r.date).slice(5)), ...axisCommon.value },
    yAxis: { type: "value", ...axisCommon.value },
    series: [
      {
        name: "总任务",
        type: "line",
        smooth: true,
        symbolSize: 5,
        lineStyle: { color: "#8A6AD6", width: 2 },
        itemStyle: { color: "#8A6AD6" },
        data: rows.map((r) => r.total),
      },
      {
        name: "成功",
        type: "line",
        smooth: true,
        symbolSize: 5,
        lineStyle: { color: "#7BC48A", width: 2 },
        itemStyle: { color: "#7BC48A" },
        data: rows.map((r) => r.ok),
      },
    ],
  };
});

const streakBar = computed(() => {
  const s = data.value?.streaks || {};
  const keys = ["1", "2", "3-6", "7-29", "30+"];
  return {
    tooltip: { trigger: "axis", ...tip.value },
    grid: { left: 42, right: 16, top: 16, bottom: 24 },
    xAxis: {
      type: "category",
      data: keys.map((k) => (k === "1" ? "首签" : k + " 天")),
      ...axisCommon.value,
    },
    yAxis: { type: "value", ...axisCommon.value },
    series: [
      {
        type: "bar",
        barMaxWidth: 26,
        itemStyle: { color: "#E86A8A", borderRadius: [4, 4, 0, 0] },
        data: keys.map((k) => Number(s[k] || 0)),
      },
    ],
  };
});

async function load() {
  loading.value = true;
  errorMsg.value = "";
  try {
    data.value = await apiGet<StatsPayload>("stats", { days: days.value });
  } catch (e: any) {
    errorMsg.value = "加载统计失败：" + (e?.message || e);
    message.error(errorMsg.value);
  } finally {
    loading.value = false;
  }
}

onMounted(load);
</script>

<style scoped>
.bar {
  display: flex;
  align-items: center;
  gap: 12px;
  flex-wrap: wrap;
  margin-bottom: 12px;
}
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
  font-size: 22px;
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
.kv {
  list-style: none;
  padding: 0;
  margin: 6px 0 0;
}
.kv li {
  display: flex;
  justify-content: space-between;
  padding: 5px 0;
  border-bottom: 1px dashed var(--msw-line);
  font-size: 12.5px;
}
.kv li span {
  color: var(--msw-sub);
}
table {
  width: 100%;
  border-collapse: collapse;
  font-size: 12.5px;
}
th,
td {
  text-align: left;
  padding: 6px 8px;
  border-bottom: 1px solid var(--msw-line);
}
th {
  color: var(--msw-sub);
  font-weight: 500;
}
.empty {
  color: var(--msw-sub);
  text-align: center;
  padding: 18px 0;
}
.empty.err {
  color: #c05656;
}
</style>
