# -*- coding: utf-8 -*-
"""农历表 / 节气例外表的「来源与校验」脚本（可选依赖，不进插件包、不进默认测试）。

背景：`lunar.py` 自带一份 1900-2100 的农历压缩表与 36 条节气例外修正，两份数据都不是
手抄的，而是从这个脚本用 `lunar_python` 推导出来的——怕的正是「看着像对、其实整体偏一天」
（第一版就翻过这个坑：闰月长度被并进前一个月，全表从此错位，卡上完全看不出来）。

用法（本机 uv 可直接拉起临时环境，不污染插件仓库）：

    # 校验：把 lunar.py 与 lunar_python 在 1900-01-31 ~ 2100-12-31 逐日比对（退出码即结论）
    uv run --no-project --python 3.12 --with lunar_python python tests/_tools/lunar_oracle.py

    # 重新生成：按 lunar_python 重算农历表与节气例外表，直接覆盖 lunar.py（危险，先 git diff）
    uv run --no-project --python 3.12 --with lunar_python python tests/_tools/lunar_oracle.py --emit

`lunar_python` 是**校验用**依赖，插件运行时不依赖它（原因见 lunar.py 开头）。
"""
import argparse
import datetime
import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))

JQ = ["小寒", "大寒", "立春", "雨水", "惊蛰", "春分", "清明", "谷雨",
      "立夏", "小满", "芒种", "夏至", "小暑", "大暑", "立秋", "处暑",
      "白露", "秋分", "寒露", "霜降", "立冬", "小雪", "大雪", "冬至"]
C20 = (6.11, 20.84, 4.6295, 19.4599, 6.3826, 21.4155, 5.59, 20.888, 6.318,
       21.86, 6.5, 22.2, 7.928, 23.65, 8.35, 23.95, 8.44, 23.822, 9.098,
       24.218, 8.218, 23.08, 7.9, 22.6)
C21 = (5.4055, 20.12, 3.87, 18.73, 5.63, 20.646, 4.81, 20.1, 5.52, 21.04,
       5.678, 21.37, 7.108, 22.83, 7.5, 23.13, 7.646, 23.042, 8.318, 23.438,
       7.438, 22.36, 7.18, 21.94)
BASE = datetime.date(1900, 1, 31)


def _formula(year: int, idx: int) -> int:
    y = year % 100
    c = C21[idx] if year >= 2000 else C20[idx]
    leap = int((y - 1) / 4) if idx < 4 else int(y / 4)
    return int(y * 0.2422 + c) - leap


def _first(lunar, y: int, m: int) -> datetime.date:
    s = lunar.fromYmd(y, m, 1).getSolar()
    return datetime.date(s.getYear(), s.getMonth(), s.getDay())


def build_table(lunar, lunar_year_cls):
    """生成 1900-2100 的压缩农历表：低 4 位闰月号，第 4-15 位各月大小，第 16 位闰月大小。"""
    out = {}
    for y in range(1900, 2101):
        lm = lunar_year_cls.fromYear(y).getLeapMonth()
        seq = []
        for i in range(1, 13):
            seq.append((i, False))
            if i == lm:
                seq.append((i, True))
        starts = [_first(lunar, y, (-m if leap else m)) for m, leap in seq]
        nxt = lunar.fromYmd(y + 1, 1, 1).getSolar()
        starts.append(datetime.date(nxt.getYear(), nxt.getMonth(), nxt.getDay()))
        bits = lm & 0xF
        for idx, (m, leap) in enumerate(seq):
            if (starts[idx + 1] - starts[idx]).days == 30:
                bits |= (1 << 16) if leap else (1 << (m + 3))
        out[y] = bits
    return out


def build_fix(solar):
    """导出「寿星公式 vs lunar_python」的例外修正：{(年, 节气下标): ±1}。"""
    truth = {}
    for year in range(1900, 2101):
        d = datetime.date(year, 1, 1)
        while d.year == year:
            jq = solar.fromYmd(d.year, d.month, d.day).getLunar().getJieQi()
            if jq:
                truth[(year, jq)] = d.day
            d += datetime.timedelta(days=1)
    fix = {}
    for year in range(1900, 2101):
        for idx, name in enumerate(JQ):
            want = truth.get((year, name))
            if want is not None and _formula(year, idx) != want:
                fix[(year, idx)] = want - _formula(year, idx)
    return fix, len(truth)


def main() -> int:
    import lunar_python
    from lunar_python import Lunar, LunarYear, Solar

    ap = argparse.ArgumentParser(description="农历/节气数据校验与再生成")
    ap.add_argument("--emit", action="store_true", help="用 lunar_python 重算并覆盖 lunar.py")
    args = ap.parse_args()

    table = build_table(Lunar, LunarYear)
    fix, _n_jq = build_fix(Solar)

    if args.emit:
        src = (REPO / "lunar.py").read_text(encoding="utf-8")
        rows = sorted(table.items())
        block = []
        for i in range(0, len(rows), 8):
            block.append("    " + " ".join(f"{y}: 0x{v:05x}," for y, v in rows[i:i + 8]))
        fix_items = [f"({y}, {i}): {d:+d}" for (y, i), d in sorted(fix.items())]
        fix_block = []
        for i in range(0, len(fix_items), 6):
            fix_block.append("    " + ", ".join(fix_items[i:i + 6]) + ",")
        src = re.sub(r"_LUNAR_INFO = \{.*?\n\}",
                     "_LUNAR_INFO = {\n" + "\n".join(block) + "\n}", src, flags=re.S, count=1)
        src = re.sub(r"_JQ_FIX = \{.*?\n\}",
                     "_JQ_FIX = {\n" + "\n".join(fix_block) + "\n}", src, flags=re.S, count=1)
        (REPO / "lunar.py").write_text(src, encoding="utf-8")
        print(f"已重写 lunar.py：农历表 {len(table)} 项、节气例外 {len(fix)} 条")
        return 0

    # 校验：逐日比对
    import lunar as plugin_lunar
    bad_lunar = bad_jq = bad_gz = 0
    sample = []
    d = BASE
    end = datetime.date(2100, 12, 31)
    n = 0
    while d <= end:
        n += 1
        got = plugin_lunar.solar_to_lunar(d.year, d.month, d.day)
        l = Solar.fromYmd(d.year, d.month, d.day).getLunar()
        want = (l.getYear(), abs(l.getMonth()), l.getDay(), l.getMonth() < 0)
        if got != want:
            bad_lunar += 1
            if len(sample) < 5:
                sample.append(f"农历 {d}: 本插件 {got} / lunar_python {want}")
        if plugin_lunar.jieqi_of(d.year, d.month, d.day) != l.getJieQi():
            bad_jq += 1
            if len(sample) < 5:
                sample.append(f"节气 {d}")
        if plugin_lunar.ganzhi_of(l.getYear()) != l.getYearInGanZhi() or \
                plugin_lunar.zodiac_of(l.getYear()) != l.getYearShengXiao():
            bad_gz += 1
        d += datetime.timedelta(days=1)

    print(f"对比 {n} 天（{BASE} ~ {end}）：农历 {bad_lunar} / 节气 {bad_jq} / 干支生肖 {bad_gz} 处不一致")
    for line in sample:
        print("  " + line)
    ok = not (bad_lunar or bad_jq or bad_gz)
    print("结论：" + ("lunar.py 与 lunar_python 完全一致" if ok else "存在不一致，见上"))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
