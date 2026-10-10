# -*- coding: utf-8 -*-
"""农历 / 节气小工具：给卡片提供「农历几月几号 + 干支生肖 + 今日节气」。

**为什么不装第三方库**：农历与节气只是卡上的一两行小字，而 AstrBot 装插件时会执行
`requirements.txt`——装失败会直接让插件装载失败（`PluginDependencyInstallError`）。
为了两行小字去冒插件装不上的风险不划算，所以这里自带数据与算法：

- **农历**：1900-2100 年的月长/闰月压缩表（每项 17 位：低 4 位是闰月号，0=无闰月；
  第 4-15 位依次是正月到腊月是否大月（30 天）；第 16 位是闰月是否大月）。
  基准 `_BASE_DATE` = 1900-01-31（农历 1900 年正月初一），换算按经典逐月扣减。
- **节气**：通用「寿星公式」（`[Y×0.2422+C]-L`，20/21 世纪各 24 个 C 值），
  再叠一张 36 条例外修正表——公式本身在 1900-2100 的 4824 个节气里只有这 36 处
  差 ±1 天，全部列出来就与权威实现逐日一致。

两份数据都不是手抄的：农历表由 `lunar_python` 的 `LunarYear` 逐月长度生成，节气例外表
由「公式结果 vs `lunar_python` 的 `getJieQi()`」逐年比对导出（生成脚本见 CHANGELOG
v1.10.17 的说明），`tests/test_lunar.py` 用独立基准锁住若干已知日期。改这张表之前请先读
那份测试：农历/节气错一天在卡上看不出来，只有测试能发现。

超出 1900-2100 的日期一律返回空结果（调用方按「没有农历行」处理），不猜。
"""
from datetime import date, datetime, timedelta

# 常见农历日名（初一…三十）
_DAY_NAMES = (
    "初一", "初二", "初三", "初四", "初五", "初六", "初七", "初八", "初九", "初十",
    "十一", "十二", "十三", "十四", "十五", "十六", "十七", "十八", "十九", "二十",
    "廿一", "廿二", "廿三", "廿四", "廿五", "廿六", "廿七", "廿八", "廿九", "三十",
)
_MONTH_NAMES = ("正月", "二月", "三月", "四月", "五月", "六月",
                "七月", "八月", "九月", "十月", "冬月", "腊月")
_GAN = "甲乙丙丁戊己庚辛壬癸"
_ZHI = "子丑寅卯辰巳午未申酉戌亥"
_ZODIAC = "鼠牛虎兔龙蛇马羊猴鸡狗猪"

# 农历 1900 年正月初一 = 1900-01-31
_BASE_DATE = date(1900, 1, 31)

