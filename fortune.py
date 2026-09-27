# -*- coding: utf-8 -*-
"""萌萌星语 · 运势核心（纯函数，不依赖 astrbot，可独立测试）。

确定性原则（PRD §3.1）：
    seed = SHA-256(f"{date}|{user_id}|{salt}|{nonce}")
所有维度由种子派生（hashlib，禁止全局 random），同一天同一人结果恒定：
跨时刻、跨群一致；换签卡 = nonce+1 重掷；底图种子同理，一人一天一张。
"""
from __future__ import annotations

import hashlib
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


def local_today(tz_name: str = "Asia/Shanghai") -> str:
    """插件时区的今天（YYYY-MM-DD）。时区非法或环境缺 tzdata 时回退 Asia/Shanghai；
    仍失败（如 Windows 未装 tzdata 包）则用固定偏移 UTC+8，绝不让时区问题炸掉抽签。"""
    try:
        tz = ZoneInfo(tz_name)
    except Exception:
        try:
            tz = ZoneInfo("Asia/Shanghai")
        except Exception:
            tz = timezone(timedelta(hours=8))
    return datetime.now(tz).strftime("%Y-%m-%d")


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
