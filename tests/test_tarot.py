# -*- coding: utf-8 -*-
"""塔罗牌库与生图提示词守卫（v1.11.9）。纯函数测试，无 astrbot 依赖。

背景：旧版只有 22 张大阿卡纳、每张只有一条正位口径解读，标着「逆位」也照读正位；
生图提示词里只塞牌名与关键词，AI 不知道倒吊人要倒挂，画出来全是站着的少女。
这个测试把「78 张 / 正逆位两套 / 牌面意象进提示词」三件事锁死。
退出码即结论。
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import fortune  # noqa: E402
import lexicon  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
FAILED = []


def check(cond, msg):
    if not cond:
        FAILED.append(msg)
        print(f"FAIL: {msg}")


def main() -> int:
    deck = fortune.TAROT_DECK

    # 1) 牌库规模与唯一性：22 大阿卡纳 + 4 花色 × 14 阶位 = 78 张
    check(len(fortune.TAROT_MAJOR) == 22, "大阿卡纳必须是 22 张")
    check(len(fortune.TAROT_MINOR) == 56, "小阿卡纳必须是 56 张（4 花色 × 14 阶位）")
    check(len(deck) == 78, f"完整牌组必须是 78 张，实际 {len(deck)}")
    check(len({c["cn"] for c in deck}) == 78, "中文牌名不得重复")
    check(len({c["en"] for c in deck}) == 78, "英文牌名不得重复")
    for suit in ("权杖", "圣杯", "宝剑", "星币"):
        hit = [c for c in fortune.TAROT_MINOR if c["suit_cn"] == suit]
        check(len(hit) == 14, f"{suit} 应有 14 张，实际 {len(hit)}")
        check(all(c["cn"].startswith(suit) for c in hit), f"{suit} 牌名应以花色开头")
        check(all(c["element"] for c in hit), f"{suit} 每张都要带四元素")

    # 2) 每张牌都必须有正/逆位两套，且两套真的不同
    fields = ("cn", "en", "suit", "suit_cn", "kw_up", "kw_rev", "up", "rev",
              "vzh_up", "vzh_rev", "ven_up", "ven_rev")
    for card in deck:
        name = card.get("cn", "?")
        for key in fields:
            check(bool(card.get(key)), f"{name} 缺字段 {key}")
        for a, b in (("kw_up", "kw_rev"), ("up", "rev"),
                     ("vzh_up", "vzh_rev"), ("ven_up", "ven_rev")):
            check(card[a] != card[b], f"{name} 的 {a}/{b} 必须不同（逆位不能只是换个标签）")
        check("{" not in card["vzh_up"] and "{" not in card["ven_up"],
              f"{name} 的画面模板占位符未填充")
        check(len(card["up"]) <= 40 and len(card["rev"]) <= 40,
              f"{name} 解读过长会撑破卡面两行")

    # 3) 倒吊人：正位必须倒挂，逆位必须松绑落地（用户反馈的「都是正的」）
    hanged = next(c for c in fortune.TAROT_MAJOR if c["cn"] == "倒吊人")
    check("倒挂" in hanged["vzh_up"] and "头下脚上" in hanged["vzh_up"],
          "倒吊人正位意象必须写明头下脚上倒挂")
    check("UPSIDE DOWN" in hanged["ven_up"], "倒吊人英文意象必须强调 UPSIDE DOWN")
    check("落地" in hanged["vzh_rev"] and "untied" in hanged["ven_rev"],
          "倒吊人逆位意象应是绳索松开、重新落地")
    check(hanged["up"] != hanged["rev"], "倒吊人正逆位解读必须不同")
    check("换个角度" in hanged["kw_up"] and "白等" in hanged["kw_rev"],
          "倒吊人正逆位关键词必须各有侧重")

    # 4) 抽牌确定性、牌池范围、正逆位分布
    seed = fortune.derive_seed("2026-11-06", "tarot-user", "salt-x", 0)
    a, b = fortune.tarot_of(seed), fortune.tarot_of(seed)
    check(a == b, "同种子抽牌必须完全一致")
    check(a["deck_size"] == 78, "默认走完整 78 张牌组")
    check(a["label"] in ("正位", "逆位") and isinstance(a["reversed"], bool),
          "正逆位字段形状")
    check(a["visual_zh"] and a["visual_en"], "抽出的牌必须带中英文画面意象")
    check(a["keywords"] and a["interp"], "抽出的牌必须带按位关键词与解读")
    majors = [fortune.tarot_of(fortune.derive_seed("2026-11-06", f"m{i}", "s"),
                               scope="major")
              for i in range(300)]
    check(all(t["suit"] == "major" and t["deck_size"] == 22 for t in majors),
          "scope=major 只能抽到 22 张大阿卡纳")
    full = [fortune.tarot_of(fortune.derive_seed("2026-11-06", f"f{i}", "s"))
            for i in range(600)]
    check(any(t["suit"] != "major" for t in full), "完整牌组应能抽到小阿卡纳")
    rev_ratio = sum(1 for t in full if t["reversed"]) / len(full)
    check(0.35 < rev_ratio < 0.65, f"正逆位应大致各半，实际逆位占比 {rev_ratio:.2f}")
    check(len({t["name_cn"] for t in full}) > 60, "600 次抽样应覆盖大部分牌，别总抽同几张")

    # 5) 事实清单：签文用（默认）保持精简，生图用（visual_lang）注入画面
    lex = lexicon.load_lexicon()
    result = fortune.roll_fortune(seed, lex)
    result["tarot"] = fortune.tarot_of(seed)
    plain = fortune.llm_facts(result)
    check("今日塔罗：" in plain and "牌面意象" not in plain,
          "签文用事实清单不应塞入牌面画面（避免 LLM 复述画面）")
    zh = fortune.llm_facts(result, visual_lang="zh")
    en = fortune.llm_facts(result, visual_lang="en")
    check("牌面意象：" in zh and result["tarot"]["visual_zh"][:8] in zh,
          "中文生图事实清单必须带牌面意象")
    check("画面规则：" in zh and "关键姿态" in zh,
          "中文生图事实清单必须带关键姿态/逆位/边框规则")
    check("Card motif (must draw exactly)" in en
          and result["tarot"]["visual_en"][:12] in en,
          "英文生图事实清单必须带牌面意象")
    check("Visual rules:" in en and "generic standing pose" in en,
          "英文生图事实清单必须带画面规则")
    check("牌组：" in zh and ("Element:" in en or "Major Arcana" in en),
          "中英文事实清单都应带牌组/元素信息")
    check("元素）" not in en and "牌组：" not in en,
          "英文牌组信息不得夹带中文元素名")
    # 旧 payload（六个字段）也要能吃上画面意象
    old = {"grade": "吉", "score": 70,
           "tarot": {"name_cn": "倒吊人", "name_en": "The Hanged Man",
                     "label": "逆位", "keywords": "换个角度", "interp": "卡住就换视角",
                     "reversed": True}}
    old_facts = fortune.llm_facts(old, visual_lang="en")
    check("the rope untied" in old_facts, "旧 payload 反查后应补上逆位画面意象")
    check("今日塔罗：审判（逆位）" in fortune.llm_facts(
        {"grade": "吉", "tarot": {"name_cn": "审判", "label": "逆位",
                                  "keywords": "觉醒 · 召唤 · 重生"}}),
        "手写/异常塔罗字典仍要能出事实清单（向后兼容）")

    # 6) 内置模板：四种组合都要求「照着牌面意象画」，且不再写死大阿卡纳
    for lang, fmt in (("en", "tags"), ("en", "natural"),
                      ("zh", "tags"), ("zh", "natural")):
        tpl = fortune.builtin_draw_prompt(lang, fmt)
        check("{facts}" in tpl, f"{lang}+{fmt} 模板必须保留 {{facts}} 占位")
        check("Card motif" in tpl or "牌面意象" in tpl,
              f"{lang}+{fmt} 模板必须要求照牌面意象绘制")
        check("major arcana" not in tpl and "大阿卡纳" not in tpl,
              f"{lang}+{fmt} 模板不得写死大阿卡纳（牌池已扩到 78 张）")
        check("no text" in tpl or "不要出现任何文字" in tpl,
              f"{lang}+{fmt} 模板必须排除牌面文字")
    check("Danbooru" in fortune.builtin_draw_prompt("en", "tags"), "英文标签式仍要求 Danbooru 标签")
    check("女性角色" in fortune.draw_system_hint("zh")
          and "女性" not in fortune.draw_system_hint("en"), "系统提示按语言切换")
    check("倒挂" in fortune.draw_system_hint("zh")
          and "upside down" in fortune.draw_system_hint("en"),
          "系统提示必须点名倒挂这类关键姿态")
    check("never cropped" in fortune.draw_system_hint("en"), "系统提示仍锁死边框不裁切")
    for tag in ("text", "roman numerals", "2girls", "white border", "floating card"):
        check(tag in fortune.DEFAULT_DRAW_NEGATIVE, f"负向提示词应排除 {tag}")

    # 7) 本地兜底提示词：LLM 超时也不能退化成「只有牌名」
    for lang, fmt in (("en", "tags"), ("en", "natural"),
                      ("zh", "tags"), ("zh", "natural")):
        lp = fortune.local_draw_prompt(result, lang, fmt)
        card_name = result["tarot"]["name_cn" if lang == "zh" else "name_en"]
        check(card_name in lp, f"{lang}+{fmt} 兜底应带牌名")
        check(result["tarot"]["visual_zh" if lang == "zh" else "visual_en"][:6] in lp,
              f"{lang}+{fmt} 兜底必须带牌面意象")
        if lang == "en":
            check(fortune.lang_matches(lp, "en"), f"{fmt} 英文兜底不得混入中文")
            check("reversed" in lp or "upright" in lp, "英文兜底应标出正逆位")
            check("The Star" in fortune.local_draw_prompt({"grade": "吉"}, "en", fmt),
                  "无塔罗数据时保留历史兜底牌名")
        else:
            check(result["tarot"]["label"] in lp, "中文兜底应标出正逆位")
            check("男性角色" in lp and "留出空隙" not in lp, "中文兜底保留单人/边框约束")

    # 8) 词库池：别让签文/宜忌又缩回「几句话轮着播」
    check(all(len(lex["comments"][g]) >= 10 for g in lex["grades"]), "每档点评至少 10 条")
    check(all(len(lex["wishes"][g]) >= 6 for g in lex["grades"]), "每档祝语至少 6 条")
    check(len(lex["item_lines"]) >= 12, "幸运物联动句式至少 12 条")
    check(len(lex["lucky_items"]) >= 60, "幸运物至少 60 条")
    check(len(lex["yi"]) >= 60 and len(lex["ji"]) >= 60, "宜/忌各至少 60 条")
    check(all(len(lex["pk"][k]) >= 6 for k in ("win", "lose", "tie")), "PK 各池至少 6 条")
    check(len(lex["friday"]) >= 8, "周五彩蛋至少 8 条")
    check(len(lex["festivals"]) >= 16, "公历节日至少 16 个")
    check(len(lex["jieqi"]) == 24, "节气必须刚好 24 个")

    # 9) 配置与前端分区：新增键不能落到「其他」，也不能缺 type
    schema = json.loads((ROOT / "_conf_schema.json").read_text(encoding="utf-8"))
    check(schema.get("tarot_deck_scope", {}).get("type") == "string"
          and schema["tarot_deck_scope"]["default"] == "full",
          "牌库范围配置必须是 string 且默认完整牌组")
    check(len(schema["tarot_deck_scope"]["labels"])
          == len(schema["tarot_deck_scope"]["options"]), "牌库范围 labels 与 options 等长")
    check(schema.get("tarot_visual_in_prompt", {}).get("type") == "bool"
          and schema["tarot_visual_in_prompt"]["default"] is True,
          "牌面意象注入开关默认开")
    vue = (ROOT / "webui-src/src/views/ConfigView.vue").read_text(encoding="utf-8")
    for key in ("tarot_deck_scope", "tarot_visual_in_prompt", "tarot_label_on_image"):
        check(key in vue, f"WebUI 分区表必须收录 {key}")
    main_src = (ROOT / "main.py").read_text(encoding="utf-8")
    check("visual_lang=visual_lang" in main_src, "生图组装必须传 visual_lang")
    check("tarot_deck_scope" in main_src, "抽签必须读牌库范围配置")

    if FAILED:
        print(f"\n{len(FAILED)} 项失败")
        return 1
    print("\ntarot.py 全部通过")
    return 0


if __name__ == "__main__":
    sys.exit(main())
