# -*- coding: utf-8 -*-
"""萌萌星语 · 运势核心（纯函数，不依赖 astrbot，可独立测试）。

确定性原则（PRD §3.1）：
    seed = SHA-256(f"{date}|{user_id}|{salt}|{nonce}")
所有维度由种子派生（hashlib，禁止全局 random），同一天同一人结果恒定：
跨时刻、跨群一致；换签卡 = nonce+1 重掷；底图种子同理，一人一天一张。
"""
from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

GRADES = ("大吉", "吉", "中吉", "小吉", "凶", "大凶")

# 权重表（D2）：大吉略高于传统十取一，群里更欢乐；运行时以配置覆盖
DEFAULT_GRADE_WEIGHTS = {"大吉": 20, "吉": 25, "中吉": 25, "小吉": 15, "凶": 10, "大凶": 5}

# 各吉凶档的六维星数区间 [lo, hi]（含端点）
GRADE_DIM_RANGE = {
    "大吉": (4, 5),
    "吉": (3, 5),
    "中吉": (3, 4),
    "小吉": (2, 4),
    "凶": (1, 3),
    "大凶": (1, 2),
}

DIM_KEYS = ("恋爱运", "学业运", "财运", "健康运", "社交运", "摸鱼运")


def _sub_int(seed: bytes, tag: str, modulus: int) -> int:
    """由种子+标签派生 [0, modulus) 内的确定整数。modulus 必须 >= 1。"""
    digest = hashlib.sha256(seed + b"|" + tag.encode("utf-8")).digest()
    return int.from_bytes(digest[:8], "big") % modulus


def _pick(seed: bytes, tag: str, pool):
    return pool[_sub_int(seed, tag, len(pool))]


def _weighted_pick(seed: bytes, tag: str, weights: dict) -> str:
    total = int(sum(weights.values()))
    if total <= 0:
        raise ValueError(f"吉凶权重之和必须为正：{weights}")
    point = _sub_int(seed, tag, total)
    acc = 0
    last = None
    for key, weight in weights.items():
        acc += int(weight)
        last = key
        if point < acc:
            return key
    return last


def _pick_two(seed: bytes, tag: str, pool: list) -> list:
    """从池中确定地取两个不重复项（池长度 >= 2）。"""
    n = len(pool)
    i = _sub_int(seed, tag, n)
    j = _sub_int(seed, tag + "#2", n - 1)
    if j >= i:
        j += 1
    return [pool[i], pool[j]]


def derive_seed(date_str: str, user_id: str, salt: str, nonce: int = 0) -> bytes:
    raw = f"{date_str}|{user_id}|{salt}|{int(nonce)}".encode("utf-8")
    return hashlib.sha256(raw).digest()


def now_in(tz_name: str = "Asia/Shanghai") -> datetime:
    """插件时区的当前时刻（aware）。回退链：配置时区 → Asia/Shanghai → 固定 UTC+8。"""
    try:
        tz = ZoneInfo(tz_name)
    except Exception:
        try:
            tz = ZoneInfo("Asia/Shanghai")
        except Exception:
            tz = timezone(timedelta(hours=8))
    return datetime.now(tz)


def local_today(tz_name: str = "Asia/Shanghai") -> str:
    """插件时区的今天（YYYY-MM-DD）。"""
    return now_in(tz_name).strftime("%Y-%m-%d")


def prev_date(date_str: str) -> str:
    d = datetime.strptime(date_str, "%Y-%m-%d")
    return (d - timedelta(days=1)).strftime("%Y-%m-%d")


