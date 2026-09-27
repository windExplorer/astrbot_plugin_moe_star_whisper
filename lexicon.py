# -*- coding: utf-8 -*-
"""萌萌星语 · 词库加载（data/lexicon/fortune_lexicon.json）。"""
from __future__ import annotations

import json
from pathlib import Path

LEXICON_FILE = Path(__file__).resolve().parent / "data" / "lexicon" / "fortune_lexicon.json"

REQUIRED_KEYS = (
    "grades", "grade_colors", "comments", "wishes", "item_lines",
    "lucky_items", "lucky_colors", "directions", "yi", "ji", "phases",
)

_cache: dict | None = None


def load_lexicon(force_reload: bool = False) -> dict:
    """加载并缓存词库；缺字段直接抛错（打包漏文件必须第一时间暴露）。"""
    global _cache
    if _cache is not None and not force_reload:
        return _cache
    with open(LEXICON_FILE, "r", encoding="utf-8") as f:
        data = json.load(f)
    missing = [k for k in REQUIRED_KEYS if k not in data]
    if missing:
        raise ValueError(f"词库缺少字段: {missing}（文件：{LEXICON_FILE}）")
    _cache = data
    return _cache
