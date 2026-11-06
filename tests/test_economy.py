# -*- coding: utf-8 -*-
"""星尘 2.0 守卫（v1.11.12）：任务 / 双倍日 / 玩法 / 等级 / 成就 / 排行榜。

纯函数 + 真 SQLite 聚合 + 源码结构三层，不需要 astrbot 运行时。
退出码即结论。
"""
import json
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import fortune  # noqa: E402
import store  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
FAILED = []


def check(cond, msg):
    if not cond:
        FAILED.append(msg)
        print(f"FAIL: {msg}")


def main() -> int:
    # ---------- 1) 纯函数：等级 / 成就 / 双倍日 / 特价 / 文案池 ----------
    lv0 = fortune.stardust_level(0)
    check(lv0["level"] == 1 and lv0["next"] == 100 and lv0["to_next"] == 100,
          "0 星尘应是 1 级，距下一级 100")
    check(fortune.stardust_level(100)["level"] == 2, "刚好踩到阈值就升级")
    check(fortune.stardust_level(99)["level"] == 1, "差 1 颗不升级")
    lvmax = fortune.stardust_level(99999)
    check(lvmax["next"] is None and lvmax["progress"] == 1.0 and lvmax["to_next"] == 0,
          "满级后不再有下一级")
    check(all(0 <= fortune.stardust_level(n)["progress"] <= 1
              for n in range(0, 7000, 137)), "进度必须始终落在 0~1")
    check(all(fortune.stardust_level(n)["title"] for n in range(0, 7000, 137)),
          "每级都要有称号")

    full = {"draw_days": 99, "max_streak": 99, "total_earned": 99999,
            "total_spent": 99999, "fun_kinds": 9, "balance": 99999}
    ach = fortune.achievements({})
    check(len(ach) == 8 and all("done" in a and "cur" in a and "need" in a for a in ach),
          "成就徽章应有 8 枚且字段齐全")
    check(not any(a["done"] for a in ach), "空指标不应有已达成徽章")
    check(all(a["done"] for a in fortune.achievements(full)), "全达标时 8 枚都应点亮")
    check(all(a["cur"] <= a["need"] for a in fortune.achievements(full)),
          "进度展示不得超出门槛")

    check(fortune.is_double_day("2026-11-08"), "2026-11-08 是周日，应双倍")
    check(not fortune.is_double_day("2026-11-07"), "周六不应双倍")
    check(not fortune.is_double_day("not-a-date"), "坏日期不得抛错，按非双倍处理")

    keys = ("delight", "bless", "gift")
    check(fortune.daily_special("2026-11-07", "salt", keys)
          == fortune.daily_special("2026-11-07", "salt", keys),
          "同日特价必须确定")
    check(fortune.daily_special("2026-11-07", "salt", keys) in keys,
          "特价只能指向池内玩法")
    check(len({fortune.daily_special(f"2026-11-{d:02d}", "salt", keys)
               for d in range(1, 15)}) >= 2, "不同日期应能轮换到不同玩法")
    check(fortune.daily_special("2026-11-07", "salt", ()) == "", "空池返回空串")
    check(len(fortune.DELIGHT_LINES) >= 12 and len(fortune.BLESS_LINES) >= 10,
          "趣味/祝福文案池别太少（避免连玩几天复读）")
    check(all(str(x).strip() for x in fortune.DELIGHT_LINES + fortune.BLESS_LINES),
          "文案池不得有空串")
    seed = fortune.derive_seed("2026-11-07", "u", "s", 0)
    check(fortune.pick_from(seed, "x", (1, 2, 3))
          == fortune.pick_from(seed, "x", (1, 2, 3)), "非文本池抽样也要确定")

    # ---------- 2) 真库聚合：当日收入 / 经济指标 / 任务 / 排行 ----------
    db = store.Store(Path(tempfile.mkdtemp(prefix="moe_econ_")) / "t.db")
    uid = "10086"
    db.add_ledger(uid, 30, "draw", "2026-11-07")
    db.add_ledger(uid, 8, "task:calendar", "2026-11-07")
    db.add_ledger(uid, -30, "fun:delight", "2026-11-07")
    db.add_ledger(uid, 40, "gift:back", "2026-11-07")
    db.add_ledger(uid, 100, "admin", "")  # 管理员发放不带 ref_date
    db.add_ledger("20000", 20, "draw", "2026-11-07")
    db.upsert_profile(uid, max_streak=9)

    check(db.day_income(uid, "2026-11-07") == 78,
          "当日收入 = 抽签 30 + 任务 8 + 礼盒返利 40（不含消耗与管理员发放）")
    check(db.day_stardust(uid, "2026-11-07") == 30,
          "day_stardust 口径不变，只数 reason='draw'")
    stats = db.economy_stats(uid)
    check(stats["total_earned"] == 178 and stats["total_spent"] == 30
          and stats["balance"] == 148, "累计获得/消费/余额聚合")
    check(stats["fun_kinds"] == 1, "玩法种类按 distinct fun: 计")
    check(stats["max_streak"] == 9 and stats["draw_days"] == 0,
          "连签与抽签天数来自 profiles / fortunes")
    prog = db.task_progress(uid, "2026-11-07",
                            ("task:calendar", "task:rank", "task:star"))
    check(prog == {"task:calendar": True, "task:rank": False, "task:star": False},
          "任务进度按 (uid, 日期, reason) 判定")
    day_rank = db.stardust_ranking("day", 10, "2026-11-07", "2026-11-01")
    check([r["user_id"] for r in day_rank] == [uid, "20000"],
          "日榜按当日自然获得降序")
    check(day_rank[0]["total"] == 78, "日榜不含无 ref_date 的管理员发放")
    all_rank = db.stardust_ranking("all", 10, "2026-11-07", "2026-11-01")
    check(all_rank[0]["total"] == 178, "总榜按累计获得，含管理员发放")
    week_rank = db.stardust_ranking("week", 10, "2026-11-07", "2026-11-01")
    check(week_rank[0]["user_id"] == uid, "周榜按近 7 天获得")
    db.close()

    # ---------- 3) 源码结构：指令 / 触发点 / 配置 / 卡面 / WebUI ----------
    main_src = (ROOT / "main.py").read_text(encoding="utf-8")
    for cmd in ("星语玩", "星语任务", "星语星尘榜"):
        check(f'@filter.command("{cmd}"' in main_src, f"缺少指令 /{cmd}")
        check(f'"/{cmd}' in main_src, f"帮助图必须列出 /{cmd}（结构守卫会双向比对）")
    check(main_src.count("self._award_task(") == 3,
          "三条每日任务触发点都要接上（日历/榜/星象）")
    check("fortune.is_double_day(date)" in main_src, "首签发放必须判定周日双倍")
    check('result["double_day"] = True' in main_src, "双倍日要写进 payload")
    check('self._cfg("task_reward", 8)' in main_src
          and 'self._cfg("fun_prices", None)' in main_src,
          "新配置键必须真的被读取")
    check("FUN_DEFS" in main_src and "ITEM_DEFS" in main_src,
          "服务型玩法刻意独立于四道具（避免 4-id 硬编码连锁）")

    card_src = (ROOT / "card.py").read_text(encoding="utf-8")
    check(card_src.count("extras: list | None = None") == 2,
          "钱包卡与商店卡都要支持 extras 且默认 None（旧调用零影响）")
    check("今日星尘收入" in card_src, "钱包卡文案要与 day_income 口径一致")

    schema = json.loads((ROOT / "_conf_schema.json").read_text(encoding="utf-8"))
    for key, kind in (("fun_prices", "dict"), ("task_reward", "int")):
        check(schema.get(key, {}).get("type") == kind,
              f"{key} 必须有合法 type（AstrBot 装载期会解析）")
    check(schema["task_reward"]["default"] == 8, "任务奖励默认 8")
    conf = (ROOT / "webui-src/src/views/ConfigView.vue").read_text(encoding="utf-8")
    check('"fun_prices"' in conf and '"task_reward"' in conf,
          "新配置键必须进 ConfigView 分区表（否则掉进「其他」）")
    labels = (ROOT / "webui-src/src/labels.ts").read_text(encoding="utf-8")
    for key in ("task:calendar", "fun:delight", "gift:back"):
        check(key in labels, f"流水原因 {key} 要有中文映射")
    webui = (ROOT / "webui_api.py").read_text(encoding="utf-8")
    check("_economy_view" in webui and "_safe_stardust_totals" in webui,
          "WebUI 必须提供经济视图与真实累计收支")
    overview = (ROOT / "webui-src/src/views/OverviewView.vue").read_text(encoding="utf-8")
    check("累计发放 / 消耗" in overview and "笔流水" not in overview,
          "总览不得再把流水笔数标成「累计星尘」")

    # ---------- 4) 卡面 extras 冒烟（有 Pillow + 中文字体才跑） ----------
    try:
        import card
        from PIL import Image
        if card.find_font(None):
            tmp = Path(tempfile.mkdtemp(prefix="moe_econ_card_"))
            items = [("换签卡", 1), ("厄运护身符", 2), ("连签保护卡", 0), ("幸运香烛", 1)]
            p1 = card.render_wallet_card("旅人", 148, items, tmp, file_key="plain")
            p2 = card.render_wallet_card(
                "旅人", 148, items, tmp, file_key="extras",
                extras=["Lv.2 星屑收集者 · 累计获得 178", "今日任务 1/3 · 成就徽章 2/8"])
            check(Image.open(p2).size[1] > Image.open(p1).size[1],
                  "钱包卡 extras 必须让卡片加高（不能把说明画到框外）")
            entries = [("换签卡", 80, "当日重抽一次，新结果覆盖旧结果", 1)]
            s1 = card.render_shop_card("旅人", entries, tmp, file_key="plain")
            s2 = card.render_shop_card(
                "旅人", entries, tmp, file_key="extras",
                extras=["今日特价：小确幸签 15 星尘", "· /星语玩 星尘礼盒 60★"])
            check(Image.open(s2).size[1] > Image.open(s1).size[1],
                  "商店卡 extras 必须让卡片加高")
    except ImportError:
        pass  # 无 Pillow 的环境跳过渲染冒烟，纯函数与结构守卫仍然生效

    if FAILED:
        print(f"\n{len(FAILED)} 项失败")
        return 1
    print("\neconomy.py 全部通过")
    return 0


if __name__ == "__main__":
    sys.exit(main())
