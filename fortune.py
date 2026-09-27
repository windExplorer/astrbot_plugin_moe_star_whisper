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
    return (
        f"吉凶：{result.get('grade', '')}（幸运指数 {result.get('score', '')}）\n"
        f"六维：{dim_text}\n"
        f"幸运物：{result.get('lucky_item', '')}；幸运色：{color}；"
        f"幸运数字：{result.get('lucky_number', '')}；幸运方位：{result.get('lucky_dir', '')}\n"
        f"宜：{'、'.join(result.get('yi') or [])}；忌：{'、'.join(result.get('ji') or [])}\n"
        f"月相：{phase.get('name', '')}"
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
    """生图提示词的 LLM 指令模板（含 anima 提示词语言规范约束，PRD §7.6-3）。"""
    if lang == "zh":
        shape = "一段自然流畅的中文画面描述（不要标签堆砌）" if fmt == "natural" else "中文短语式描述"
        return (
            "根据下面的事实清单，为一张萌系运势卡插画写{shape}："
            "一位少女、结合幸运物入画、带星月氛围，不要出现文字。只输出描述本身。\n{facts}"
        ).format(shape=shape, facts="{facts}")
    if fmt == "natural":
        return (
            "Based on the fortune facts below, write ONE English sentence describing a moe "
            "anime illustration (no Chinese, no explanations): a girl, the lucky item as a motif, "
            "star and moon ambience, matching the mood. Output only the sentence.\n{facts}"
        )
    return (
        "Based on the fortune facts below, write ONE line of English Danbooru-style tags for a "
        "moe anime illustration: comma-separated lowercase tags, no sentences, no Chinese, no "
        "explanations. Must include 1girl, solo, a mood-matching scene, the lucky item as a motif, "
        "star and moon ambience, masterpiece, best quality. Output only the tags.\n{facts}"
    )


def local_draw_prompt(result: dict, lang: str, fmt: str) -> str:
    """LLM 不可用时的本地兜底提示词（吉凶氛围 + 幸运物，PRD §7.6-4）。"""
    grade = result.get("grade", "")
    item = str(result.get("lucky_item", "星星"))
    if lang == "zh":
        mood = DRAW_GRADE_MOODS_ZH.get(grade, "温柔")
        return f"一张萌系运势插画：少女与「{item}」，{mood}，星月氛围，淡彩，画质精美"
    mood = DRAW_GRADE_MOODS_EN.get(grade, "gentle smile")
    return (
        f"1girl, solo, {mood}, holding a lucky charm ({item}), "
        "stars, crescent moon, night sky, soft pastel colors, masterpiece, best quality"
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
