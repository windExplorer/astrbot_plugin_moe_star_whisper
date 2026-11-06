// 后台枚举 → 界面中文（draw_jobs.status / ledger.reason），三个视图共用一份。
//
// ⚠️ skipped_no_anima 是**历史落库值**（旧 draw_jobs 记录里已经是它），
// 数据库里不改，只在界面上显示成「萌绘未安装」——改库值会导致新旧数据双份映射。

export const STATUS_LABELS: Record<string, string> = {
  ok: "成功",
  error: "失败",
  timeout: "超时",
  skipped_no_anima: "萌绘未安装",
  disabled: "未开启",
};

export const REASON_LABELS: Record<string, string> = {
  draw: "每日抽签发放",
  reroll: "换签卡消耗",
  amulet: "护身符消耗",
  candle: "幸运香烛消耗",
  streak_guard: "连签保护卡消耗",
  grant: "管理员发放",
  birthday: "生日彩蛋",
  "task:calendar": "每日任务 · 运势日历",
  "task:rank": "每日任务 · 星语榜",
  "task:star": "每日任务 · 今日星象",
  "fun:delight": "玩法 · 小确幸签",
  "fun:bless": "玩法 · 星语祝福卡",
  "fun:gift": "玩法 · 星尘礼盒",
  "gift:back": "礼盒星尘返利",
};

/** 绘图任务状态：未知值原样显示（便于排查新状态）。 */
export function statusLabel(status: string): string {
  return STATUS_LABELS[String(status)] || String(status);
}

/** 星尘流水原因：支持 buy:xxx / use:xxx 前缀。 */
export function reasonLabel(reason: string): string {
  const key = String(reason || "");
  if (REASON_LABELS[key]) return REASON_LABELS[key];
  if (key.startsWith("buy:")) return "购买 " + key.slice(4);
  if (key.startsWith("use:")) return "使用 " + key.slice(4);
  return key;
}