_LUNAR_INFO = {
    1900: 0x0bd28, 1901: 0x07520, 1902: 0x0ea50, 1903: 0x0b2a5, 1904: 0x064b0, 1905: 0x0a9b0, 1906: 0x1aa64, 1907: 0x056a0,
    1908: 0x0b590, 1909: 0x0baa2, 1910: 0x07520, 1911: 0x0da56, 1912: 0x0b250, 1913: 0x0a4b0, 1914: 0x1a4b5, 1915: 0x02ad0,
    1916: 0x056b0, 1917: 0x05b52, 1918: 0x0da90, 1919: 0x1e927, 1920: 0x0e920, 1921: 0x0d250, 1922: 0x0d2d5, 1923: 0x0a560,
    1924: 0x02b60, 1925: 0x1ad54, 1926: 0x06d40, 1927: 0x0ea90, 1928: 0x0f4a2, 1929: 0x0e920, 1930: 0x06a66, 1931: 0x052b0,
    1932: 0x0a570, 1933: 0x19565, 1934: 0x0b5a0, 1935: 0x06d40, 1936: 0x17613, 1937: 0x07490, 1938: 0x1b137, 1939: 0x0a930,
    1940: 0x052b0, 1941: 0x151b6, 1942: 0x0aad0, 1943: 0x056a0, 1944: 0x1da54, 1945: 0x0ba40, 1946: 0x0b490, 1947: 0x0d4b2,
    1948: 0x0a950, 1949: 0x0aad7, 1950: 0x05360, 1951: 0x0aad0, 1952: 0x1aca5, 1953: 0x05b20, 1954: 0x0da50, 1955: 0x1ea23,
    1956: 0x0d4a0, 1957: 0x05958, 1958: 0x0a970, 1959: 0x05560, 1960: 0x05756, 1961: 0x0ad50, 1962: 0x06d20, 1963: 0x07554,
    1964: 0x0ea50, 1965: 0x064a0, 1966: 0x064f3, 1967: 0x0a9b0, 1968: 0x0ada7, 1969: 0x056a0, 1970: 0x0b690, 1971: 0x0bb25,
    1972: 0x0b520, 1973: 0x0b250, 1974: 0x0b2b4, 1975: 0x0a4b0, 1976: 0x0aab8, 1977: 0x02ad0, 1978: 0x056d0, 1979: 0x15a96,
    1980: 0x0da90, 1981: 0x0d920, 1982: 0x0e954, 1983: 0x0d250, 1984: 0x0e4da, 1985: 0x0a560, 1986: 0x02b60, 1987: 0x02f56,
    1988: 0x06d50, 1989: 0x0ea90, 1990: 0x0f525, 1991: 0x0e920, 1992: 0x0d260, 1993: 0x052e3, 1994: 0x0a570, 1995: 0x0ad68,
    1996: 0x035a0, 1997: 0x06d50, 1998: 0x0b695, 1999: 0x07490, 2000: 0x06930, 2001: 0x0a9b4, 2002: 0x052b0, 2003: 0x0a5b0,
    2004: 0x0aae2, 2005: 0x056a0, 2006: 0x0dd57, 2007: 0x0ba40, 2008: 0x0b490, 2009: 0x0d535, 2010: 0x0a950, 2011: 0x052d0,
    2012: 0x055d4, 2013: 0x0ab50, 2014: 0x0baa9, 2015: 0x05d20, 2016: 0x0da50, 2017: 0x1e8a6, 2018: 0x0d4a0, 2019: 0x0c950,
    2020: 0x0a9e4, 2021: 0x05560, 2022: 0x0ab50, 2023: 0x0ada2, 2024: 0x06d20, 2025: 0x07656, 2026: 0x07250, 2027: 0x064b0,
    2028: 0x06575, 2029: 0x0cab0, 2030: 0x055a0, 2031: 0x056e3, 2032: 0x0b690, 2033: 0x0f52b, 2034: 0x0b520, 2035: 0x0b250,
    2036: 0x1d0b6, 2037: 0x0a4b0, 2038: 0x04ab0, 2039: 0x02bb5, 2040: 0x05ad0, 2041: 0x0b6a0, 2042: 0x0daa2, 2043: 0x0d920,
    2044: 0x0ea57, 2045: 0x0d250, 2046: 0x0a550, 2047: 0x1a4d5, 2048: 0x04b60, 2049: 0x05b50, 2050: 0x16d23, 2051: 0x0ec90,
    2052: 0x0f928, 2053: 0x0e920, 2054: 0x0d260, 2055: 0x15166, 2056: 0x0a570, 2057: 0x04d60, 2058: 0x13654, 2059: 0x07550,
    2060: 0x07490, 2061: 0x074b3, 2062: 0x06930, 2063: 0x0aab7, 2064: 0x052b0, 2065: 0x0a5b0, 2066: 0x0aba5, 2067: 0x056a0,
    2068: 0x0b650, 2069: 0x0baa4, 2070: 0x0b4a0, 2071: 0x0d958, 2072: 0x0a950, 2073: 0x052d0, 2074: 0x056d6, 2075: 0x0ab50,
    2076: 0x05aa0, 2077: 0x05d54, 2078: 0x0da50, 2079: 0x0d4a0, 2080: 0x0e4d3, 2081: 0x0c960, 2082: 0x0cce7, 2083: 0x05560,
    2084: 0x0ab50, 2085: 0x1ad25, 2086: 0x06d20, 2087: 0x0ea50, 2088: 0x072a4, 2089: 0x068b0, 2090: 0x06978, 2091: 0x04ab0,
    2092: 0x055b0, 2093: 0x15566, 2094: 0x0b6a0, 2095: 0x07520, 2096: 0x0b954, 2097: 0x0b450, 2098: 0x0a8b0, 2099: 0x0a4f2,
    2100: 0x04ab0,
}

