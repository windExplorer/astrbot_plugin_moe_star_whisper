# -*- coding: utf-8 -*-
"""好感度联动守卫（v1.12.0）：送礼定义 / 档位加成映射 / 流水计数 / schema。

纯函数 + 真 SQLite 聚合 + 源码结构三层，不需要 astrbot 运行时。退出码即结论。
"""
import json
import re
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import store  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
FAILED = []


def check(cond, msg):
    if not cond:
        FAILED.append(msg)
        print(f"FAIL: {msg}")
    else:
        print(f"  ok   {msg}")


def main() -> int:
    main_src = (ROOT / "main.py").read_text(encoding="utf-8")

    # ---------- 1) 送礼定义：别名全覆盖、分值压小、价格可解析 ----------
    ns = {}
    exec(compile(re.search(r"GIFT_DEFS = \{.*?\n\}", main_src, re.S).group(0),
                 "<main>", "exec"), ns)
    gift_defs = ns["GIFT_DEFS"]
    ns2 = {}
    exec(compile(re.search(r"GIFT_ALIASES = \{.*?\n\}", main_src, re.S).group(0),
                 "<main>", "exec"), ns2)
    gift_aliases = ns2["GIFT_ALIASES"]
    check(len(gift_defs) == 3, "三种心意：星光糖 / 星尘花束 / 星语贺卡")
    for gid, (_name, price, delta) in gift_defs.items():
        check(price > 0, f"{gid} 价格为正")
        check(0 < delta <= 4, f"{gid} 好感度压在 +1~+4（单次不超 4）")
        check(gid in gift_aliases and gift_aliases[gid] == gid,
              f"{gid} 至少有一个指向自己的别名")
    check("gift" not in gift_defs, "礼盒 id 不与星尘礼盒（fun:gift）冲突")

    # ---------- 2) 档位加成映射：键必须落在中枢档位键集合内 ----------
    ns3 = {}
    exec(compile(re.search(r"TIER_BONUS = \{.*?\n\}", main_src, re.S).group(0),
                 "<main>", "exec"), ns3)
    tier_bonus = ns3["TIER_BONUS"]
    # 中枢 STAGE_TABLE 的英文档位键（store.stage_of）：known/familiar/close/intimate/bonded
    check(set(tier_bonus) <= {"known", "familiar", "close", "intimate", "bonded"},
          "TIER_BONUS 键与中枢档位键对齐（stranger 无加成）")
    check(all(1 <= v <= 6 for v in tier_bonus.values()), "档位加成压在 +1~+6")
    check(list(tier_bonus.values()) == sorted(tier_bonus.values()),
          "档位越高加成越大（单调不减）")

    # ---------- 3) 流水计数：send: 前缀排除退款与礼盒返利 ----------
    tmp = Path(tempfile.mkdtemp(prefix="affinity_link_"))
    st = store.Store(tmp / "star_whisper.db")
    st.add_ledger("u1", -10, "send:candy", "2026-11-12")
    st.add_ledger("u1", 20, "gift:back", "2026-11-12")   # 星尘礼盒返利（v1.11.12 既有）
    st.add_ledger("u1", 10, "refund:send:candy", "2026-11-12")
    st.add_ledger("u1", -30, "send:bouquet", "2026-11-12")
    st.add_ledger("u1", 15, "draw", "2026-11-12")
    check(st.day_reason_count("u1", "2026-11-12", "send:") == 2,
          "送礼计数只认 send: 扣款，礼盒返利/退款/抽签都不算")
    check(st.day_reason_count("u1", "2026-11-13", "send:") == 0, "跨天归零")

    # ---------- 4) 源码结构：送礼流水不用 gift: 前缀扣款、幂等闸、开关 ----------
    check('add_ledger(uid, -price, f"gift:' not in main_src,
          "送礼扣款不得用 gift: 前缀（与礼盒返利 gift:back 撞车）")
    check('has_ledger(uid, date, "tier")' in main_src, "档位加成有 has_ledger 幂等闸")
    check('"gift_enabled"' in main_src and '"tier_bonus_enabled"' in main_src,
          "送礼与档位加成有配置开关")
    check("get_registered_star(AFFINITY_PLUGIN)" in main_src, "契约经 get_registered_star 获取")

    # ---------- 5) schema：新键齐全且每节点有 type ----------
    schema = json.loads((ROOT / "_conf_schema.json").read_text(encoding="utf-8"))
    allowed = {"int", "float", "bool", "string", "text", "list", "file",
               "object", "template_list", "dict"}
    bad = []

    def walk(node, path):
        if "type" not in node:
            bad.append(f"{path}: 缺少 type")
            return
        if node["type"] not in allowed:
            bad.append(f"{path}: 非法 type {node['type']}")
        if node["type"] == "dict":
            for key, child in (node.get("default") or {}).items():
                if not isinstance(child, (int, float, str)):
                    bad.append(f"{path}.{key}: dict 默认值非法")

    for key, node in schema.items():
        walk(node, key)
    check(not bad, f"schema 每节点有合法 type {bad or ''}")
    for key in ("gift_enabled", "gift_prices", "gift_daily_limit", "tier_bonus_enabled"):
        check(key in schema, f"schema 顶层键 {key} 存在")
    check(schema.get("gift_daily_limit", {}).get("default") == 2, "送礼每日上限默认 2 次（v1.12.1 压小）")

    print()
    if FAILED:
        print(f"RESULT: FAIL ({len(FAILED)} 项)")
        return 1
    print("RESULT: OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
