// 控制台后端调用封装。
//
// 端点写法（AstrBot 约定，别改）：不带前导斜杠、不带插件名，如 "overview"、"config"。
// Dashboard 会把它拼成 /api/v1/plugins/extensions/<plugin>/<endpoint>；
// normalizePluginEndpoint 会校验端点（不能含 ? 或 #），查询参数一律走 params。
import { whenBridgeReady } from "./bridge";

const PAGE_PLUGIN_NAME = "astrbot_plugin_moe_star_whisper";
const DEFAULT_TIMEOUT_MS = 20000;

/** 不同 AstrBot 版本对端点前缀处理略有差异，逐个候选尝试（首个成功即返回）。 */
function endpointCandidates(routePath: string): string[] {
  const clean = routePath.replace(/^\/+/, "");
  const list = [clean, "/" + clean, `${PAGE_PLUGIN_NAME}/${clean}`, `/${PAGE_PLUGIN_NAME}/${clean}`];
  return [...new Set(list.map((s) => s.replace(/\/+/g, "/")).filter(Boolean))];
}

function isRouteMissing(payload: any): boolean {
  if (!payload || typeof payload !== "object") return false;
  const text =
    String(payload.error || "") + " " + String(payload.message || "") + " " + String(payload.detail || "");
  return /未找到.*路由|route.*not.*found|not.*found.*route|404/i.test(text);
}

function isRouteMissingError(e: any): boolean {
  if (isRouteMissing(e)) return true;
  const text = String(e?.message || e?.toString?.() || e || "");
  return /未找到.*路由|route.*not.*found|not.*found.*route|404|not found/i.test(text);
}

function withTimeout<T>(promise: Promise<T>, ms: number, label: string): Promise<T> {
  return new Promise<T>((resolve, reject) => {
    const timer = setTimeout(() => reject(new Error(`请求超时（${label}，${ms}ms）`)), ms);
    promise.then(
      (v) => {
        clearTimeout(timer);
        resolve(v);
      },
      (e) => {
        clearTimeout(timer);
        reject(e);
      }
    );
  });
}

/** 解信封：Dashboard 已剥一层 data，这里再兼容 status/data 与 code/data 两种形状。 */
function unwrap(payload: any): any {
  if (payload && typeof payload === "object") {
    if (payload.status === "error") throw new Error(payload.message || "请求失败");
    if (payload.status === "ok" && "data" in payload) return payload.data;
    if (Object.prototype.hasOwnProperty.call(payload, "code")) {
      if (payload.code !== 0) throw new Error(payload.message || "请求失败");
      return payload.data;
    }
  }
  return payload;
}

async function request(
  path: string,
  method: "GET" | "POST",
  params?: Record<string, any>,
  timeoutMs?: number
): Promise<any> {
  const br = await whenBridgeReady();
  const candidates = endpointCandidates(path);
  const errors: string[] = [];
  const ms = timeoutMs ?? DEFAULT_TIMEOUT_MS;

  for (const candidate of candidates) {
    try {
      const payload =
        method === "GET"
          ? await withTimeout(br.apiGet(candidate, params), ms, "GET " + candidate)
          : await withTimeout(br.apiPost(candidate, params || {}), ms, "POST " + candidate);
      if (isRouteMissing(payload)) {
        errors.push(String(payload?.message || payload?.error || "未找到该路由"));
        continue;
      }
      return unwrap(payload);
    } catch (e: any) {
      // 只有「路由不存在」才值得换一种写法重试；业务错误必须立刻抛出
      // （POST 尤其如此——重试可能造成重复写入）。
      if (!isRouteMissingError(e)) throw e;
      errors.push(e?.message || String(e));
    }
  }
  throw new Error(errors[0] || "未找到可用的控制台 API 路由");
}

/** GET，endpoint 如 "overview"、"records"。查询参数走 params。 */
export function apiGet<T = any>(endpoint: string, params?: Record<string, any>, timeoutMs?: number): Promise<T> {
  return request(endpoint, "GET", params, timeoutMs) as Promise<T>;
}

