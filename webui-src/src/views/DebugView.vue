<template>
  <section class="panel">
    <div class="filters">
      <n-input
        v-model:value="uid"
        placeholder="要调试的 QQ 号，例如 10086"
        style="width: 240px"
        clearable
        @keyup.enter="loadState()"
      />
      <n-button type="primary" size="small" @click="loadState()">查状态</n-button>
      <span class="sub">最近：</span>
      <span class="chip link" v-for="u in recent" :key="u" @click="pick(u)">{{ u }}</span>
    </div>
    <div class="sub" style="margin-top: 6px">
      作用对象是「该 QQ 号的今日签」（时区按插件配置）。重抽 = 换种子重算运势，底图复用当日成功记录；
      重绘 = 只重渲染卡面（改 card.py 样式后看效果）；重置 = 删除今日记录与卡文件（不可恢复）。
    </div>
    <div v-if="msg" class="msg" :class="{ err: msgErr }">{{ msg }}</div>
  </section>

  <template v-if="state">
    <section class="stats">
      <div class="stat">
        <div class="k">今日签</div>
        <div class="v" :style="{ color: state.fortune ? gradeColor(state.fortune.grade) : undefined }">
          {{ state.fortune ? state.fortune.grade : "未抽签" }}
        </div>
        <div class="d">{{ state.date }}</div>
      </div>
      <div class="stat"><div class="k">幸运指数</div><div class="v">{{ state.fortune?.score ?? "—" }}</div><div class="d">连签 {{ state.fortune?.streak ?? 0 }} 天</div></div>
      <div class="stat"><div class="k">星尘/背包</div><div class="v" style="font-size: 18px">{{ state.balance }}</div><div class="d">换签×{{ state.items.reroll || 0 }} · 护身符×{{ state.items.amulet || 0 }}</div></div>
      <div class="stat"><div class="k">档案</div><div class="v" style="font-size: 16px">{{ state.profile.constellation || "未绑定" }}</div><div class="d">当前连签 {{ state.profile.streak }} / 最高 {{ state.profile.max_streak }}</div></div>
    </section>

    <section class="panel">
      <div class="head">
        <b>今日签 · {{ state.uid }}</b>
        <span class="spacer"></span>
        <n-button size="small" :disabled="!state.fortune" @click="act('debug/redraw', '重抽')">重抽</n-button>
        <n-button size="small" :disabled="!state.fortune" @click="act('debug/rerender', '重绘')">重绘</n-button>
        <n-popconfirm @positive-click="act('debug/reset', '重置')">
          <template #trigger>
            <n-button size="small" type="error" ghost :disabled="!state.fortune">重置</n-button>
          </template>
          确认删除该 QQ 号的今日签记录与卡文件？
        </n-popconfirm>
      </div>
      <template v-if="state.fortune">
        <div class="tags">
          <span class="grade" :style="{ background: gradeColor(state.fortune.grade) }">{{ state.fortune.grade }}</span>
          <span class="tag">{{ state.fortune.score }} 分</span>
          <span class="tag">幸运色 {{ state.fortune.lucky_color || "—" }}</span>
          <span class="tag" :class="{ ok: state.fortune.has_card }">{{ state.fortune.has_card ? "卡已生成" : "无卡文件" }}</span>
          <span class="tag" v-if="state.fortune.reroll_count">已换签 ×{{ state.fortune.reroll_count }}</span>
          <span class="tag" v-if="state.fortune.llm_used">LLM 签文</span>
          <span class="tag bad" v-if="state.fortune.llm_note">LLM：{{ state.fortune.llm_note }}</span>
        </div>
        <div class="sign">{{ state.fortune.sign_text || "（无签文）" }}</div>
        <div class="sub path" v-if="state.fortune.card_path">{{ state.fortune.card_path }}</div>
      </template>
      <div v-else class="empty">该用户今天还没有签记录（在聊天里用 /星语 抽一支）</div>
    </section>

    <div class="grid2">
      <section class="panel">
        <div class="head"><b>关键配置快照</b></div>
        <div class="tags">
          <span class="tag" :class="{ ok: state.config.draw_enabled }">绘图 {{ state.config.draw_enabled ? "开" : "关" }}</span>
          <span class="tag" :class="{ ok: state.config.llm_enabled }">LLM {{ state.config.llm_enabled ? "开" : "关" }}</span>
          <span class="tag">出签 {{ state.config.output_mode }}</span>
          <span class="tag" :class="{ ok: state.config.economy_enabled }">经济 {{ state.config.economy_enabled ? "开" : "关" }}</span>
          <span class="tag">推送 {{ state.config.daily_push_enabled ? state.config.daily_push_time : "关" }}</span>
          <span class="tag" v-if="state.config.draw_workflow">工作流 {{ state.config.draw_workflow }}</span>
        </div>
        <ul class="kv">
          <li><span>生日绑定</span><b>{{ state.profile.birthday || "未绑定" }}</b></li>
          <li><span>最近抽签</span><b>{{ state.profile.last_draw_date || "—" }}</b></li>
          <li><span>连签保护卡</span><b>{{ state.items.streak_guard || 0 }}</b></li>
          <li><span>幸运香烛</span><b>{{ state.items.candle || 0 }}</b></li>
        </ul>
      </section>

      <section class="panel">
        <div class="head"><b>今日绘图任务</b><span class="sub">最近 10 条</span></div>
        <div class="table-wrap">
          <table>
            <thead><tr><th>#</th><th>状态</th><th>工作流</th><th>耗时</th><th>错误</th></tr></thead>
            <tbody>
              <tr v-for="j in state.draw_jobs" :key="j.id">
                <td>{{ j.id }}</td>
                <td><span class="tag" :class="{ ok: j.status === 'ok' }">{{ statusLabel(j.status) }}</span></td>
                <td>{{ j.workflow || "默认" }}</td>
                <td>{{ j.duration_ms == null ? "—" : j.duration_ms + "ms" }}</td>
                <td class="err-cell">{{ j.error || "" }}</td>
              </tr>
              <tr v-if="!state.draw_jobs.length"><td colspan="5" class="empty">今天没有绘图任务</td></tr>
            </tbody>
          </table>
        </div>
      </section>
    </div>
  </template>
