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

    # 1) 默认尺寸落盘、可打开、非空白
    p1 = card.render_card(r, tmp, nickname="测试旅人", uid="10086")
    check(Path(p1).is_file(), "卡文件应落盘")
    img = Image.open(p1)
    img.load()
    check(img.size == (1024, 1536), f"默认尺寸 1024x1536，实际 {img.size}")
    lo, hi = img.convert("L").getextrema()
    check(hi - lo > 30, f"卡面应有明暗层次（extrema {lo}~{hi}）")

    # 2) 确定性：同输入两次渲染字节一致（不同目录避免同名覆盖）
    p2 = card.render_card(dict(r), Path(tempfile.mkdtemp(prefix="moe_card_")),
                          nickname="测试旅人", uid="10086")
    check(Path(p1).read_bytes() == Path(p2).read_bytes(), "同输入渲染必须字节一致")

    # 3) 小尺寸按 u 缩放
    p3 = card.render_card(r, Path(tempfile.mkdtemp(prefix="moe_card_")),
                          width=512, height=768, nickname="小", uid="2")
    check(Image.open(p3).size == (512, 768), "小尺寸应按比例渲染")

    # 3.5) M4：暗色主题 / 生日描边 / 星座角标 / grade_display 渲染冒烟
    r4 = dict(r)
    r4["birthday_today"] = True
    r4["grade_display"] = "大吉（？）"
    r4["constellation"] = "天秤座"
    p4 = card.render_card(r4, Path(tempfile.mkdtemp(prefix="moe_card_")),
                          theme="dark", nickname="夜旅人", uid="4")
    img4 = Image.open(p4)
    img4.load()
    check(img4.size == (1024, 1536), "暗色卡尺寸一致")
    lo4, hi4 = img4.convert("L").getextrema()
    check(hi4 - lo4 > 30, "暗色卡应有明暗层次")

    # 3.6) M5：推送卡冒烟
    p5 = card.render_push_card(
        "2026-09-27", "星期日", {"name": "新月", "text": "许愿的好时机"},
        festival_line="元旦快乐！", accent_hex="#A8D8EA",
        cards_root=Path(tempfile.mkdtemp(prefix="moe_card_")),
    )
    check(Image.open(p5).size == (1024, 620), "推送卡尺寸 1024x620")

    # 4) 长签文换行：每行不超宽（允许单字超宽的容差）
    f40 = card._font(ff, 40)
    lines = card._wrap("星" * 120, f40, 800)
    check(len(lines) > 1, "长文本应换行")
    check(all(card.draw_len(l, f40) <= 840 for l in lines), "每行宽度应受限")

    # 5) 粗体变体：msyh 环境应命中 msyhbd
    bv = card._bold_variant(ff)
    check(Path(bv).is_file(), "粗体变体必须指向存在的字体文件")

    if FAILED:
        print(f"\n{len(FAILED)} 项失败")
        return 1
    print("\ncard.py 全部通过")
    return 0


if __name__ == "__main__":
    sys.exit(main())