def roll_fortune(seed: bytes, lex: dict, grade_weights: dict | None = None) -> dict:
    """由种子确定地掷出一支完整运势（返回值可直接 JSON 序列化落库）。"""
    weights = dict(grade_weights) if grade_weights else dict(DEFAULT_GRADE_WEIGHTS)
    grade = _weighted_pick(seed, "grade", weights)
    lo, hi = GRADE_DIM_RANGE[grade]
    dims = {}
    for key in DIM_KEYS:
        dims[key] = lo + _sub_int(seed, f"dim:{key}", hi - lo + 1)
    score = round(sum(dims.values()) / (5 * len(DIM_KEYS)) * 100)
    score = max(5, min(100, score))

    item = _pick(seed, "item", lex["lucky_items"])
    color = lex["lucky_colors"][_sub_int(seed, "color", len(lex["lucky_colors"]))]
    yi = _pick_two(seed, "yi", lex["yi"])
    ji = _pick_two(seed, "ji", lex["ji"])
    phase = _pick(seed, "phase", lex["phases"])
    direction = _pick(seed, "dir", lex["directions"])
    number = 1 + _sub_int(seed, "number", 99)

    comment = _pick(seed, f"comment:{grade}", lex["comments"][grade])
    item_line = _pick(seed, "item_line", lex["item_lines"]).format(item=item)
    wish = _pick(seed, f"wish:{grade}", lex["wishes"][grade])
    sign_text = f"{comment}{item_line}{wish}"

    return {
        "grade": grade,
        "grade_color": lex["grade_colors"].get(grade, "#E8A2B8"),
        "score": score,
        "dims": dims,
        "lucky_item": item,
        "lucky_color": color,
        "lucky_number": number,
        "lucky_dir": direction,
        "yi": yi,
        "ji": ji,
        "phase": phase,
        "sign_text": sign_text,
        "boosts": {"amulet": False, "candle": False},
    }


def pick_text(seed: bytes, tag: str, pool: list) -> str:
    """从池中确定性取一条（公开接口，供 PK 文案等场景使用）。"""
    return _pick(seed, tag, pool)


# 星座区间（含跨年的摩羯）；MM-DD -> 名称
CONSTELLATION_RANGES = (
    ("摩羯座", (12, 22), (1, 19)),
    ("水瓶座", (1, 20), (2, 18)),
    ("双鱼座", (2, 19), (3, 20)),
    ("白羊座", (3, 21), (4, 19)),
    ("金牛座", (4, 20), (5, 20)),
    ("双子座", (5, 21), (6, 21)),
    ("巨蟹座", (6, 22), (7, 22)),
    ("狮子座", (7, 23), (8, 22)),
    ("处女座", (8, 23), (9, 22)),
    ("天秤座", (9, 23), (10, 23)),
    ("天蝎座", (10, 24), (11, 22)),
    ("射手座", (11, 23), (12, 21)),
)


def constellation_of(mmdd: str) -> str:
    """MM-DD -> 星座名；非法日期返回空串（绑定入口已先行校验，此处双保险）。"""
    try:
        m, d = int(str(mmdd)[:2]), int(str(mmdd)[3:5])
        datetime(2000, m, d)  # 日历合法性（拦截 13-40 之类，防跨年 or 误判）
    except Exception:
        return ""
    for name, (m1, d1), (m2, d2) in CONSTELLATION_RANGES:
        if (m1, d1) <= (m2, d2):
            hit = (m1, d1) <= (m, d) <= (m2, d2)
        else:  # 跨年（摩羯）
            hit = (m, d) >= (m1, d1) or (m, d) <= (m2, d2)
        if hit:
            return name
    return ""


def amulet_weights(weights: dict | None = None) -> dict:
    """厄运护身符（F22，M7 使用）：凶/大凶的权重并入小吉，实现「保底小吉」。"""
    base = dict(weights) if weights else dict(DEFAULT_GRADE_WEIGHTS)
    merged = int(base.pop("凶", 0)) + int(base.pop("大凶", 0))
    base["小吉"] = int(base.get("小吉", 0)) + merged
    return base


def apply_candle(result: dict) -> dict:
    """幸运香烛（F22，M7 使用）：幸运指数 +8（封顶 100），不改吉凶档，幂等。"""
    boosts = result.setdefault("boosts", {})
    if boosts.get("candle"):
        return result
    result["score"] = min(100, int(result.get("score", 0)) + 8)
    boosts["candle"] = True
    return result


