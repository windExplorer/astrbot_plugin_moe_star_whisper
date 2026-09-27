# -*- coding: utf-8 -*-
"""fortune.py 纯函数测试（无 astrbot 依赖，直接运行；退出码 0=通过）。"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import fortune  # noqa: E402
import lexicon  # noqa: E402

FAILED = []


def check(cond, msg):
    if not cond:
        FAILED.append(msg)
        print(f"FAIL: {msg}")


def main() -> int:
    lex = lexicon.load_lexicon()
    weights = dict(fortune.DEFAULT_GRADE_WEIGHTS)

    # 1) 确定性：同种子同结果，且可稳定 JSON 序列化（落库依据）
    s1 = fortune.derive_seed("2026-09-27", "10001", "salt-x", 0)
    r1 = fortune.roll_fortune(s1, lex, weights)
    r2 = fortune.roll_fortune(s1, lex, weights)
    check(r1 == r2, "同种子两次 roll 结果必须完全一致")
    check(json.dumps(r1, ensure_ascii=False, sort_keys=True) ==
          json.dumps(r2, ensure_ascii=False, sort_keys=True), "结果可稳定 JSON 序列化")

    # 2) 用户/日期/nonce 变化 → 结果变化
    s2 = fortune.derive_seed("2026-09-27", "10002", "salt-x", 0)
    s3 = fortune.derive_seed("2026-09-28", "10001", "salt-x", 0)
    s4 = fortune.derive_seed("2026-09-27", "10001", "salt-x", 1)
    check(fortune.roll_fortune(s2, lex, weights) != r1 or
          fortune.roll_fortune(s3, lex, weights) != r1 or
          fortune.roll_fortune(s4, lex, weights) != r1,
          "不同用户/日期/nonce 至少一项应产生不同结果")

    # 3) 档位合法、六维落在档位区间、各字段来自词库
    for i in range(500):
        seed = fortune.derive_seed("2026-09-27", f"u{i}", "salt-x", 0)
        r = fortune.roll_fortune(seed, lex, weights)
        check(r["grade"] in fortune.GRADES, f"档位非法: {r['grade']}")
        lo, hi = fortune.GRADE_DIM_RANGE[r["grade"]]
        for k, v in r["dims"].items():
            check(lo <= v <= hi, f"{r['grade']} 维度 {k}={v} 超出区间 [{lo},{hi}]")
        check(0 <= r["score"] <= 100, f"score 越界: {r['score']}")
        check(len(r["yi"]) == 2 and r["yi"][0] != r["yi"][1], "宜必须两条且不重复")
        check(len(r["ji"]) == 2 and r["ji"][0] != r["ji"][1], "忌必须两条且不重复")
        check(r["yi"][0] in lex["yi"] and r["yi"][1] in lex["yi"], "宜必须来自词库")
        check(r["ji"][0] in lex["ji"] and r["ji"][1] in lex["ji"], "忌必须来自词库")
        check("{item}" not in r["sign_text"], f"签文槽位未填充: {r['sign_text']}")
        check(r["lucky_item"] in lex["lucky_items"], "幸运物必须来自词库")
        check(r["lucky_color"]["name"] in [c["name"] for c in lex["lucky_colors"]],
              "幸运色必须来自词库")
        check(1 <= r["lucky_number"] <= 99, "幸运数字须在 1~99")
        check(r["lucky_dir"] in lex["directions"], "方位必须来自词库")
        check(r["phase"]["name"] in [p["name"] for p in lex["phases"]], "月相必须来自词库")
        check(r["grade_color"] == lex["grade_colors"].get(r["grade"]), "档位色必须来自词库")

    # 4) 权重分布粗检（5000 个合成用户，单日；容差 3% 足以发现权重接反）
    counts = {g: 0 for g in fortune.GRADES}
    n = 5000
    for i in range(n):
        seed = fortune.derive_seed("2026-09-27", f"distuser{i}", "salt-x", 0)
        counts[fortune.roll_fortune(seed, lex, weights)["grade"]] += 1
    total = sum(weights.values())
    for g, w in weights.items():
        expect = w / total
        actual = counts[g] / n
        check(abs(actual - expect) < 0.03,
              f"{g} 频率 {actual:.3f} 偏离权重 {expect:.3f} 过多")

    # 5) 跨日变化：同一用户连续 10 天不至于全同
    seen = set()
    for d in range(20, 30):
        seed = fortune.derive_seed(f"2026-09-{d:02d}", "streakuser", "salt-x", 0)
        seen.add(json.dumps(fortune.roll_fortune(seed, lex, weights), sort_keys=True))
    check(len(seen) >= 8, f"同用户 10 天结果应大部分不同（实际 {len(seen)}）")

    # 6) 道具钩子（M7 用，先行实现）
    aw = fortune.amulet_weights(weights)
    check("凶" not in aw and "大凶" not in aw, "护身符权重必须移除凶/大凶")
    check(aw["小吉"] == weights["小吉"] + weights["凶"] + weights["大凶"],
          "护身符权重并入小吉")
    bad = fortune.roll_fortune(s1, lex, weights)
    fortune.apply_candle(bad)
    check(bad["score"] == min(100, r1["score"] + 8), "香烛必须 +8 封顶 100")
    check(bad["boosts"]["candle"] is True, "香烛必须标记 boosts.candle")
    fortune.apply_candle(bad)
    check(bad["score"] == min(100, r1["score"] + 8), "香烛必须幂等")

    # 7) 日期工具
    check(fortune.prev_date("2026-03-01") == "2026-02-28", "跨月/闰年 prev_date")
    check(len(fortune.local_today("UTC")) == 10, "local_today 格式 YYYY-MM-DD")
    check(fortune.local_today("Not/AZone") == fortune.local_today("Asia/Shanghai"),
          "非法时区应回退 Asia/Shanghai")

    # 8) 星座边界（M4）
    cases = (
        ("03-21", "白羊座"), ("04-19", "白羊座"), ("03-20", "双鱼座"), ("02-19", "双鱼座"),
        ("12-22", "摩羯座"), ("01-19", "摩羯座"), ("01-20", "水瓶座"), ("02-18", "水瓶座"),
        ("06-21", "双子座"), ("06-22", "巨蟹座"), ("05-20", "金牛座"), ("07-22", "巨蟹座"),
        ("08-23", "处女座"), ("09-22", "处女座"), ("09-23", "天秤座"), ("10-23", "天秤座"),
        ("10-24", "天蝎座"), ("11-22", "天蝎座"), ("11-23", "射手座"), ("12-21", "射手座"),
    )
    for mmdd, expect in cases:
        check(fortune.constellation_of(mmdd) == expect,
              f"星座 {mmdd} 应为 {expect}，实际 {fortune.constellation_of(mmdd)}")
    check(fortune.constellation_of("abc") == "", "非法输入返回空串")
    check(fortune.constellation_of("13-40") == "", "越界日期返回空串")

    # 9) LLM 星语辅助（M5）
    facts = fortune.llm_facts(r1)
    check("吉凶" in facts and "幸运物" in facts and str(r1["grade"]) in facts,
          "llm_facts 应含吉凶与幸运物等事实")
    r1t = dict(r1)
    r1t["tarot"] = {"name_cn": "审判", "label": "逆位", "keywords": "觉醒 · 召唤 · 重生"}
    check("今日塔罗：审判（逆位）" in fortune.llm_facts(r1t),
          "llm_facts 应含塔罗事实（v1.4.1 塔罗提示词）")
    check(fortune.DEFAULT_LLM_PERSONA and "星语者" in fortune.DEFAULT_LLM_PERSONA,
          "内置人设非空")
    now = fortune.now_in("UTC")
    check(now.tzinfo is not None, "now_in 应返回 aware datetime")

    # 10) M6：生图提示词与 anima 响应解析
    tpl = fortune.builtin_draw_prompt("en", "tags")
    check("Danbooru" in tpl and "{facts}" in tpl, "en+tags 模板应含 Danbooru 约束与 facts 占位")
    tpl_zh = fortune.builtin_draw_prompt("zh", "natural")
    check("自然流畅" in tpl_zh and "{facts}" in tpl_zh, "zh+natural 模板应正确")
    lp = fortune.local_draw_prompt(r1, "en", "tags")
    check("tarot card design" in lp and "1girl" in lp and "The Star" in lp,
          "本地兜底提示词应为塔罗牌主题（v1.4.1）")
    check(fortune.local_draw_prompt(r1, "zh", "natural"), "中文兜底提示词非空")
    check(fortune.parse_draw_response('{"image_paths": ["a.png", " b.png "]}') == ["a.png", "b.png"],
          "解析 image_paths 列表")
    check(fortune.parse_draw_response('{"image_path": "one.png"}') == ["one.png"],
          "兼容单数 image_path")
    check(fortune.parse_draw_response('前缀 {"image_paths": ["x.png"]} 后缀') == ["x.png"],
          "容错截取花括号段")
    check(fortune.parse_draw_response("绘图完成！") == [], "无路径文本返回空")
    check(fortune.parse_draw_response(None) == [], "None 返回空")

    # 11) M7：星尘奖励公式
    check(fortune.stardust_reward("大吉", 0) == 30, "大吉首签 10+20")
    check(fortune.stardust_reward("凶", 3) == 26, "凶+连签3 10+14+2")
    check(fortune.stardust_reward("大凶", 7) == 32, "大凶+连签7 10+18+4（越倒霉补偿越多）")
    check(fortune.stardust_reward("中吉", 30) == 28, "中吉+连签30 10+12+6")
    check(fortune.stardust_reward("小吉", 1) == 20, "小吉首签 10+10")
    check(fortune.stardust_reward("吉", 1, base=0) == 15, "自定义基础值（streak=1 无连签加成）")

    if FAILED:
        print(f"\n{len(FAILED)} 项失败")
        return 1
    print("\nfortune.py 全部通过")
    return 0


if __name__ == "__main__":
    sys.exit(main())
