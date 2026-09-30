# -*- coding: utf-8 -*-
"""store.py 测试：临时库上验证一日一签 / streak / 档案快照。直接运行，退出码即结论。"""
import sys
import tempfile
from datetime import datetime
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

    # card_path 只存在 fortunes 的独立列（payload 里没有该键）——v1.8.7 的
    # 「当日第二次抽签退回纯文本」正是读取方误读 payload 造成的，这里锁死结构。
    st.save_fortune("c1", "2026-09-27", {"grade": "吉", "score": 60}, card_path="card-c1.png")
    crow = st.get_fortune("c1", "2026-09-27")
    check(crow["card_path"] == "card-c1.png", "card_path 落列并可读回")
    check("card_path" not in crow["payload"], "payload 不含 card_path（读取方必须取列）")
    st.set_card_path("c1", "2026-09-27", "card-c1-retry.png")
    check(st.get_fortune("c1", "2026-09-27")["card_path"] == "card-c1-retry.png",
          "set_card_path 应能回写补渲染的卡路径")

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

    # 种子序号（v1.3.1）：持久在档案，重置删签后仍可自增换种子
    st.upsert_profile("u1", seed_date="2026-09-27", seed_nonce=2)
    p3 = st.get_profile("u1")
    check(p3["seed_date"] == "2026-09-27" and p3["seed_nonce"] == 2,
          f"种子序号持久化，实际 {p3.get('seed_date')}/{p3.get('seed_nonce')}")
    st.delete_fortune("u1", "2026-09-27")
    p4 = st.get_profile("u1")
    check(p4["seed_nonce"] == 2, "删除签记录后种子序号仍在档案")

    # 群榜聚合（M3）：用独立群号，避免与前面用例的 g1 数据互相污染
    def fake(score, grade="吉"):
        return {"grade": grade, "score": score, "date": "x"}

    st.save_fortune("w1", "2026-09-27", fake(90), nickname="甲", group_id="wg1")
    st.save_fortune("w2", "2026-09-27", fake(70), nickname="乙", group_id="wg1")
    st.save_fortune("w3", "2026-09-27", fake(99), nickname="隔壁", group_id="wg2")
    st.save_fortune("w1", "2026-09-28", fake(60, "凶"), nickname="甲", group_id="wg1")
    day = st.list_group_day("wg1", "2026-09-27")
    check([r["user_id"] for r in day] == ["w1", "w2"],
          f"日榜分数降序且只含本群，实际 {[r['user_id'] for r in day]}")
    check(day[0]["grade"] == "吉", f"日榜行要带吉凶（徽章显示用），实际 {day[0].get('grade')}")
    week = st.list_group_range_avg("wg1", "2026-09-22")
    check(week[0]["user_id"] == "w1" and abs(week[0]["avg_score"] - 75) < 0.01,
          f"周榜甲均分 75 应第一，实际 {week[0]}")
    check(week[1]["user_id"] == "w2" and week[1]["days"] == 1, "周榜乙 1 天")
    # v1.10.10：周榜带 last_grade（区间内最近一签）——甲 09-28 抽的「凶」，不是更早的「吉」
    check(week[0]["last_grade"] == "凶",
          f"周榜 last_grade 应取最近一签（09-28 的凶），实际 {week[0].get('last_grade')}")
    check(week[1]["last_grade"] == "吉", "周榜只有一天时 last_grade 就是他那一签")
    # 人数可配：limit 必须真的下推到 SQL（v1.10.10 前是函数内写死的 10）
    check(len(st.list_group_range_avg("wg1", "2026-09-22", limit=1)) == 1, "周榜 limit 下推")
    check(len(st.list_group_day("wg1", "2026-09-27", limit=1)) == 1, "日榜 limit 下推")
    # 成员口径那条路（不限群聚合）同样要带 last_grade
    allw = st.list_range_avg_all("2026-09-22", 300)
    w1 = next(r for r in allw if r["user_id"] == "w1")
    check(w1["last_grade"] == "凶", f"list_range_avg_all 也要带 last_grade，实际 {w1}")

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

    # 星尘展示与运势日历（M9）：当日抽签星尘 / 月签记录 / 最近昵称
    check(st.day_stardust("e1", "2026-09-27") == 30,
          f"当日 draw 流水合计 30，实际 {st.day_stardust('e1', '2026-09-27')}")
    check(st.day_stardust("e1", "2026-09-28") == 0, "非 draw 流水不计入当日星尘")
    check(st.day_stardust("nobody", "2026-09-27") == 0, "无记录用户当日星尘 0")
    st.save_fortune("e1", "2026-09-05", {"grade": "大吉", "score": 88})
    st.save_fortune("e1", "2026-09-26", {"grade": "小吉", "score": 55})
    st.save_fortune("e1", "2026-09-27", {"grade": "吉", "score": 66})
    month = st.month_fortunes("e1", "2026-09")
    check([r["date"] for r in month] == ["2026-09-05", "2026-09-26", "2026-09-27"],
          f"月签记录按日期升序，实际 {[r['date'] for r in month]}")
    check(all({"date", "grade", "score"} <= set(r.keys()) for r in month), "月签记录字段齐备")
    check(st.month_fortunes("e1", "2026-10") == [], "无记录月份返回空表")
    check(st.last_nickname("w1") == "甲", f"最近昵称可查，实际 {st.last_nickname('w1')!r}")
    check(st.last_nickname("u1") == "" or st.last_nickname("u1") == "测试君",
          f"已删记录用户的最近昵称不误报，实际 {st.last_nickname('u1')!r}")
    check(st.last_nickname("nobody") == "", "无记录用户最近昵称为空")

    # 调试历史（v1.6.3）：记录/去重/按最近排序
    st.record_debug_uid("10086")
    st.record_debug_uid("23456")
    st.record_debug_uid("10086")
    uids = st.list_debug_uids(8)
    check(uids[0] == "10086" and "23456" in uids and len(uids) == 2,
          f"调试历史去重按最近排序，实际 {uids}")

    # 调试：删除当日签（v1.1.0）
    ok_del = st.delete_fortune("e1", "2026-09-28")
    check(ok_del is False, "无记录删除返回 False")
    st.save_fortune("del1", "2026-09-27", {"grade": "吉", "score": 50})
    check(st.delete_fortune("del1", "2026-09-27") is True, "删除当日签")
    check(st.get_fortune("del1", "2026-09-27") is None, "删除后不可读")
    check(st.delete_fortune("del1", "2026-09-27") is False, "重复删除返回 False")

    # 统计与面板查询（v1.9.0 WebUI 控制台）：换到**独立库**上验证聚合
    # （前面的段落已在同一库里写了多个用户/群的数据，混着做不出严格断言）
    st.close()
    st = Store(tmp / "stats.db")

    def payload(grade, score, dim, item, color, color_hex, streak):
        return {
            "grade": grade,
            "score": score,
            "dims": {"恋爱运": dim, "学业运": dim, "财运": dim, "健康运": dim, "社交运": dim, "摸鱼运": dim},
            "lucky_item": item,
            "lucky_color": {"name": color, "hex": color_hex},
            "streak": streak,
            "constellation": "天蝎座",
        }

    st.save_fortune("s1", "2026-09-20", payload("大吉", 90, 5, "四叶草", "樱粉", "#F0A0B8", 1),
                    nickname="统计甲", group_id="sg1", group_name="统计群", card_path="card-s1.png")
    st.save_fortune("s2", "2026-09-20", payload("凶", 30, 3, "四叶草", "樱粉", "#F0A0B8", 1),
                    nickname="统计乙", group_id="sg1", group_name="统计群")
    st.save_fortune("s1", "2026-09-21", payload("吉", 70, 4, "松果", "雾蓝", "#A8C8E8", 2),
                    nickname="统计甲", group_id="sg1", group_name="统计群")

    day = st.stats_day("2026-09-20")
    check(day["draws"] == 2 and day["users"] == 2, f"stats_day 抽签/人数，实际 {day}")
    check(abs(day["avg_score"] - 60.0) < 0.01, f"stats_day 均分 60，实际 {day['avg_score']}")
    check(day["lucky"] == 1 and day["unlucky"] == 1, "stats_day 吉签/凶签各 1")

    trend = st.stats_trend("2026-09-20")
    check([r["date"] for r in trend] == ["2026-09-20", "2026-09-21"], f"stats_trend 日期升序，实际 {trend}")
    check(trend[0]["great"] == 1 and trend[0]["bad"] == 1, "stats_trend 大吉/凶计数")

    grades = st.stats_grades("2026-09-20")
    check(grades == {"大吉": 1, "凶": 1, "吉": 1}, f"stats_grades 档位分布，实际 {grades}")
    daily = st.stats_grade_daily("2026-09-20")
    check(len(daily) == 3 and {r["grade"] for r in daily} == {"大吉", "凶", "吉"}, "stats_grade_daily 按日×档位")

    hours = st.stats_hours("2026-09-20")
    check(len(hours) == 24 and sum(hours) == 3, f"stats_hours 24 桶且合计 3，实际 {sum(hours)}")

    groups = [g for g in st.stats_groups("2026-09-20", 50) if g["group_id"] == "sg1"]
    check(groups and groups[0]["draws"] == 3 and groups[0]["users"] == 2,
          f"stats_groups sg1 抽签 3/人数 2，实际 {groups}")
    check(groups[0]["great"] == 1 and groups[0]["bad"] == 1 and groups[0]["cards"] == 1,
          f"stats_groups 大吉/凶签/图卡列，实际 {groups[0]}")
    check(groups[0]["last_date"] == "2026-09-21", f"stats_groups 最近活跃日期，实际 {groups[0]['last_date']}")
    check(st.stats_private("2026-09-20") == {"draws": 0, "users": 0}, "区间内没有私聊抽签")

    pdata = st.stats_payload("2026-09-20")
    check(pdata["sampled"] == 3, f"stats_payload 采样 3 条，实际 {pdata['sampled']}")
    check(abs(pdata["dims"].get("恋爱运", 0) - 4.0) < 0.01, f"六维均值 4.0，实际 {pdata['dims']}")
    check(pdata["items"][0] == {"name": "四叶草", "n": 2}, f"幸运物 Top，实际 {pdata['items']}")
    check(pdata["colors"][0]["name"] == "樱粉" and pdata["colors"][0]["n"] == 2, "幸运色 Top")
    check(pdata["constellations"] == [{"name": "天蝎座", "n": 3}], "星座分布")
    check(pdata["streaks"]["1"] == 2 and pdata["streaks"]["2"] == 1, f"连签档位，实际 {pdata['streaks']}")

    st.record_draw_job("s1", "2026-09-20", status="ok", duration_ms=1000, workflow="wf")
    st.record_draw_job("s1", "2026-09-21", status="timeout", duration_ms=3000)
    jobs = st.stats_jobs("2026-09-20")
    check(jobs["total"] == 2 and jobs["ok"] == 1 and jobs["success_rate"] == 50.0,
          f"stats_jobs 成功率 50%，实际 {jobs}")
    check(jobs["by_status"]["timeout"]["avg_ms"] == 3000, "stats_jobs 分状态均耗时")
    check(len(jobs["by_day"]) == 2, "stats_jobs 按日拆解")

    st.add_ledger("s1", 30, "draw", "2026-09-20")
    st.add_ledger("s1", -20, "buy:reroll", "2026-09-21")
    ledger = st.stats_ledger("2000-01-01")
    check(ledger["income"] >= 30 and ledger["spend"] >= 20, f"stats_ledger 收支，实际 {ledger}")
    check(any(r["reason"] == "buy:reroll" for r in ledger["by_reason"]), "stats_ledger 按原因聚合")
    check(any(r["day"] == datetime.now().strftime("%Y-%m-%d") for r in ledger["by_day"]),
          "stats_ledger 按日聚合（created_at 前 10 位）")

    recs = st.list_records(date_from="2026-09-20", date_to="2026-09-21")
    check(recs["total"] == 3 and recs["rows"][0]["date"] == "2026-09-21",
          f"list_records 区间 3 条且新→旧，实际 {recs['total']}")
    check(recs["rows"][0]["has_card"] is False and any(r["has_card"] for r in recs["rows"]),
          "list_records 卡文件状态取行内 card_path 列")
    only_grade = st.list_records(date_from="2026-09-20", date_to="2026-09-21", grade="大吉")
    check(only_grade["total"] == 1 and only_grade["rows"][0]["uid"] == "s1", "list_records 档位过滤")
    by_kw = st.list_records(keyword="统计甲")
    check(by_kw["total"] == 2, f"list_records 昵称模糊搜索，实际 {by_kw['total']}")
    by_group = st.list_records(date_from="2026-09-20", date_to="2026-09-21", group_id="sg1")
    check(by_group["total"] == 3, "list_records 群过滤")
    paged = st.list_records(date_from="2026-09-20", date_to="2026-09-21", page=2, size=2)
    check(paged["total"] == 3 and len(paged["rows"]) == 1 and paged["page"] == 2, "list_records 分页")

    gs = [g for g in st.list_groups(50) if g["group_id"] == "sg1"]
    check(gs and gs[0]["group_name"] == "统计群" and gs[0]["draws"] == 3, "list_groups 群列表")
    ru = st.recent_users(50)
    check(any(u["uid"] == "s1" and u["draws"] == 2 for u in ru), f"recent_users 含 s1，实际 {ru[:3]}")
    hist = st.user_history("s1", 10)
    check(len(hist) == 2 and hist[0]["date"] == "2026-09-21" and hist[0]["streak"] == 2,
          f"user_history 新→旧且带连签，实际 {hist}")
    check(hist[0]["group_id"] == "sg1" and hist[0]["group_name"] == "统计群",
          f"user_history 带来源群（v1.9.3），实际 {hist[0]}")
    uled = st.user_ledger("s1", 10)
    check(len(uled) == 2 and uled[0]["reason"] == "buy:reroll", f"user_ledger 新→旧，实际 {uled}")
    counts = st.count_all()
    check(counts["fortunes"] >= 3 and set(counts) == {"fortunes", "profiles", "items", "ledger", "draw_jobs"},
          f"count_all 表行数，实际 {counts}")

    # 群归属口径（v1.9.1，需求明确要求）：同一用户当天先在 A 群抽签，之后换到 B 群
    # 再抽 —— 一日一签主键拒绝第二次写入，群归属保持第一次那个群，不会被重复计算
    st.save_fortune("t1", "2026-09-22", payload("吉", 60, 3, "松果", "雾蓝", "#A8C8E8", 1),
                    nickname="归属甲", avatar="http://a/t1.png",
                    group_id="tgA", group_name="A群")
    again = st.save_fortune("t1", "2026-09-22", payload("大凶", 10, 1, "松果", "雾蓝", "#A8C8E8", 1),
                            nickname="归属甲", group_id="tgB", group_name="B群")
    check(again is False, "同日换群再抽必须被拒绝（不写新行）")
    row_t1 = st.get_fortune("t1", "2026-09-22")
    check(row_t1["group_id"] == "tgA" and row_t1["score"] == 60,
          f"群归属与内容保持当天第一次的值，实际 {row_t1['group_id']}/{row_t1['score']}")
    group_draws = {g["group_id"]: g["draws"] for g in st.stats_groups("2026-09-22", 50)}
    check(group_draws.get("tgA") == 1 and "tgB" not in group_draws,
          f"群维度只计入首签所在群，实际 {group_draws}")
    check(len(st.user_history("t1", 5)) == 1, "该用户当天只有一条记录")
    check(st.stats_private("2026-09-22")["draws"] == 0, "该日无私聊记录")

    # 用户列表（v1.9.1）：头像 / 昵称 / QQ / 抽签天数 / 群数 / 排序与分页
    ulist = st.list_users(page=1, size=10)
    check(ulist["total"] == 3, f"抽过签的用户 3 人（s1/s2/t1），实际 {ulist['total']}")
    first = ulist["rows"][0]
    check(first["uid"] == "t1" and first["draws"] == 1 and first["groups"] == 1,
          f"list_users 默认按最近活跃排序，实际 {first}")
    check(first["nickname"] == "归属甲" and first["avatar"] == "http://a/t1.png",
          f"list_users 昵称与头像取最近有值的记录，实际 {first['nickname']}/{first['avatar']}")
    check(first["last_group_id"] == "tgA" and first["last_group_name"] == "A群", "list_users 最近所在群")
    check({"uid", "nickname", "avatar", "draws", "first_date", "last_date",
           "avg_score", "best_score", "groups", "last_group_id", "last_group_name"}
          <= set(first.keys()), "list_users 字段齐备")
    check(st.list_users(keyword="统计甲")["total"] == 1, "list_users 昵称模糊搜索")
    check(st.list_users(keyword="s2")["total"] == 1, "list_users QQ 号搜索")
    check(st.list_users(order="draws")["rows"][0]["draws"] == 2, "list_users 按抽签数排序")
    check(st.list_users(order="score")["rows"][0]["avg_score"] >= 60, "list_users 按均分排序")
    check(st.list_users(order="乱写")["rows"][0]["uid"] == "t1", "list_users 非法排序回落最近活跃")
    paged_users = st.list_users(page=2, size=1)
    check(len(paged_users["rows"]) == 1 and paged_users["page"] == 2, "list_users 分页")

    # 群名记录与回填（v1.9.3）：新记录带群名；历史行（没群名）用同群最新群名展示。
    # ⚠️ 这一段会新增一个用户（t2），必须放在用户列表断言之后，否则 total 断言就变了。
    st.save_fortune("t2", "2026-09-23", payload("吉", 55, 3, "松果", "雾蓝", "#A8C8E8", 1),
                    nickname="归属乙", group_id="tgA")  # 故意不传 group_name
    check(st.get_fortune("t2", "2026-09-23")["group_name"] == "", "未传群名时列里就是空")
    check(st.group_names().get("tgA") == "A群", f"群名映射，实际 {st.group_names()}")
    recs_tgA = st.list_records(date_from="2026-09-22", date_to="2026-09-23", group_id="tgA")
    check(recs_tgA["total"] == 2
          and all(r["group_name"] == "A群" for r in recs_tgA["rows"]),
          f"同群历史行回填最新群名，实际 {[r['group_name'] for r in recs_tgA['rows']]}")
    hist_t2 = st.user_history("t2", 5)
    check(hist_t2[0]["group_name"] == "A群", "user_history 也回填群名")
    t2_row = st.list_users(keyword="归属乙")["rows"][0]
    check(t2_row["last_group_name"] == "A群", "list_users 最近群名也回填")

    # 全体均分榜（v1.9.4 星语榜口径）：不限群，调用方再用群成员集合过滤，
    # 这样「人在本群、今天在别群抽签」的成员也能上榜
    st.save_fortune("t3", "2026-09-23", payload("大吉", 95, 5, "四叶草", "樱粉", "#F0A0B8", 1),
                    nickname="归属丙", group_id="tgB", group_name="B群")
    allavg = st.list_range_avg_all("2026-09-22", 50)
    check({r["user_id"] for r in allavg} == {"t1", "t2", "t3"},
          f"list_range_avg_all 不限群地含全部用户，实际 {[r['user_id'] for r in allavg]}")
    check(allavg[0]["user_id"] == "t3" and allavg[0]["avg_score"] == 95.0,
          f"按均分降序，实际 {allavg[0]}")
    check(allavg[0]["nickname"] == "归属丙" and allavg[0]["days"] == 1, "带昵称与抽签天数")
    check(allavg[0]["last_group_name"] == "B群" and allavg[0]["last_group_id"] == "tgB",
          "带最近所在群（供榜单标注来源）")
    check(st.list_range_avg_all("2027-01-01", 50) == [], "区间外返回空表")

    st.close()
    if FAILED:
        print(f"\n{len(FAILED)} 项失败")
        return 1
    print("\nstore.py 全部通过")
    return 0


if __name__ == "__main__":
    sys.exit(main())