DEFAULT_LLM_PERSONA = (
    "你是「星语者」，一位温柔微傲娇的占星见习生。根据给出的事实清单，为这位用户写一段今日签文："
    "第二人称、60 字以内、2~3 句，结合幸运物与宜忌给一句具体的小建议；"
    "凶日要温柔安慰、吉日要大方恭喜。只输出签文本身，不要解释、引号或表情。"
)


def llm_facts(result: dict) -> str:
    """当日运势事实清单（F16：喂给 LLM 的脱敏事实，不含任何用户身份信息）。"""
    dims = result.get("dims") or {}
    dim_text = "、".join(f"{k}{v}星" for k, v in dims.items())
    color = (result.get("lucky_color") or {}).get("name", "")
    phase = result.get("phase") or {}
    tarot = result.get("tarot") or {}
    tarot_text = ""
    if tarot:
        tarot_text = (f"\n今日塔罗：{tarot.get('name_cn', '')}"
                      f"（{tarot.get('label', '')}）——{tarot.get('keywords', '')}")
    return (
        f"吉凶：{result.get('grade', '')}（幸运指数 {result.get('score', '')}）\n"
        f"六维：{dim_text}\n"
        f"幸运物：{result.get('lucky_item', '')}；幸运色：{color}；"
        f"幸运数字：{result.get('lucky_number', '')}；幸运方位：{result.get('lucky_dir', '')}\n"
        f"宜：{'、'.join(result.get('yi') or [])}；忌：{'、'.join(result.get('ji') or [])}\n"
        f"月相：{phase.get('name', '')}"
        f"{tarot_text}"
    )


# ---------- M6：anima 底图联动的提示词与响应解析 ----------

DRAW_SYSTEM_HINT = (
    "You write image-generation prompts for a moe astrology fortune card. "
    "Output ONLY the prompt itself."
)

DRAW_GRADE_MOODS_EN = {
    "大吉": "radiant smile, sparkling eyes, golden sparkles, celebration",
    "吉": "gentle smile, warm light, soft glow",
    "中吉": "calm expression, serene, soft pastel mood",
    "小吉": "shy smile, cute, delicate",
    "凶": "melancholy, gloomy mood, drizzle",
    "大凶": "tearful pout, dramatic clouds, under a broken umbrella",
}

DRAW_GRADE_MOODS_ZH = {
    "大吉": "光芒四射、喜气洋洋", "吉": "温柔微笑、暖光环绕",
    "中吉": "平静安详、淡彩氛围", "小吉": "害羞可爱",
    "凶": "微微忧郁、细雨", "大凶": "委屈嘟嘴、头顶乌云",
}


def builtin_draw_prompt(lang: str, fmt: str) -> str:
    """生图提示词的 LLM 指令模板（塔罗牌牌面 + 动漫风格，PRD §7.6-3）。"""
    if lang == "zh":
        shape = "一段自然流畅的中文画面描述（不要标签堆砌）" if fmt == "natural" else "中文短语式描述"
        return (
            "根据下面的事实清单，为一张**动漫风格的塔罗牌牌面**插画写" + shape + "："
            "画面即清单中「今日塔罗」那张大阿卡纳的牌面演绎（牌面主题为中央构图），"
            "配华丽塔罗牌边框、星月与神秘学纹样，动漫赛璐璐质感，不要出现任何文字。"
            "只输出描述本身。\n{facts}"
        )
    if fmt == "natural":
        return (
            "Based on the fortune facts below, write ONE English sentence describing an "
            "ANIME-STYLE TAROT CARD illustration: the major arcana card named in the facts "
            "as the central motif, a complete ornate tarot card border fully visible and "
            "perfectly centered, symmetrical composition, portrait orientation, nothing "
            "cropped at the edges, mystical star-and-moon ambience, cel-shaded anime art. "
            "No Chinese, no explanations, output only the sentence.\n{facts}"
        )
    return (
        "Based on the fortune facts below, write ONE line of English Danbooru-style tags for an "
        "ANIME-STYLE TAROT CARD illustration: the major arcana card named in the facts as the "
        "central motif, symmetrical composition, centered, complete ornate tarot card border "
        "fully visible inside the frame, nothing cropped at the edges, portrait orientation, "
        "mystical symbols, star and crescent moon background, anime style, cel shading, "
        "masterpiece, best quality. Comma-separated lowercase tags, no sentences, no Chinese, "
        "no explanations. Output only the tags.\n{facts}"
    )


