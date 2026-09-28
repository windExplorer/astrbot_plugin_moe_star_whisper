<template>
  <div v-if="loading" class="empty">正在加载配置…</div>
  <div v-else-if="errorMsg" class="empty err">{{ errorMsg }}</div>
  <template v-else>
    <section class="panel head-panel">
      <div>
        <b>参数配置</b>
        <div class="sub">
          字段与类型来自插件自己的 <code>_conf_schema.json</code>（唯一来源，新增配置键会自动出现在这里）。
          保存只提交<b>被改动过</b>的字段，未改动的原样保留。
        </div>
      </div>
      <div class="meta">
        <n-tag size="small" :bordered="false">v{{ meta.version }}</n-tag>
        <n-tag size="small" :bordered="false" :type="meta.writable ? 'success' : 'error'">
          {{ meta.writable ? "可写" : "只读" }}
        </n-tag>
        <n-tag size="small" :bordered="false">{{ meta.field_count }} 个字段</n-tag>
      </div>
    </section>

    <section class="panel" v-for="group in groups" :key="group.name">
      <div class="head">
        <b>{{ group.name }}</b>
        <span class="sub">{{ group.description }}</span>
        <span class="spacer"></span>
        <n-button size="small" type="primary" :disabled="!meta.writable || !dirtyKeys(group).length" @click="save(group)">
          保存本分区（{{ dirtyKeys(group).length }}）
        </n-button>
      </div>

      <div class="fields">
        <div class="field" v-for="key in group.keys" :key="key">
          <div class="label">
            <span>{{ titleOf(key) }}</span>
            <code>{{ key }}</code>
          </div>
          <div class="control">
            <n-switch v-if="typeOf(key) === 'bool'" v-model:value="form[key]" />
            <n-input-number
              v-else-if="typeOf(key) === 'int' || typeOf(key) === 'float'"
              v-model:value="form[key]"
              :min="minOf(key)"
              :max="maxOf(key)"
              :step="typeOf(key) === 'float' ? 0.1 : 1"
              style="width: 100%"
            />
            <n-select
              v-else-if="typeOf(key) === 'string' && optionsOf(key).length"
              v-model:value="form[key]"
              :options="optionsOf(key)"
              style="width: 100%"
            />
            <n-input
              v-else-if="typeOf(key) === 'dict'"
              v-model:value="form[key]"
              type="textarea"
              :autosize="{ minRows: 3, maxRows: 8 }"
              placeholder="JSON 对象，例如 {&quot;大吉&quot;: 20}"
            />
            <n-input
              v-else-if="typeOf(key) === 'text'"
              v-model:value="form[key]"
              type="textarea"
              :autosize="{ minRows: 3, maxRows: 10 }"
            />
            <n-input v-else v-model:value="form[key]" />
            <div class="hint" v-if="hintOf(key)">{{ hintOf(key) }}</div>
          </div>
        </div>
        <div v-if="!group.keys.length" class="empty">该分区暂无字段</div>
      </div>
    </section>

    <section class="panel" v-if="skipped.length">
      <div class="head"><b>上次保存被跳过的字段</b></div>
      <ul class="kv">
        <li v-for="(s, i) in skipped" :key="i"><span>{{ s }}</span></li>
      </ul>
    </section>
  </template>
</template>

<script setup lang="ts">
import { NButton, NInput, NInputNumber, NSelect, NSwitch, NTag, useMessage } from "naive-ui";
import { computed, onMounted, ref } from "vue";
import { apiGet, apiPost, type ConfigPayload } from "../api";

const message = useMessage();

const loading = ref(true);
const errorMsg = ref("");
const skipped = ref<string[]>([]);

const schema = ref<Record<string, any>>({});
const meta = ref<ConfigPayload["meta"]>({ plugin: "", version: "", writable: false, field_count: 0 });
const form = ref<Record<string, any>>({});
const initial = ref<Record<string, any>>({});

// 分区表（硬编码）：未列入的顶层键会落进「其他」，所以新增配置键要同步这里。
const GROUP_META: { name: string; description: string; keys: string[] }[] = [
  {
    name: "基础与出签",
    description: "时区、种子盐、出签方式与卡面外观",
    keys: [
      "timezone", "salt", "output_mode", "card_theme", "card_font_path",
      "card_width", "card_height", "fortune_signer", "tarot_label_on_image",
    ],
  },
  { name: "吉凶与权重", description: "六档吉凶的抽中权重", keys: ["grade_weights"] },
  { name: "LLM 星语", description: "用大模型改写签文", keys: ["llm_enabled", "llm_prompt_persona"] },
  { name: "每日推送", description: "定时向活跃群推送今日星象卡", keys: ["daily_push_enabled", "daily_push_time"] },
  {
    name: "AI 封面图",
    description: "联动 astrbot-comfyui-anima 出卡面底图",
    keys: [
      "draw_enabled", "draw_workflow", "draw_prompt_lang", "draw_prompt_format",
      "draw_llm_prompt", "draw_negative_prompt", "draw_silent", "draw_raw_prompt",
      "draw_timeout", "draw_fail_hint",
    ],
  },
  {
    name: "道具经济",
    description: "星尘与四道具的价格、上限",
    keys: ["economy_enabled", "item_prices", "draw_reward_base", "item_hold_cap"],
  },
  { name: "群与权限", description: "停用的群号", keys: ["disabled_groups"] },
];

const groups = computed(() => {
  const all = Object.keys(schema.value);
  const used = new Set<string>();
  const out = GROUP_META.map((g) => {
    const keys = g.keys.filter((k) => {
      if (!all.includes(k)) return false;
      used.add(k);
      return true;
    });
    return { ...g, keys };
  }).filter((g) => g.keys.length);
  const leftover = all.filter((k) => !used.has(k));
  if (leftover.length) {
    out.push({ name: "其他", description: "未归入以上分区的配置键", keys: leftover });
  }
  return out;
});