</template>

<script setup lang="ts">
import { NButton, NInput, NPopconfirm, useMessage } from "naive-ui";
import { onMounted, ref } from "vue";
import { apiGet, apiPost } from "../api";
import { gradeColor } from "../theme";
import { statusLabel } from "../labels";

const message = useMessage();

interface DebugState {
  uid: string;
  date: string;
  fortune: {
    grade: string;
    score: number;
    streak: number;
    sign_text: string;
    lucky_color: string;
    card_path: string;
    has_card: boolean;
    reroll_count: number;
    llm_used: boolean;
    llm_note: string;
  } | null;
  profile: {
    constellation: string;
    birthday: string;
    streak: number;
    max_streak: number;
    last_draw_date: string;
  };
  balance: number;
  items: Record<string, number>;
  draw_jobs: { id: number; status: string; workflow: string; error: string; duration_ms: number }[];
  config: Record<string, any>;
  recent_uids: string[];
}

const uid = ref("");
const state = ref<DebugState | null>(null);
const recent = ref<string[]>([]);
const msg = ref("");
const msgErr = ref(false);

function say(text: string, isErr = false) {
  msg.value = text;
  msgErr.value = isErr;
}

async function loadState(keepMsg = false) {
  const target = uid.value.trim();
  if (!target) {
    say("先填 QQ 号", true);
    return;
  }
  try {
    const data = await apiGet<DebugState>("debug/state", { uid: target });
    state.value = data;
    recent.value = data.recent_uids || recent.value;
    if (!keepMsg) say("");
  } catch (e: any) {
    state.value = null;
    const text = "查询失败：" + (e?.message || e);
    say(text, true);
    message.error(text);
  }
}

async function act(endpoint: string, label: string) {
  const target = uid.value.trim();
  if (!target) {
    say("先填 QQ 号", true);
    return;
  }
  try {
    const res = await apiPost<any>(endpoint, { uid: target });
    await loadState(true);
    const extra = res?.fortune
      ? `（${res.fortune.grade} · ${res.fortune.score} 分）`
      : "";
    say(`${label}完成。${res?.note || ""}${extra}`);
    message.success(`${label}完成`);
  } catch (e: any) {
    const text = `${label}失败：` + (e?.message || e);
    say(text, true);
    message.error(text);
  }
}

function pick(u: string) {
  uid.value = u;
  loadState();
}

onMounted(async () => {
  try {
    const d = await apiGet<{ recent_uids: string[] }>("debug/history");
    recent.value = d?.recent_uids || [];
  } catch {
    /* 忽略 */
  }
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
  align-items: center;
  gap: 8px;
  margin-bottom: 10px;
  flex-wrap: wrap;
}
.head b {
  font-size: 14px;
}
.spacer {
  flex: 1;
}
.sub {
  color: var(--msw-sub);
  font-size: 12px;
  line-height: 1.6;
}
.msg {
  margin-top: 8px;
  font-size: 13px;
  white-space: pre-wrap;
}
.msg.err {
  color: #c05656;
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
.tag.bad {
  background: rgba(192, 86, 86, 0.18);
  color: #c05656;
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
  word-break: break-all;
}
.kv {
  list-style: none;
  padding: 0;
  margin: 10px 0 0;
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
.table-wrap {
  overflow: auto;
  max-height: 300px;
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
}
.err-cell {
  max-width: 200px;
  overflow: hidden;
  text-overflow: ellipsis;
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
  font-size: 13px;
}
</style>
