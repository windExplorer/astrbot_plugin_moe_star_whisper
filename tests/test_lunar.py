# -*- coding: utf-8 -*-
"""lunar.py 自检：农历/节气必须与权威基准逐项一致（退出码即结论）。

基准数据从 `lunar_python` 导出（脚本见 `tests/_tools/lunar_oracle.py`，可选依赖，
不进插件运行时）。为什么要硬编码这些「春节 / 节气」日期而不是随机抽查：
农历表错一天在卡上完全看不出来，而**春节日期是全年长度的直接函数**——只要某年的
某个月大小月判错，那年的春节就会偏一天，这张表就能立刻抓住它（第一版正是这样错的：
闰月长度被并进前一个月，整表从此错位）。

    uv run --no-project python tests/test_lunar.py
"""
import datetime
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import lunar  # noqa: E402

FAILED = []


def check(cond, msg):
    if not cond:
        FAILED.append(msg)
        print(f"FAIL: {msg}")


# 春节（农历正月初一）公历日期：1900-2100 每 3 年 + 2020-2035 每年（含 2100）
CHUNJIE = (
    (1900, "1900-01-31"), (1903, "1903-01-29"), (1906, "1906-01-25"), (1909, "1909-01-22"),
    (1912, "1912-02-18"), (1915, "1915-02-14"), (1918, "1918-02-11"), (1921, "1921-02-08"),
    (1924, "1924-02-05"), (1927, "1927-02-02"), (1930, "1930-01-30"), (1933, "1933-01-26"),
    (1936, "1936-01-24"), (1939, "1939-02-19"), (1942, "1942-02-15"), (1945, "1945-02-13"),
    (1948, "1948-02-10"), (1951, "1951-02-06"), (1954, "1954-02-03"), (1957, "1957-01-31"),
    (1960, "1960-01-28"), (1963, "1963-01-25"), (1966, "1966-01-21"), (1969, "1969-02-17"),
    (1972, "1972-02-15"), (1975, "1975-02-11"), (1978, "1978-02-07"), (1981, "1981-02-05"),
    (1984, "1984-02-02"), (1987, "1987-01-29"), (1990, "1990-01-27"), (1993, "1993-01-23"),
    (1996, "1996-02-19"), (1999, "1999-02-16"), (2002, "2002-02-12"), (2005, "2005-02-09"),
    (2008, "2008-02-07"), (2011, "2011-02-03"), (2014, "2014-01-31"), (2017, "2017-01-28"),
    (2020, "2020-01-25"), (2021, "2021-02-12"), (2022, "2022-02-01"), (2023, "2023-01-22"),
    (2024, "2024-02-10"), (2025, "2025-01-29"), (2026, "2026-02-17"), (2027, "2027-02-06"),
    (2028, "2028-01-26"), (2029, "2029-02-13"), (2030, "2030-02-03"), (2031, "2031-01-23"),
    (2032, "2032-02-11"), (2033, "2033-01-31"), (2034, "2034-02-19"), (2035, "2035-02-08"),
    (2038, "2038-02-04"), (2041, "2041-02-01"), (2044, "2044-01-30"), (2047, "2047-01-26"),
    (2050, "2050-01-23"), (2053, "2053-02-19"), (2056, "2056-02-15"), (2059, "2059-02-12"),
    (2062, "2062-02-09"), (2065, "2065-02-05"), (2068, "2068-02-03"), (2071, "2071-01-31"),
    (2074, "2074-01-27"), (2077, "2077-01-24"), (2080, "2080-01-22"), (2083, "2083-02-17"),
    (2086, "2086-02-14"), (2089, "2089-02-10"), (2092, "2092-02-07"), (2095, "2095-02-05"),
    (2098, "2098-02-01"), (2100, "2100-02-09"),
)