# 24 节气（按公历月的顺序：小寒/大寒在 1 月，立春/雨水在 2 月 …… 大雪/冬至在 12 月）
JIEQI_NAMES = (
    "小寒", "大寒", "立春", "雨水", "惊蛰", "春分", "清明", "谷雨",
    "立夏", "小满", "芒种", "夏至", "小暑", "大暑", "立秋", "处暑",
    "白露", "秋分", "寒露", "霜降", "立冬", "小雪", "大雪", "冬至",
)
_C20 = (
    6.11, 20.84, 4.6295, 19.4599, 6.3826, 21.4155, 5.59, 20.888, 6.318,
    21.86, 6.5, 22.2, 7.928, 23.65, 8.35, 23.95, 8.44, 23.822, 9.098,
    24.218, 8.218, 23.08, 7.9, 22.6,
)
_C21 = (
    5.4055, 20.12, 3.87, 18.73, 5.63, 20.646, 4.81, 20.1, 5.52, 21.04,
    5.678, 21.37, 7.108, 22.83, 7.5, 23.13, 7.646, 23.042, 8.318, 23.438,
    7.438, 22.36, 7.18, 21.94,
)
# 寿星公式的例外修正：(年, 节气下标) -> 天数修正
_JQ_FIX = {
    (1902, 10): +1, (1911, 8): +1, (1914, 2): -1, (1914, 23): +1, (1915, 4): -1, (1922, 13): +1,
    (1923, 3): -1, (1925, 12): +1, (1927, 16): +1, (1928, 11): +1, (1942, 17): +1, (1947, 2): -1,
    (1947, 23): +1, (1948, 4): -1, (1951, 23): +1, (1978, 21): +1, (1980, 23): +1, (1982, 0): +1,
    (1984, 23): +1, (2000, 0): +1, (2000, 1): +1, (2000, 2): +1, (2000, 3): +1, (2002, 14): +1,
    (2008, 9): +1, (2016, 12): +1, (2019, 0): -1, (2021, 23): -1, (2026, 3): -1, (2082, 1): +1,
    (2089, 19): +1, (2089, 20): +1, (2100, 2): +1, (2100, 6): +1, (2100, 13): +1, (2100, 23): +1,
}


def _leap_month(bits: int) -> int:
    """该农历年的闰月号（0 = 无闰月）。"""
    return bits & 0xF


def _month_days(bits: int, month: int) -> int:
    # 第 4-15 位 = 正月..腊月（bit 4 对应正月），低 4 位是闰月号，别搞混
    return 30 if bits & (1 << (month + 3)) else 29


def _leap_days(bits: int) -> int:
    return 30 if bits & 0x10000 else 29


def _year_days(bits: int) -> int:
    total = sum(_month_days(bits, m) for m in range(1, 13))
    if _leap_month(bits):
        total += _leap_days(bits)
    return total