function typeOf(key: string): string {
  return String(schema.value[key]?.type || "string").toLowerCase();
}
function titleOf(key: string): string {
  return String(schema.value[key]?.description || key);
}
function hintOf(key: string): string {
  return String(schema.value[key]?.hint || "");
}
function optionsOf(key: string) {
  const node = schema.value[key] || {};
  const options = Array.isArray(node.options) ? node.options : [];
  const labels = Array.isArray(node.labels) ? node.labels : [];
  return options.map((v: any, i: number) => ({
    label: labels[i] != null ? String(labels[i]) : String(v),
    value: v,
  }));
}
function minOf(key: string): number | undefined {
  const slider = schema.value[key]?.slider;
  return slider && typeof slider.min === "number" ? slider.min : undefined;
}
function maxOf(key: string): number | undefined {
  const slider = schema.value[key]?.slider;
  return slider && typeof slider.max === "number" ? slider.max : undefined;
}

function toEditable(value: any, type: string): any {
  if (type === "dict") {
    try {
      return JSON.stringify(value ?? {}, null, 2);
    } catch {
      return "{}";
    }
  }
  if (type === "list") {
    return Array.isArray(value) ? value.join(",") : String(value ?? "");
  }
  return value;
}

function sameValue(a: any, b: any): boolean {
  if (a === b) return true;
  try {
    return JSON.stringify(a) === JSON.stringify(b);
  } catch {
    return false;
  }
}

function dirtyKeys(group: { keys: string[] }): string[] {
  return group.keys.filter((k) => !sameValue(form.value[k], initial.value[k]));
}

function buildPayload(keys: string[]): { values: Record<string, any>; bad: string[] } {
  const values: Record<string, any> = {};
  const bad: string[] = [];
  for (const key of keys) {
    const type = typeOf(key);
    let value = form.value[key];
    if (type === "dict") {
      try {
        const parsed = JSON.parse(String(value || "{}"));
        if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) {
          bad.push(`${key}（必须是 JSON 对象）`);
          continue;
        }
        value = parsed;
      } catch {
        bad.push(`${key}（JSON 解析失败）`);
        continue;
      }
    } else if (type === "list") {
      value = String(value || "")
        .split(/[,，]/)
        .map((s) => s.trim())
        .filter(Boolean);
    }
    values[key] = value;
  }
  return { values, bad };
}

async function save(group: { name: string; keys: string[] }) {
  const keys = dirtyKeys(group);
  if (!keys.length) return;
  const { values, bad } = buildPayload(keys);
  if (bad.length) {
    message.error("有字段格式不对，未提交：" + bad.join("、"));
  }
  if (!Object.keys(values).length) return;
  try {
    const res = await apiPost<{ changed: string[]; skipped: string[] }>("config", { values });
    skipped.value = res?.skipped || [];
    // 保存成功后同步基线，避免重复提交
    for (const k of res?.changed || []) initial.value[k] = form.value[k];
    const n = (res?.changed || []).length;
    if (n) message.success(`已保存 ${n} 项：${(res?.changed || []).join("、")}`);
    if (skipped.value.length) message.warning("部分字段被后端跳过，见页面底部说明");
  } catch (e: any) {
    message.error("保存失败：" + (e?.message || e));
  }
}

async function load() {
  loading.value = true;
  errorMsg.value = "";
  try {
    const data = await apiGet<ConfigPayload>("config");
    schema.value = data.schema || {};
    const m = data.meta;
    meta.value = {
      plugin: m?.plugin || "",
      version: m?.version || "",
      writable: Boolean(m?.writable),
      field_count: Number(m?.field_count ?? Object.keys(schema.value).length),
    };
    const editable: Record<string, any> = {};
    const base: Record<string, any> = {};
    for (const [key, value] of Object.entries(data.values || {})) {
      const type = String(schema.value[key]?.type || "string").toLowerCase();
      editable[key] = toEditable(value, type);
      base[key] = editable[key];
    }
    form.value = editable;
    initial.value = { ...base };
  } catch (e: any) {
    errorMsg.value = "加载配置失败：" + (e?.message || e);
    message.error(errorMsg.value);
  } finally {
    loading.value = false;
  }
}

onMounted(load);
</script>

<style scoped>
.panel {
  background: var(--msw-panel);
  border: 1px solid var(--msw-line);
  border-radius: 14px;
  padding: 14px 16px;
  margin-bottom: 14px;
}
.head-panel {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 12px;
  flex-wrap: wrap;
}
.head {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-bottom: 10px;
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
.meta {
  display: flex;
  gap: 6px;
  align-items: center;
}
.fields {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(320px, 1fr));
  gap: 14px;
}
.field {
  border: 1px dashed var(--msw-line);
  border-radius: 10px;
  padding: 10px 12px;
}
.label {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  gap: 8px;
  margin-bottom: 6px;
  font-size: 12.5px;
}
.label code {
  color: var(--msw-sub);
  font-size: 11px;
}
.hint {
  color: var(--msw-sub);
  font-size: 11px;
  margin-top: 5px;
  line-height: 1.55;
}
.kv {
  list-style: none;
  padding: 0;
  margin: 0;
}
.kv li {
  font-size: 12.5px;
  padding: 4px 0;
  color: #c05656;
}
.empty {
  color: var(--msw-sub);
  font-size: 13px;
  padding: 16px 0;
  text-align: center;
}
.empty.err {
  color: #c05656;
}
</style>