def local_draw_prompt(result: dict, lang: str, fmt: str) -> str:
    """LLM 不可用时的本地兜底提示词（塔罗牌牌面 + 吉凶氛围，PRD §7.6-4）。"""
    grade = result.get("grade", "")
    tarot = result.get("tarot") or {}
    arcana = tarot.get("name_en") or "The Star"
    if lang == "zh":
        mood = DRAW_GRADE_MOODS_ZH.get(grade, "温柔")
        return (f"动漫风格塔罗牌牌面：大阿卡纳「{tarot.get('name_cn', '星星')}」为主题的少女，"
                f"{mood}，完整华丽的塔罗牌边框居中且左右对称，构图饱满不裁边，"
                f"竖版构图，星月神秘氛围，淡彩，画质精美")
    mood = DRAW_GRADE_MOODS_EN.get(grade, "gentle smile")
    return (
        f"tarot card design, anime style, 1girl, solo, {mood}, "
        f"the {arcana} major arcana motif, symmetrical composition, centered, "
        "complete ornate tarot card border fully visible, nothing cropped, "
        "portrait orientation, stars, crescent moon, mystical ambience, "
        "soft pastel colors, masterpiece, best quality"
    )


def parse_draw_response(raw) -> list:
    """解析 anima comfyui_draw 的返回文本 → 本地图片路径列表。

    source 命中约定值时 anima 返回 JSON 文本：{"image_paths": [...], ...}
    （兼容旧的单数 image_path 字段）；容错：截取花括号段再解析，失败返回空表。
    """
    text = str(raw or "")
    data = {}
    try:
        loaded = json.loads(text)
        if isinstance(loaded, dict):
            data = loaded
    except Exception:
        m = re.search(r"\{.*\}", text, re.S)
        if m:
            try:
                loaded = json.loads(m.group(0))
                if isinstance(loaded, dict):
                    data = loaded
            except Exception:
                data = {}
    paths = data.get("image_paths") or []
    if not paths and data.get("image_path"):
        paths = [data["image_path"]]
    out = []
    for p in paths:
        if isinstance(p, str) and p.strip():
            out.append(p.strip())
    return out


# ---------- M7：道具经济（F22/D8，口径见 PRD「道具经济明细」） ----------

STARDUST_GRADE_BONUS = {
    "大吉": 20, "吉": 15, "中吉": 12, "小吉": 10, "凶": 14, "大凶": 18,
}


def stardust_reward(grade: str, streak: int, base: int = 10) -> int:
    """每日抽签的星尘奖励：基础 + 吉凶修正（越倒霉补偿越多）+ 连签加成（2/4/6 档）。"""
    if streak >= 30:
        streak_bonus = 6
    elif streak >= 7:
        streak_bonus = 4
    elif streak >= 3:
        streak_bonus = 2
    else:
        streak_bonus = 0
    return int(base) + STARDUST_GRADE_BONUS.get(grade, 10) + streak_bonus


# ---------- M8：塔罗牌（22 张大阿卡纳，随种子每日一张） ----------