# 2026 年 24 个节气（公历日期）
JIEQI_2026 = (
    ("2026-01-05", "小寒"), ("2026-01-20", "大寒"), ("2026-02-04", "立春"),
    ("2026-02-18", "雨水"), ("2026-03-05", "惊蛰"), ("2026-03-20", "春分"),
    ("2026-04-05", "清明"), ("2026-04-20", "谷雨"), ("2026-05-05", "立夏"),
    ("2026-05-21", "小满"), ("2026-06-05", "芒种"), ("2026-06-21", "夏至"),
    ("2026-07-07", "小暑"), ("2026-07-23", "大暑"), ("2026-08-07", "立秋"),
    ("2026-08-23", "处暑"), ("2026-09-07", "白露"), ("2026-09-23", "秋分"),
    ("2026-10-08", "寒露"), ("2026-10-23", "霜降"), ("2026-11-07", "立冬"),
    ("2026-11-22", "小雪"), ("2026-12-07", "大雪"), ("2026-12-22", "冬至"),
)

# 除夕（农历腊月最后一天）
CHUXI = ("2020-01-24", "2021-02-11", "2022-01-31", "2023-01-21", "2024-02-09",
         "2025-01-28", "2026-02-16", "2027-02-05", "2028-01-25", "2029-02-12",
         "2030-02-02")

# 农历样例（含闰月与争议日）
LUNAR_SAMPLES = (
    ("1900-01-31", 1, 1, False),
    ("1900-09-23", 8, 30, False),
    ("1900-09-24", 8, 1, True),      # 1900 闰八月
    ("1933-07-22", 5, 30, True),     # 1933 闰五月（lunardate 这天算错，以 lunar_python 为准）
    ("1954-12-24", 11, 30, False),
    ("1978-10-01", 8, 29, False),
    ("2023-03-22", 2, 1, True),      # 2023 闰二月
    ("2025-07-25", 6, 1, True),      # 2025 闰六月
    ("2026-02-16", 12, 29, False),
    ("2026-02-17", 1, 1, False),
    ("2026-09-25", 8, 15, False),    # 2026 中秋
    ("2026-10-08", 8, 28, False),
    ("2026-10-10", 9, 1, False),
    ("2100-12-31", 12, 1, False),    # 表尾仍要能算
)


def _d(date_str: str) -> datetime.date:
    return datetime.datetime.strptime(date_str, "%Y-%m-%d").date()


