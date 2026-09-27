# -*- coding: utf-8 -*-
"""card.py 冒烟测试。需 pillow：
uv run --no-project --with pillow python tests/test_card.py
退出码即结论。"""
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import fortune  # noqa: E402
import lexicon  # noqa: E402
import card  # noqa: E402
from PIL import Image  # noqa: E402

FAILED = []


def check(cond, msg):
    if not cond:
        FAILED.append(msg)
        print(f"FAIL: {msg}")


def main() -> int:
    lex = lexicon.load_lexicon()
    ff = card.find_font(None)
    if ff is None:
        print("SKIP: 未找到系统中文字体，跳过渲染断言（部署机按多级查找兜底）")
        return 0
    print(f"font: {ff}")

    r = fortune.roll_fortune(
        fortune.derive_seed("2026-09-27", "utest", "card"), lex, None
    )
    r["date"] = "2026-09-27"
    r["streak"] = 3

    tmp = Path(tempfile.mkdtemp(prefix="moe_card_"))

    # 1) 默认尺寸落盘、可打开、非空白（单联内容多时画布自动加高：高≥配置值）
    p1 = card.render_card(r, tmp, nickname="测试旅人", uid="10086")
    check(Path(p1).is_file(), "卡文件应落盘")
    img = Image.open(p1)
    img.load()
    check(img.size[0] == 1024 and img.size[1] >= 1536,
          f"宽 1024、高≥1536（自动加高），实际 {img.size}")
    lo, hi = img.convert("L").getextrema()
    check(hi - lo > 30, f"卡面应有明暗层次（extrema {lo}~{hi}）")

    # 2) 确定性：同输入两次渲染字节一致（不同目录避免同名覆盖）
    p2 = card.render_card(dict(r), Path(tempfile.mkdtemp(prefix="moe_card_")),
                          nickname="测试旅人", uid="10086")
    check(Path(p1).read_bytes() == Path(p2).read_bytes(), "同输入渲染必须字节一致")

    # 3) 小尺寸：宽按配置，高随内容只增不减
    p3 = card.render_card(r, Path(tempfile.mkdtemp(prefix="moe_card_")),
                          width=512, height=768, nickname="小", uid="2")
    _s3 = Image.open(p3).size
    check(_s3[0] == 512 and _s3[1] >= 768, f"小尺寸宽 512、高≥768，实际 {_s3}")

    # 3.5) M4：暗色主题 / 生日描边 / 星座角标 / grade_display 渲染冒烟
    r4 = dict(r)
    r4["birthday_today"] = True
    r4["grade_display"] = "大吉（？）"
    r4["constellation"] = "天秤座"
    p4 = card.render_card(r4, Path(tempfile.mkdtemp(prefix="moe_card_")),
                          theme="dark", nickname="夜旅人", uid="4")
    img4 = Image.open(p4)
    img4.load()
    check(img4.size[0] == 1024 and img4.size[1] >= 1536, f"暗色卡宽 1024、高≥1536，实际 {img4.size}")
    lo4, hi4 = img4.convert("L").getextrema()
    check(hi4 - lo4 > 30, "暗色卡应有明暗层次")

    # 3.6) M5：推送卡冒烟
    p5 = card.render_push_card(
        "2026-09-27", "星期日", {"name": "新月", "text": "许愿的好时机"},
        festival_line="元旦快乐！", accent_hex="#A8D8EA",
        cards_root=Path(tempfile.mkdtemp(prefix="moe_card_")),
    )
    check(Image.open(p5).size == (1024, 620), "推送卡尺寸 1024x620")

    # 3.7) M8：塔罗双联（有 AI 牌面 → 1400x1200 横图；无图 → 单联 700x1200 不留空白）
    fake_side = Path(tempfile.mkdtemp(prefix="moe_card_")) / "ai.png"
    Image.new("RGB", (700, 1200), (40, 36, 80)).save(fake_side)
    r6 = dict(r)
    r6["tarot"] = {"name_cn": "星星", "name_en": "The Star",
                   "keywords": "希望 · 疗愈 · 星光", "reversed": False, "label": "正位"}
    p6 = card.render_card(r6, Path(tempfile.mkdtemp(prefix="moe_card_")),
                          width=700, height=1200, nickname="塔罗客", uid="6",
                          bg_image=str(fake_side))
    check(Image.open(p6).size == (1400, 1200), f"塔罗双联应 1400x1200，实际 {Image.open(p6).size}")
    p7 = card.render_card(r6, Path(tempfile.mkdtemp(prefix="moe_card_")),
                          width=700, height=1200, nickname="塔罗客", uid="6",
                          bg_image=None)
    _s7 = Image.open(p7).size
    check(_s7[0] == 700 and _s7[1] >= 1200, f"无图单联宽 700、高≥1200（自动加高），实际 {_s7}")

    # 4) 长签文换行：每行不超宽（允许单字超宽的容差）
    f40 = card._font(ff, 40)
    lines = card._wrap("星" * 120, f40, 800)
    check(len(lines) > 1, "长文本应换行")
    check(all(card.draw_len(l, f40) <= 840 for l in lines), "每行宽度应受限")

    # 5) 粗体变体：msyh 环境应命中 msyhbd
    bv = card._bold_variant(ff)
    check(Path(bv).is_file(), "粗体变体必须指向存在的字体文件")

    # 6) M9 星尘展示：单联/塔罗双联带 stardust 参数渲染冒烟（不炸即过）
    p8 = card.render_card(r, Path(tempfile.mkdtemp(prefix="moe_card_")),
                          nickname="攒星人", uid="8",
                          stardust_today=23, stardust_total=456)
    _s8 = Image.open(p8).size
    check(Path(p8).is_file() and _s8[0] == 1024 and _s8[1] >= 1536,
          f"单联星尘行渲染（宽 1024、高≥1536），实际 {_s8}")
    p9 = card.render_card(r6, Path(tempfile.mkdtemp(prefix="moe_card_")),
                          width=700, height=1200, nickname="塔罗客", uid="8",
                          bg_image=str(fake_side), stardust_today=23, stardust_total=456)
    check(Image.open(p9).size == (1400, 1200), "塔罗双联星尘块渲染")

    # 7) M9 提示卡六件套：落盘 + 可打开 + 非空白
    misc = Path(tempfile.mkdtemp(prefix="moe_card_"))
    pw = card.render_wallet_card("攒星人", 456, [("换签卡", 1), ("厄运护身符", 2),
                                                 ("连签保护卡", 0), ("幸运香烛", 3)],
                                 misc, file_key="t", uid="10086", today_gain=23,
                                 date_str="2026-09-27", accent_hex="#A8D8EA")
    check(Path(pw).is_file(), "钱包卡落盘")
    ps = card.render_shop_card("攒星人", [(n, 80 + i * 10, f"道具 {n} 的说明文字，测试换行宽度是否正常",
                                           i) for i, n in
                                          enumerate(("换签卡", "厄运护身符", "连签保护卡", "幸运香烛"))],
                               misc, file_key="t", uid="10086")
    check(Path(ps).is_file(), "商店卡落盘")
    pr = card.render_rank_card("今日星语榜", [(1, "甲", "95", ""), (2, "乙", "88", ""),
                                             (3, "丙", "80", ""), (4, "丁", "70", "")],
                               misc, file_key="t", date_str="2026-09-27")
    check(Path(pr).is_file(), "榜单卡落盘")
    pr0 = card.render_rank_card("今日星语榜", [], misc, file_key="empty")
    check(Path(pr0).is_file(), "空榜单卡（空状态）落盘")
    pp = card.render_pk_card("甲", 95, "乙", 88, "甲 胜！", "今天的星星偏向了你。",
                             misc, file_key="t", winner="left", accent_hex="#F0A0B8")
    check(Path(pp).is_file(), "PK 卡落盘")
    pn = card.render_notice_card("购买成功", ["换签卡 ×1", "花费 80 星尘，余额 20", "当前持有 ×2"],
                                 misc, file_key="t", footer="使用：/星语使用 <名称>")
    check(Path(pn).is_file(), "通知卡落盘")
    # 日历：2026-09（1 号周二，30 天，跨 5 周）；含已占卜/未占卜/未来/今日
    cal_days = {"2026-09-05": ("大吉", 92), "2026-09-14": ("凶", 33), "2026-09-27": ("吉", 77)}
    pc = card.render_calendar_card(2026, 9, cal_days, misc, file_key="t",
                                   today="2026-09-27", nickname="攒星人",
                                   accent_hex="#A8D8EA", stats={"drawn": 3, "daji": 1, "avg": 67, "stardust": 456})
    check(Path(pc).is_file(), "日历卡落盘")
    pc2 = card.render_calendar_card(2026, 2, {}, misc, file_key="t2",
                                    today="", nickname="攒星人", stats={"drawn": 0, "daji": 0, "avg": 0, "stardust": None})
    check(Image.open(pc2).size[0] == 1000, "平年二月（4 周）日历渲染")
    for p in (pw, ps, pr, pr0, pp, pn, pc, pc2):
        im = Image.open(p)
        im.load()
        lo_, hi_ = im.convert("L").getextrema()
        check(hi_ - lo_ > 30, f"提示卡应有明暗层次：{Path(p).name} {lo_}~{hi_}")

    if FAILED:
        print(f"\n{len(FAILED)} 项失败")
        return 1
    print("\ncard.py 全部通过")
    return 0


if __name__ == "__main__":
    sys.exit(main())
