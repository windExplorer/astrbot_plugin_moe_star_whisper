<template>
  <section class="panel">
    <div class="filters">
      <n-input
        v-model:value="uid"
        placeholder="输入 QQ 号查询该用户的星语档案"
        style="width: 260px"
        clearable
        @keyup.enter="load"
      />
      <n-select v-model:value="months" :options="monthOptions" style="width: 130px" @update:value="load" />
      <n-button type="primary" size="small" @click="load">查询</n-button>
      <span class="sub">最近查询：</span>
      <span class="chip link" v-for="u in recentUids" :key="u" @click="pick(u)">{{ u }}</span>
    </div>
    <div v-if="errorMsg" class="empty err">{{ errorMsg }}</div>
    <div v-else-if="!data" class="empty">输入 QQ 号后点「查询」，或从总览页的表格进入</div>
  </section>

  <template v-if="data">
    <section class="stats">
      <div class="stat">
        <div class="k">今日签</div>
        <div class="v" :style="{ color: data.fortune ? gradeColor(data.fortune.grade) : undefined }">
          {{ data.fortune ? data.fortune.grade : "未抽签" }}
        </div>
        <div class="d">{{ data.fortune ? data.fortune.score + " 分" : data.today }}</div>
      </div>
      <div class="stat"><div class="k">当前连签</div><div class="v">{{ data.profile.streak }}</div><div class="d">最高 {{ data.profile.max_streak }} 天</div></div>
      <div class="stat"><div class="k">星尘余额</div><div class="v">{{ data.balance }}</div><div class="d">全流水可审计</div></div>
      <div class="stat"><div class="k">星座</div><div class="v" style="font-size: 18px">{{ data.profile.constellation || "未绑定" }}</div><div class="d">生日 {{ data.profile.birthday || "未绑定" }}</div></div>
      <div class="stat"><div class="k">背包</div><div class="v" style="font-size: 16px">
        换签×{{ data.items.reroll || 0 }}</div>
        <div class="d">护身符×{{ data.items.amulet || 0 }} · 保护卡×{{ data.items.streak_guard || 0 }} · 香烛×{{ data.items.candle || 0 }}</div>
      </div>
      <div class="stat"><div class="k">抽签总数</div><div class="v">{{ data.history.length }}</div><div class="d">最近记录 {{ data.history.length }} 条</div></div>
    </section>

    <div class="grid2">
      <section class="panel">
        <div class="head"><b>今日签文</b><span class="sub">{{ data.nickname || data.uid }}</span></div>
        <template v-if="data.fortune">
          <div class="tags">
            <span class="grade" :style="{ background: gradeColor(data.fortune.grade) }">{{ data.fortune.grade }}</span>
            <span class="tag">{{ data.fortune.score }} 分</span>
            <span class="tag">连签 {{ data.fortune.streak }}</span>
            <span class="tag">{{ data.fortune.lucky_color || "—" }}</span>
            <span class="tag" :class="{ ok: data.fortune.has_card }">{{ data.fortune.has_card ? "卡已生成" : "无卡文件" }}</span>
            <span class="tag" v-if="data.fortune.reroll_count">已换签 ×{{ data.fortune.reroll_count }}</span>
            <span class="tag" v-if="data.fortune.llm_used">LLM 签文</span>
          </div>
          <div class="sign">{{ data.fortune.sign_text || "（无签文）" }}</div>
          <div class="path" v-if="data.fortune.card_path">{{ data.fortune.card_path }}</div>
        </template>
        <div v-else class="empty">今天还没抽签</div>
      </section>

      <section class="panel">
        <div class="head"><b>星尘流水</b><span class="sub">最近 30 笔</span></div>
        <div class="table-wrap short">
          <table>
            <thead><tr><th>时间</th><th>原因</th><th>变动</th></tr></thead>
            <tbody>
              <tr v-for="(r, i) in data.ledger" :key="i">
                <td>{{ r.created_at }}</td>
                <td>{{ reasonLabel(r.reason) }}</td>
                <td :class="r.delta >= 0 ? 'pos' : 'neg'">{{ r.delta > 0 ? "+" : "" }}{{ r.delta }}</td>
              </tr>
              <tr v-if="!data.ledger.length"><td colspan="3" class="empty">暂无流水</td></tr>
            </tbody>
          </table>
        </div>
      </section>
    </div>

    <section class="panel">
      <div class="head"><b>运势日历</b><span class="sub">近 {{ months }} 个月</span></div>
      <div class="months">
        <div class="month" v-for="m in calendarMonths" :key="m.month">
          <div class="mname">{{ m.month }}</div>
          <div class="week-head">
            <span v-for="w in ['日', '一', '二', '三', '四', '五', '六']" :key="w">{{ w }}</span>
          </div>
          <div class="week" v-for="(week, wi) in m.weeks" :key="wi">
            <span
              v-for="(cell, ci) in week"
              :key="ci"
              class="cell"
              :class="{ blank: !cell, today: cell && cell.date === data.today }"
              :style="cell && cell.hit ? { background: gradeColor(cell.hit.grade), color: '#fff' } : undefined"
              :title="cell && cell.hit ? cell.hit.grade + ' · ' + cell.hit.score : (cell ? '未抽签' : '')"
            >{{ cell ? cell.day : "" }}</span>
          </div>
        </div>
      </div>
    </section>

    <div class="grid2">
      <section class="panel">
        <div class="head"><b>历史签记录</b><span class="sub">最近 60 条</span></div>
        <div class="table-wrap">
          <table>
            <thead><tr><th>日期</th><th>吉凶</th><th>指数</th><th>连签</th><th>幸运色</th><th>图卡</th></tr></thead>
            <tbody>
              <tr v-for="h in data.history" :key="h.date">
                <td>{{ h.date }}</td>
                <td><span class="grade" :style="{ background: gradeColor(h.grade) }">{{ h.grade }}</span></td>
                <td>{{ h.score }}</td>
                <td>{{ h.streak }}</td>
                <td>{{ h.lucky_color || "-" }}</td>
                <td>{{ h.has_card ? "已生成" : "—" }}</td>
              </tr>
              <tr v-if="!data.history.length"><td colspan="6" class="empty">暂无记录</td></tr>
            </tbody>
          </table>
        </div>
      </section>

      <section class="panel">
        <div class="head"><b>绘图任务</b><span class="sub">今日最近 10 条</span></div>
        <div class="table-wrap">
          <table>
            <thead><tr><th>#</th><th>状态</th><th>工作流</th><th>耗时</th><th>错误</th></tr></thead>
            <tbody>
              <tr v-for="j in data.draw_jobs" :key="j.id">
                <td>{{ j.id }}</td>
                <td><span class="tag" :class="{ ok: j.status === 'ok' }">{{ j.status }}</span></td>
                <td>{{ j.workflow || "默认" }}</td>
                <td>{{ j.duration_ms == null ? "—" : j.duration_ms + "ms" }}</td>
                <td class="err-cell">{{ j.error || "" }}</td>
              </tr>
              <tr v-if="!data.draw_jobs.length"><td colspan="5" class="empty">今天没有绘图任务</td></tr>
            </tbody>
          </table>
        </div>
        <div class="head" style="margin-top: 10px"><b>档案信息</b></div>
        <ul class="kv">
          <li><span>最近抽签</span><b>{{ data.profile.last_draw_date || "—" }}</b></li>
          <li><span>换签种子序号</span><b>{{ data.profile.seed_nonce }}</b></li>
          <li><span>昵称快照</span><b>{{ data.nickname || "—" }}</b></li>
        </ul>
      </section>
    </div>
  </template>