/** POST，endpoint 如 "config"、"debug/redraw"。 */
export function apiPost<T = any>(endpoint: string, body?: Record<string, any>, timeoutMs?: number): Promise<T> {
  return request(endpoint, "POST", body, timeoutMs) as Promise<T>;
}

// ------------------------------------------------------------------ //
// 类型（与 webui_api.py 返回形状对应，只声明用到的字段）
// ------------------------------------------------------------------ //

export interface Totals {
  draws: number;
  users: number;
  groups: number;
  days: number;
  cards: number;
}

export interface DayStat {
  date: string;
  draws: number;
  users: number;
  avg_score: number;
  lucky?: number;
  unlucky?: number;
  great?: number;
  bad?: number;
}

export interface RecordRow {
  uid: string;
  nickname: string;
  avatar?: string;
  date: string;
  grade: string;
  score: number;
  group_id: string;
  group_name: string;
  created_at: string;
  streak: number;
  lucky_color: string;
  lucky_item: string;
  llm_used: boolean;
  sign_text: string;
  has_card: boolean;
}

export interface Overview {
  version: string;
  today: string;
  range_from: string;
  totals: Totals;
  day: DayStat;
  trend: DayStat[];
  grades: Record<string, number>;
  recent: RecordRow[];
  recent_users: UserRow[];
  counts: Record<string, number>;
  switches: Record<string, any>;
}

/** 抽过签的用户（用户列表页 / 总览快捷入口）。 */
export interface UserRow {
  uid: string;
  nickname: string;
  avatar: string;
  draws: number;
  first_date: string;
  last_date: string;
  avg_score: number;
  best_score: number;
  groups: number;
  last_group_id: string;
  last_group_name: string;
}

export interface UsersPayload {
  users: { total: number; page: number; size: number; rows: UserRow[] };
  keyword: string;
  order: string;
}

/** 群活跃行（口径：每条记录=用户当天第一次抽签所在的群，不会重复计算）。 */
export interface GroupRow {
  group_id: string;
  group_name: string;
  draws: number;
  users: number;
  avg_score: number;
  great: number;
  bad: number;
  cards: number;
  last_date: string;
}

export interface RecordsPayload {
  records: { total: number; page: number; size: number; rows: RecordRow[] };
  groups: { group_id: string; group_name: string; draws: number }[];
  grades: string[];
  filters: Record<string, any>;
  today: string;
}

export interface StatsPayload {
  days: number;
  range_from: string;
  range_to: string;
  trend: DayStat[];
  grades: Record<string, number>;
  grades_all: Record<string, number>;
  grade_daily: { date: string; grade: string; n: number }[];
  hours: number[];
  groups: GroupRow[];
  groups_all: GroupRow[];
  group_share: { name: string; value: number }[];
  private: { draws: number; users: number };
  jobs: {
    by_status: Record<string, { n: number; avg_ms: number }>;
    total: number;
    ok: number;
    success_rate: number;
    by_day: { date: string; total: number; ok: number }[];
  };
  ledger: {
    by_reason: { reason: string; total: number; n: number }[];
    by_day: { day: string; income: number; spend: number }[];
    income: number;
    spend: number;
  };
  dims: Record<string, number>;
  dims_sampled: number;
  lucky_items: { name: string; n: number }[];
  lucky_colors: { name: string; hex: string; n: number }[];
  constellations: { name: string; n: number }[];
  streaks: Record<string, number>;
}

export interface UserPayload {
  uid: string;
  today: string;
  nickname: string;
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
    nickname: string;
    seed_nonce: number;
  };
  balance: number;
  items: Record<string, number>;
  draw_jobs: {
    id: number;
    status: string;
    workflow: string;
    error: string;
    duration_ms: number;
    image_path: string;
  }[];
  history: {
    date: string;
    grade: string;
    score: number;
    streak: number;
    lucky_color: string;
    has_card: boolean;
  }[];
  ledger: { delta: number; reason: string; ref_date: string; created_at: string }[];
  calendar: { date: string; grade: string; score: number }[];
  recent_uids: string[];
  config: Record<string, any>;
}

export interface ConfigPayload {
  schema: Record<string, any>;
  values: Record<string, any>;
  meta: { plugin: string; version: string; writable: boolean; field_count: number };
}