def main() -> int:
    # 1) 结构：201 年压缩表、取值落在 17 位内（多一位就说明打包写错）
    check(len(lunar._LUNAR_INFO) == 201, f"农历表应 201 项，实际 {len(lunar._LUNAR_INFO)}")
    check(all(0 < v < (1 << 17) for v in lunar._LUNAR_INFO.values()),
          "农历表每项必须是 17 位内的正整数")
    check(lunar._BASE_DATE == datetime.date(1900, 1, 31), "基准日应为 1900-01-31（正月初一）")

    # 2) 农历样例逐项（只比月/日/闰，不比农历年——腊月廿九已跨到下一个公历年）
    for date_str, m, day, leap in LUNAR_SAMPLES:
        d = _d(date_str)
        got = lunar.solar_to_lunar(d.year, d.month, d.day)
        check(got is not None and got[1:] == (m, day, leap),
              f"{date_str} 应为农历 {m}-{day}{'(闰)' if leap else ''}，实际 {got}")

    # 3) 春节：那一天必须是正月初一，前一天必须是腊月（除夕）
    for year, date_str in CHUNJIE:
        d = _d(date_str)
        got = lunar.solar_to_lunar(d.year, d.month, d.day)
        check(got is not None and got[1] == 1 and got[2] == 1 and not got[3],
              f"{year} 春节 {date_str} 应为正月初一，实际 {got}")
        if d == lunar._BASE_DATE:
            continue        # 1900-01-31 的前一天在表外（1899 腊月），不检查
        p = d - datetime.timedelta(days=1)
        prev = lunar.solar_to_lunar(p.year, p.month, p.day)
        check(prev is not None and prev[1] == 12 and not prev[3] and prev[2] >= 29,
              f"{date_str} 前一天应为腊月末（29/30），实际 {prev}")

    # 4) 节气：2026 全年逐个对；非节气日必须为空
    jq_days = {date_str: name for date_str, name in JIEQI_2026}
    for date_str, name in JIEQI_2026:
        d = _d(date_str)
        check(lunar.jieqi_of(d.year, d.month, d.day) == name,
              f"{date_str} 应为 {name}，实际 {lunar.jieqi_of(d.year, d.month, d.day)!r}")
    d = datetime.date(2026, 1, 1)
    while d.year == 2026:
        key = d.strftime("%Y-%m-%d")
        if key not in jq_days:
            check(lunar.jieqi_of(d.year, d.month, d.day) == "",
                  f"{key} 不是节气却返回了 {lunar.jieqi_of(d.year, d.month, d.day)!r}")
        d += datetime.timedelta(days=1)

    # 5) describe：卡片直接用的字段
    info = lunar.describe("2026-10-10")
    check(info.get("lunar_text") == "九月初一", f"农历文案错：{info}")
    check(info.get("ganzhi_text") == "丙午马年", f"干支生肖错：{info}")
    check(info.get("lunar_key") == "9-1", f"农历节日键错：{info}")
    check(info.get("jieqi") == "", "2026-10-10 不是节气")
    check(lunar.describe("2026-10-08").get("jieqi") == "寒露", "节气名要能被 describe 带出")
    check(lunar.describe("2026-09-25").get("lunar_key") == "8-15", "中秋的农历键应为 8-15")
    check(lunar.describe("2025-07-25").get("lunar_key") == "",
          "闰月不算节日（闰六月初一不是节日），lunar_key 必须为空串")
    check(lunar.describe("2025-07-25").get("lunar_text") == "闰六月初一",
          f"闰月文案要带「闰」：{lunar.describe('2025-07-25')}")
    for date_str in CHUXI:
        check(lunar.describe(date_str).get("chuxi") is True, f"{date_str} 应识别为除夕")
        check(lunar.describe(date_str).get("lunar_key") == "chuxi",
              f"{date_str} 除夕的 lunar_key 应为 chuxi")
    check(lunar.describe("2026-02-17").get("chuxi") is False, "正月初一不是除夕")

    # 6) 边界：超出 1900-2100 一律空结果（调用方按「没有这行」处理），不抛错
    check(lunar.describe("1899-12-31") == {}, "1900 之前应返回空 dict")
    check(lunar.describe("2101-06-01") == {}, "2100 之后应返回空 dict")
    check(lunar.describe("") == {} and lunar.describe("不是日期") == {},
          "脏输入应返回空 dict 而不是抛错")
    check(lunar.jieqi_of(2200, 1, 5) == "", "超出范围的节气查询应返回空串")

    # 7) 逐日连续性（7 万天）：每个农历月都必须是 29/30 天，且不出现空档
    d = lunar._BASE_DATE
    end = datetime.date(2100, 12, 31)
    first_days = []
    while d <= end:
        got = lunar.solar_to_lunar(d.year, d.month, d.day)
        if got is None:
            check(False, f"{d} 落在支持范围内却算不出来")
            break
        _y, _m, day, _leap = got
        if day == 1:
            first_days.append(d)
        d += datetime.timedelta(days=1)
    gaps = {(b - a).days for a, b in zip(first_days, first_days[1:])}
    check(gaps <= {29, 30}, f"农历月长必须都是 29/30 天，实际出现 {sorted(gaps)}")
    check(len(first_days) > 2400, f"7 万天里应有 2400+ 个月首，实际 {len(first_days)}")

    # 8) 零依赖守卫：lunar.py 只能 import 标准库（这是「不装第三方库」这条决定的落点；
    #    注释里提到 lunar_python（说明数据来源）是允许的，所以只查 import 语句）
    src = (ROOT / "lunar.py").read_text(encoding="utf-8")
    imports = [ln.strip() for ln in src.splitlines()
               if ln.strip().startswith(("import ", "from "))]
    check(imports == ["from datetime import date, datetime, timedelta"],
          f"lunar.py 只应 import 标准库，实际 {imports}")

    if FAILED:
        print(f"\n{len(FAILED)} 项失败")
        return 1
    print("\nlunar.py 全部通过（春节 79 项 / 节气 24 项 / 农历样例 14 项 / 7 万天连续性）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