</template>

<script setup lang="ts">
import { NButton, NInput, NSelect, useMessage } from "naive-ui";
import { computed, onMounted, ref, watch } from "vue";
import { useRoute } from "vue-router";
import { apiGet, type UserPayload } from "../api";
import { gradeColor } from "../theme";

const message = useMessage();
const route = useRoute();

const uid = ref("");
const months = ref(3);
const data = ref<UserPayload | null>(null);
const errorMsg = ref("");

const monthOptions = [1, 2, 3, 6, 12].map((m) => ({ label: `近 ${m} 个月`, value: m }));

const REASON_LABELS: Record<string, string> = {
  draw: "每日抽签",
  reroll: "换签卡",
  amulet: "护身符",
  candle: "幸运香烛",
  streak_guard: "连签保护卡",
  grant: "管理员发放",
  birthday: "生日彩蛋",
};
function reasonLabel(s: string): string {
  if (REASON_LABELS[s]) return REASON_LABELS[s];
  if (s.startsWith("buy:")) return "购买 " + s.slice(4);
  if (s.startsWith("use:")) return "使用 " + s.slice(4);
  return s;
}

const recentFallback = ref<string[]>([]);
const recentUids = computed(() =>
  data.value?.recent_uids?.length ? data.value.recent_uids : recentFallback.value
);

interface Cell {
  day: number;
  date: string;
  hit: { grade: string; score: number } | null;
}

function buildWeeks(month: string, days: Record<string, { grade: string; score: number }>): (Cell | null)[][] {
  const [y, m] = month.split("-").map(Number);
  const startWeekday = new Date(y, m - 1, 1).getDay();
  const daysInMonth = new Date(y, m, 0).getDate();
  const cells: (Cell | null)[] = [];
  for (let i = 0; i < startWeekday; i++) cells.push(null);
  for (let d = 1; d <= daysInMonth; d++) {
    const dateStr = `${month}-${String(d).padStart(2, "0")}`;
    cells.push({ day: d, date: dateStr, hit: days[dateStr] || null });
  }
  while (cells.length % 7 !== 0) cells.push(null);
  const weeks: (Cell | null)[][] = [];
  for (let i = 0; i < cells.length; i += 7) weeks.push(cells.slice(i, i + 7));
  return weeks;
}

