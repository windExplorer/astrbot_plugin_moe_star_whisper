// 配色与图表调色板：档位色与插件词库（data/lexicon/fortune_lexicon.json）保持一致，
// 让控制台图表与聊天里的签卡观感统一。

export const GRADE_ORDER = ["大吉", "吉", "中吉", "小吉", "凶", "大凶"] as const;

export const GRADE_COLORS: Record<string, string> = {
  大吉: "#E86A8A",
  吉: "#F0A0B8",
  中吉: "#E8C46A",
  小吉: "#A8C8E8",
  凶: "#9BA8B8",
  大凶: "#7A86A8",
};

export const PALETTE = [
  "#E86A8A",
  "#8A6AD6",
  "#E8C46A",
  "#5BA8C8",
  "#7BC48A",
  "#E89A6A",
  "#B48AD6",
  "#9BA8B8",
];

export const DIM_KEYS = ["恋爱运", "学业运", "财运", "健康运", "社交运", "摸鱼运"];

export interface ChartPalette {
  text: string;
  textDim: string;
  axis: string;
  split: string;
  tooltipBg: string;
  tooltipText: string;
  area: string;
}

/** 图表内的文字/网格颜色（ECharts 不跟随 CSS 变量，按主题显式给）。 */
export function chartPalette(isDark: boolean): ChartPalette {
  return isDark
    ? {
        text: "#e8e4f2",
        textDim: "#a49fb8",
        axis: "#5c5773",
        split: "rgba(255,255,255,.08)",
        tooltipBg: "rgba(28,26,40,.95)",
        tooltipText: "#f2eef8",
        area: "rgba(232,106,138,.25)",
      }
    : {
        text: "#4a4a60",
        textDim: "#9696a8",
        axis: "#c9c6d6",
        split: "rgba(120,100,140,.12)",
        tooltipBg: "rgba(255,255,255,.96)",
        tooltipText: "#4a4a60",
        area: "rgba(232,106,138,.18)",
      };
}

export function gradeColor(grade: string): string {
  return GRADE_COLORS[grade] || PALETTE[0];
}
