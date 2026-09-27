# -*- coding: utf-8 -*-
"""store.py 测试：临时库上验证一日一签 / streak / 档案快照。直接运行，退出码即结论。"""
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import fortune  # noqa: E402
import lexicon  # noqa: E402
from store import Store  # noqa: E402

FAILED = []


def check(cond, msg):
    if not cond:
        FAILED.append(msg)
        print(f"FAIL: {msg}")


def main() -> int:
    tmp = Path(tempfile.mkdtemp(prefix="moe_star_test_"))
    st = Store(tmp / "t.db")
    lex = lexicon.load_lexicon()
    weights = dict(fortune.DEFAULT_GRADE_WEIGHTS)

    result = fortune.roll_fortune(
        fortune.derive_seed("2026-09-27", "u1", "salt", 0), lex, weights
    )
    result["date"] = "2026-09-27"

    ok1 = st.save_fortune("u1", "2026-09-27", result,
                          nickname="测试君", avatar="http://a/1", group_id="g1")
    ok2 = st.save_fortune("u1", "2026-09-27", result)
    check(ok1 is True, "首次落库必须成功")
    check(ok2 is False, "一日一签：同日第二次 save 必须被主键拒绝并返回 False")

    row = st.get_fortune("u1", "2026-09-27")
    check(row is not None, "当日记录应可读回")
    if row:
        check(row["payload"].get("grade") == result["grade"], "payload 往返一致")
        check(row["nickname"] == "测试君" and row["group_id"] == "g1", "身份快照入库")

    # streak：首日 1 → 同日幂等 → 次日 2 → 断签回 1
    s1 = st.bump_streak("u1", "2026-09-27", "2026-09-26")
    s2 = st.bump_streak("u1", "2026-09-27", "2026-09-26")
    s3 = st.bump_streak("u1", "2026-09-28", "2026-09-27")
    s4 = st.bump_streak("u1", "2026-09-30", "2026-09-29")
    check((s1, s2, s3, s4) == (1, 1, 2, 1),
          f"streak 序列应为 1,1,2,1，实际 {s1},{s2},{s3},{s4}")
    p = st.get_profile("u1")
    check(p and p["max_streak"] == 2, f"max_streak 应为 2，实际 {p and p['max_streak']}")

    # 档案快照 upsert：只更新提供的字段
    st.upsert_profile("u1", nickname="新昵称", avatar="http://a/2")
    p2 = st.get_profile("u1")
    check(p2["nickname"] == "新昵称" and p2["avatar"] == "http://a/2", "档案昵称/头像更新")
    check(p2["streak"] == 1, "未提供的字段不被覆盖")

    # 群榜聚合（M3）：用独立群号，避免与前面用例的 g1 数据互相污染
    def fake(score):
        return {"grade": "吉", "score": score, "date": "x"}

    st.save_fortune("w1", "2026-09-27", fake(90), nickname="甲", group_id="wg1")
    st.save_fortune("w2", "2026-09-27", fake(70), nickname="乙", group_id="wg1")
    st.save_fortune("w3", "2026-09-27", fake(99), nickname="隔壁", group_id="wg2")
    st.save_fortune("w1", "2026-09-28", fake(60), nickname="甲", group_id="wg1")
    day = st.list_group_day("wg1", "2026-09-27")
    check([r["user_id"] for r in day] == ["w1", "w2"],
          f"日榜分数降序且只含本群，实际 {[r['user_id'] for r in day]}")
    week = st.list_group_range_avg("wg1", "2026-09-22")
    check(week[0]["user_id"] == "w1" and abs(week[0]["avg_score"] - 75) < 0.01,
          f"周榜甲均分 75 应第一，实际 {week[0]}")
    check(week[1]["user_id"] == "w2" and week[1]["days"] == 1, "周榜乙 1 天")

    # 活跃群列表（M5 推送目标集）：近 7 天有抽签的群
    ids = [g for g, _ in st.list_active_group_ids(7)]
    check("wg1" in ids and "wg2" in ids, f"活跃群应含 wg1/wg2，实际 {ids}")

    # 绘图任务落库（M6）
    st.record_draw_job("u1", "2026-09-27", workflow="wf1", prompt_lang="en",
                       prompt_fmt="tags", image_prompt="1girl, stars",
                       llm_prompt="tpl", status="ok", duration_ms=1234,
                       image_path="bg.png", card_path="card.png")
    jobs = st.get_draw_jobs("u1", "2026-09-27")
    check(len(jobs) == 1 and jobs[0]["status"] == "ok" and jobs[0]["duration_ms"] == 1234,
          "draw_jobs 落库与读回")

    # 道具经济（M7）：流水/余额/背包/佩戴标记
    st.add_ledger("e1", 30, "draw", "2026-09-27")
    st.add_ledger("e1", -20, "buy:reroll")
    check(st.get_balance("e1") == 10, f"余额=流水合计 10，实际 {st.get_balance('e1')}")
    check(st.get_balance("nobody") == 0, "无记录用户余额 0")
    st.add_item("e1", "reroll", 2)
    st.add_item("e1", "reroll", 1)
    check(st.get_item("e1", "reroll") == 3, "道具累加 upsert")
    st.add_item("e1", "reroll", -1)
    check(st.get_item("e1", "reroll") == 2, "道具扣减")
    st.add_ledger("e1", 0, "use:amulet", "2026-09-28")
    check(st.has_ledger("e1", "2026-09-28", "use:amulet"), "佩戴标记可查")
    check(not st.has_ledger("e1", "2026-09-28", "use:candle"), "未佩戴不误报")

    st.close()
    if FAILED:
        print(f"\n{len(FAILED)} 项失败")
        return 1
    print("\nstore.py 全部通过")
    return 0


if __name__ == "__main__":
    sys.exit(main())