const calendarMonths = computed(() => {
  const map = new Map<string, Record<string, { grade: string; score: number }>>();
  for (const c of data.value?.calendar || []) {
    const key = String(c.date).slice(0, 7);
    if (!map.has(key)) map.set(key, {});
    (map.get(key) as Record<string, { grade: string; score: number }>)[c.date] = {
      grade: c.grade,
      score: c.score,
    };
  }
  return [...map.entries()]
    .sort((a, b) => (a[0] < b[0] ? 1 : -1))
    .map(([month, days]) => ({ month, weeks: buildWeeks(month, days) }));
});

function pick(u: string) {
  uid.value = u;
  load();
}

async function load() {
  const target = uid.value.trim();
  if (!target) {
    message.warning("先填一个 QQ 号");
    return;
  }
  errorMsg.value = "";
  try {
    data.value = await apiGet<UserPayload>("user", { uid: target, months: months.value });
  } catch (e: any) {
    data.value = null;
    errorMsg.value = "查询失败：" + (e?.message || e);
    message.error(errorMsg.value);
  }
}

watch(
  () => route.query.uid,
  (v) => {
    if (typeof v === "string" && v) {
      uid.value = v;
      load();
    }
  }
);

onMounted(() => {
  const q = route.query.uid;
  if (typeof q === "string" && q) {
    uid.value = q;
    load();
    return;
  }
  // 未指定用户时，用「最近调试过的 QQ 号」当快捷入口
  apiGet<{ recent_uids: string[] }>("debug/history")
    .then((d) => {
      recentFallback.value = d?.recent_uids || [];
    })
    .catch(() => {
      /* 忽略：没有历史也能正常查询 */
    });
});
</script>

<style scoped>
.panel {
  background: var(--msw-panel);
  border: 1px solid var(--msw-line);
  border-radius: 14px;
  padding: 14px 16px;
  margin-bottom: 14px;
}
.filters {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}
.stats {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(160px, 1fr));
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
.grid2 {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 14px;
}
@media (max-width: 980px) {
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
.tags {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  margin-bottom: 8px;
}
.tag {
  font-size: 11.5px;
  padding: 2px 9px;
  border-radius: 9px;
  background: rgba(120, 100, 140, 0.12);
}
.tag.ok {
  background: rgba(123, 196, 138, 0.25);
}
.grade {
  font-size: 11.5px;
  padding: 2px 9px;
  border-radius: 9px;
  color: #fff;
}
.sign {
  white-space: pre-wrap;
  font-size: 13px;
  line-height: 1.7;
  background: rgba(232, 106, 138, 0.08);
  border-radius: 10px;
  padding: 10px 12px;
}
.path {
  margin-top: 8px;
  color: var(--msw-sub);
  font-size: 11px;
  word-break: break-all;
}
.months {
  display: flex;
  gap: 18px;
  flex-wrap: wrap;
}
.month {
  min-width: 236px;
}
.mname {
  font-size: 12.5px;
  margin-bottom: 4px;
  color: var(--msw-sub);
}
.week-head,
.week {
  display: grid;
  grid-template-columns: repeat(7, 1fr);
  gap: 3px;
}
.week-head span {
  text-align: center;
  font-size: 11px;
  color: var(--msw-sub);
}
.cell {
  height: 26px;
  border-radius: 7px;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 11.5px;
  background: rgba(120, 100, 140, 0.08);
}
.cell.blank {
  background: transparent;
}
.cell.today {
  outline: 2px solid var(--msw-accent);
}
.table-wrap {
  overflow: auto;
  max-height: 420px;
}
.table-wrap.short {
  max-height: 220px;
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
  white-space: nowrap;
}
th {
  color: var(--msw-sub);
  font-weight: 500;
  position: sticky;
  top: 0;
  background: var(--msw-panel);
}
.pos {
  color: #3a9a5c;
}
.neg {
  color: #c05656;
}
.err-cell {
  max-width: 220px;
  overflow: hidden;
  text-overflow: ellipsis;
  color: var(--msw-sub);
}
.kv {
  list-style: none;
  padding: 0;
  margin: 0;
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
.chip {
  font-size: 12px;
  padding: 2px 10px;
  border-radius: 10px;
  background: rgba(232, 106, 138, 0.1);
}
.chip.link {
  cursor: pointer;
}
.chip.link:hover {
  background: var(--msw-accent);
  color: #fff;
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