def solar_to_lunar(year: int, month: int, day: int):
    """公历 -> 农历：(农历年, 月, 日, 是否闰月)；超出 1900-2100 返回 None。"""
    try:
        target = date(int(year), int(month), int(day))
    except ValueError:
        return None
    offset = (target - _BASE_DATE).days
    if offset < 0:
        return None
    lunar_year = 1900
    while True:
        bits = _LUNAR_INFO.get(lunar_year)
        if bits is None:
            return None
        days = _year_days(bits)
        if offset < days:
            break
        offset -= days
        lunar_year += 1
    leap = _leap_month(bits)
    for m in range(1, 13):
        d = _month_days(bits, m)
        if offset < d:
            return lunar_year, m, offset + 1, False
        offset -= d
        if m == leap:
            d = _leap_days(bits)
            if offset < d:
                return lunar_year, m, offset + 1, True
            offset -= d
    return None     # 理论上到不了这里


def lunar_month_name(month: int, is_leap: bool = False) -> str:
    name = _MONTH_NAMES[month - 1] if 1 <= month <= 12 else f"{month}月"
    return f"闰{name}" if is_leap else name


def lunar_day_name(day: int) -> str:
    return _DAY_NAMES[day - 1] if 1 <= day <= 30 else str(day)


def ganzhi_of(lunar_year: int) -> str:
    """农历年的干支（如「丙午」）。"""
    y = int(lunar_year)
    return _GAN[(y - 4) % 10] + _ZHI[(y - 4) % 12]


def zodiac_of(lunar_year: int) -> str:
    """农历年的生肖（如「马」）。"""
    return _ZODIAC[(int(lunar_year) - 4) % 12]


def _jieqi_day(year: int, idx: int) -> int:
    y = year % 100
    c = _C21[idx] if year >= 2000 else _C20[idx]
    leap = int((y - 1) / 4) if idx < 4 else int(y / 4)
    return int(y * 0.2422 + c) - leap + _JQ_FIX.get((year, idx), 0)


def jieqi_of(year: int, month: int, day: int) -> str:
    """当天是节气就返回节气名，否则空串（超出 1900-2100 返回空串）。"""
    year, month, day = int(year), int(month), int(day)
    if not (1900 <= year <= 2100) or not (1 <= month <= 12):
        return ""
    for idx in (2 * (month - 1), 2 * (month - 1) + 1):
        if _jieqi_day(year, idx) == day:
            return JIEQI_NAMES[idx]
    return ""


def describe(date_str: str) -> dict:
    """卡片要用的历法信息（失败/超范围返回空 dict，调用方按「没有就少一行」处理）。

    返回键：
      lunar_text  农历月日（含闰月标注），如「八月十九」「闰六月初三」
      ganzhi_text 干支 + 生肖年，如「丙午马年」
      lunar_key   农历「月-日」键（用于查农历节日），如「8-15」
      jieqi       当天节气名（不是节气则为空串）
      chuxi       当天是否除夕（腊月最后一天，即次日为正月初一）
    """
    try:
        d = datetime.strptime(str(date_str), "%Y-%m-%d").date()
    except (TypeError, ValueError):
        return {}
    got = solar_to_lunar(d.year, d.month, d.day)
    if got is None:
        return {}
    lunar_year, m, day, is_leap = got
    out = {
        "lunar_text": lunar_month_name(m, is_leap) + lunar_day_name(day),
        "ganzhi_text": ganzhi_of(lunar_year) + zodiac_of(lunar_year) + "年",
        # 闰月不算节日（闰五月初五不是端午）
        "lunar_key": "" if is_leap else f"{m}-{day}",
        "jieqi": jieqi_of(d.year, d.month, d.day),
        "chuxi": False,
    }
    nxt = solar_to_lunar(d.year, d.month, d.day + 1) if d.day < 28 else None
    if nxt is None:      # 跨月/跨年的边界：直接算次日
        nd = d + timedelta(days=1)
        nxt = solar_to_lunar(nd.year, nd.month, nd.day)
    if nxt is not None and not is_leap and m == 12 and nxt[1] == 1 and nxt[2] == 1:
        out["chuxi"] = True
        out["lunar_key"] = "chuxi"
    return out
