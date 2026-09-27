# -*- coding: utf-8 -*-
"""萌萌星语 · 词库加载（data/lexicon/fortune_lexicon.json）。"""
from __future__ import annotations

import json
from pathlib import Path

LEXICON_FILE = Path(__file__).resolve().parent / "data" / "lexicon" / "fortune_lexicon.json"

REQUIRED_KEYS = (
    "grades", "grade_colors", "comments", "wishes", "item_lines",
    "lucky_items", "lucky_colors", "directions", "yi", "ji", "phases", "pk",
)

_cache: dict | None = None


def validate_lexicon(data: dict) -> None:
    """深度校验：池非空、宜忌池 >=2、点评/祝语覆盖全部吉凶档、结构字段齐全。

    坏词库必须在加载期报错，而不是等到用户抽签时才以 ZeroDivisionError/KeyError 炸掉
    （与「缺键加载期暴露」同一理念）。
    """
    missing = [k for k in REQUIRED_KEYS if k not in data]
    if missing:
        raise ValueError(f"词库缺少字段: {missing}")
    for key in ("grades", "lucky_items", "lucky_colors", "directions",
                "item_lines", "phases"):
        if not isinstance(data.get(key), list) or not data[key]:
            raise ValueError(f"词库 {key} 必须是非空列表")
    for key in ("yi", "ji"):
        if not isinstance(data.get(key), list) or len(data[key]) < 2:
            raise ValueError(f"词库 {key} 至少需要 2 条（要从中不重复抽两条）")
    grades = data["grades"]
    for key in ("comments", "wishes"):
        section = data.get(key) or {}
        absent = [
            g for g in grades
            if not isinstance(section.get(g), list) or not section[g]
        ]
        if absent:
            raise ValueError(f"词库 {key} 缺少档位或为空: {absent}")
    for color in data["lucky_colors"]:
        if not isinstance(color, dict) or "name" not in color or "hex" not in color:
            raise ValueError("词库 lucky_colors 每项需含 name/hex")
    for phase in data["phases"]:
        if not isinstance(phase, dict) or "name" not in phase or "text" not in phase:
            raise ValueError("词库 phases 每项需含 name/text")
    pk = data.get("pk") or {}
    for key in ("win", "lose", "tie"):
        if not isinstance(pk.get(key), list) or not pk[key]:
            raise ValueError(f"词库 pk.{key} 必须是非空列表")


def load_lexicon(force_reload: bool = False) -> dict:
    """加载并缓存词库；缺字段直接抛错（打包漏文件必须第一时间暴露）。"""
    global _cache
    if _cache is not None and not force_reload:
        return _cache
    with open(LEXICON_FILE, "r", encoding="utf-8") as f:
        data = json.load(f)
    validate_lexicon(data)
    _cache = data
    return _cache