TAROT_MAJOR = (
    ("愚者", "The Fool", "新起点 · 冒险 · 无限可能",
     "背起行囊就出发吧，此刻的你不需要太多准备，路会教你怎么走。"),
    ("魔术师", "The Magician", "创造 · 行动 · 资源",
     "你手里其实什么都有，缺的只是把它们用起来的那点决心。"),
    ("女祭司", "The High Priestess", "直觉 · 静谧 · 内在之声",
     "安静下来，答案早就藏在你的直觉里，今天别急着问别人。"),
    ("皇后", "The Empress", "丰饶 · 温柔 · 滋养",
     "好好犒劳自己，温柔和丰盛都值得被你大大方方地拥有。"),
    ("皇帝", "The Emperor", "秩序 · 稳固 · 掌控",
     "把节奏握在自己手里，今天你说了算，别被人带偏。"),
    ("教皇", "The Hierophant", "指引 · 传统 · 学习",
     "听听过来人的话，经验是今天最短的那条捷径。"),
    ("恋人", "The Lovers", "选择 · 契合 · 心意",
     "跟随心意做选择，坦诚一点，关系会更进一步。"),
    ("战车", "The Chariot", "前进 · 意志 · 胜利",
     "目标已经明确，别踩刹车，全力冲刺就是最好的答案。"),
    ("力量", "Strength", "勇气 · 耐心 · 柔韧",
     "不必声张，温柔而坚定就是今天最大的力量。"),
    ("隐士", "The Hermit", "沉思 · 独处 · 寻找",
     "给自己留一段独处的时光，想清楚了再出发也不迟。"),
    ("命运之轮", "Wheel of Fortune", "转机 · 周期 · 好运",
     "转机就在眼前，轮到你的时候，记得伸手接住它。"),
    ("正义", "Justice", "公平 · 权衡 · 因果",
     "种什么因得什么果，这条法则今天格外灵验，行得正坐得直。"),
    ("倒吊人", "The Hanged Man", "换个角度 · 暂停 · 释然",
     "卡住的时候换个视角看看，暂停本身也是一种前进。"),
    ("死神", "Death", "告别 · 蜕变 · 新生",
     "该翻篇的就翻篇，腾出双手，才接得住新的东西。"),
    ("节制", "Temperance", "平衡 · 调和 · 适度",
     "火候到了自然成，今天最忌一口气吃成胖子。"),
    ("恶魔", "The Devil", "觉察 · 破除执念 · 松绑",
     "看清那个让你停不下来的执念，然后轻轻地，把它放下。"),
    ("高塔", "The Tower", "骤变 · 崩塌 · 重建",
     "意外只是重建的序幕，塌过的地方会盖得更稳。"),
    ("星星", "The Star", "希望 · 疗愈 · 星光",
     "许下的愿望已经在路上，今晚适合抬头看看星光。"),
    ("月亮", "The Moon", "想象 · 梦境 · 潮汐",
     "有些事暂时看不真切，别急着下结论，让月亮替你多看一会儿。"),
    ("太阳", "The Sun", "喜悦 · 成功 · 活力",
     "把开心写在脸上，今天的你走到哪里都自带光芒。"),
    ("审判", "Judgement", "觉醒 · 召唤 · 重生",
     "该觉醒的总会觉醒，听从内心那个声音，它很少出错。"),
    ("世界", "The World", "完成 · 圆满 · 远行",
     "一段旅程正圆满落幕，好好纪念一下，再奔赴下一场。"),
)


def tarot_of(seed: bytes) -> dict:
    """由种子确定今日大阿卡纳（牌面、正逆位与解读，纯函数可测）。"""
    name_cn, name_en, keywords, interp = TAROT_MAJOR[_sub_int(seed, "tarot", len(TAROT_MAJOR))]
    reversed_card = bool(_sub_int(seed, "tarot_rev", 2))
    return {
        "name_cn": name_cn,
        "name_en": name_en,
        "keywords": keywords,
        "interp": interp,
        "reversed": reversed_card,
        "label": "逆位" if reversed_card else "正位",
    }
