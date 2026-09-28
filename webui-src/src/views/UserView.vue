<template>
  <section class="panel">
    <div class="head">
      <b>抽过签的用户</b>
      <span class="sub">共 {{ users.total }} 人 · 一人一天只算一次（按当天首次抽签所在会话归属）</span>
      <span class="spacer"></span>
      <n-input
        v-model:value="keyword"
        placeholder="搜 QQ 号或昵称"
        style="width: 200px"
        size="small"
        clearable
        @keyup.enter="loadUsers(1)"
      />
      <n-select
        v-model:value="order"
        :options="orderOptions"
        style="width: 150px"
        size="small"
        @update:value="loadUsers(1)"
      />
      <n-button size="small" type="primary" @click="loadUsers(1)">搜索</n-button>
    </div>

    <div class="users">
      <div
        class="user"
        v-for="u in users.rows"
        :key="u.uid"
        :class="{ active: u.uid === activeUid }"
        @click="openUser(u.uid)"
      >
        <UserAvatar :uid="u.uid" :src="u.avatar" :name="u.nickname" :size="44" />
        <div class="info">
          <div class="nick">{{ u.nickname || "（未记录昵称）" }}</div>
          <div class="uid">QQ {{ u.uid }}</div>
          <div class="uid" v-if="u.last_group_name || u.last_group_id">
            最近在 {{ u.last_group_name || u.last_group_id }}
          </div>
        </div>
        <div class="mini">
          <span class="badge">{{ u.draws }} 签</span>
          <span>均分 {{ u.avg_score }}</span>
          <span>最近 {{ u.last_date }}</span>
        </div>
      </div>
      <div v-if="!users.rows.length" class="empty">
        {{ usersLoading ? "加载中…" : "还没有人抽过签" }}
      </div>
    </div>

    <div class="pager" v-if="users.total > users.size">
      <n-pagination
        v-model:page="page"
        :page-count="Math.ceil(users.total / users.size)"
        :page-slot="7"
        size="small"
        @update:page="loadUsers()"
      />
    </div>
  </section>

  <section class="panel" v-if="activeUid">
    <div class="filters">
      <UserAvatar :uid="activeUid" :name="data?.nickname || activeUid" :size="28" />
      <b>{{ data?.nickname || activeUid }}</b>
      <span class="sub">QQ {{ activeUid }}</span>
      <span class="spacer"></span>
      <n-select v-model:value="months" :options="monthOptions" style="width: 130px" size="small" @update:value="load" />
      <n-button size="small" quaternary @click="clearActive">关闭</n-button>
    </div>
    <div v-if="errorMsg" class="empty err">{{ errorMsg }}</div>
    <div v-else-if="!data" class="empty">正在加载该用户档案…</div>
  </section>

  <section class="panel" v-else>
    <div class="empty">点上方任意用户查看档案与运势日历（也可从总览页的表格点击进入）</div>
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
                <td><span class="tag" :class="{ ok: j.status === 'ok' }">{{ statusLabel(j.status) }}</span></td>
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
import { apiGet, type UserPayload, type UsersPayload } from "../api";
import { gradeColor } from "../theme";
import { reasonLabel, statusLabel } from "../labels";
import UserAvatar from "../components/UserAvatar.vue";

const message = useMessage();
const route = useRoute();

const uid = ref("");
const activeUid = ref("");
const months = ref(3);
const data = ref<UserPayload | null>(null);
const errorMsg = ref("");

const monthOptions = [1, 2, 3, 6, 12].map((m) => ({ label: `近 ${m} 个月`, value: m }));

// 用户列表（头像 / 昵称 / QQ / 抽签天数）：分页 + 搜索 + 排序
const keyword = ref("");
const order = ref("last");
const page = ref(1);
const usersLoading = ref(false);
const users = ref<UsersPayload["users"]>({ total: 0, page: 1, size: 24, rows: [] });
const orderOptions = [
  { label: "最近活跃", value: "last" },
  { label: "抽签最多", value: "draws" },
  { label: "均分最高", value: "score" },
];

async function loadUsers(toPage?: number) {
  if (typeof toPage === "number") page.value = toPage;
  usersLoading.value = true;
  try {
    const res = await apiGet<UsersPayload>("users", {
      page: page.value,
      size: 24,
      q: keyword.value.trim(),
      order: order.value,
    });
    users.value = res.users;
  } catch (e: any) {
    message.error("加载用户列表失败：" + (e?.message || e));
  } finally {
    usersLoading.value = false;
  }
}

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

function openUser(u: string) {
  activeUid.value = u;
  uid.value = u;
  load();
}

function clearActive() {
  activeUid.value = "";
  data.value = null;
  errorMsg.value = "";
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
    if (typeof v === "string" && v) openUser(v);
  }
);

onMounted(() => {
  loadUsers(1);
  const q = route.query.uid;
  if (typeof q === "string" && q) openUser(q);
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
.spacer {
  flex: 1;
}
.users {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(286px, 1fr));
  gap: 10px;
}
.user {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 8px 10px;
  border: 1px solid var(--msw-line);
  border-radius: 12px;
  cursor: pointer;
  transition: border-color 0.15s, background 0.15s;
}
.user:hover {
  border-color: var(--msw-accent);
  background: rgba(232, 106, 138, 0.06);
}
.user.active {
  border-color: var(--msw-accent);
  background: rgba(232, 106, 138, 0.12);
}
.user .info {
  flex: 1;
  min-width: 0;
}
.user .nick {
  font-size: 13.5px;
  font-weight: 600;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
.user .uid {
  color: var(--msw-sub);
  font-size: 11px;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
.user .mini {
  display: flex;
  flex-direction: column;
  align-items: flex-end;
  gap: 2px;
  color: var(--msw-sub);
  font-size: 11px;
  white-space: nowrap;
}
.badge {
  background: rgba(232, 106, 138, 0.16);
  color: var(--msw-text);
  border-radius: 8px;
  padding: 1px 7px;
}
.pager {
  display: flex;
  justify-content: flex-end;
  margin-top: 10px;
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
