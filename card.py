# -*- coding: utf-8 -*-
"""萌萌星语 · Pillow 图卡渲染（纯 Pillow，无 astrbot 依赖，可独立测试）。

卡面信息层级（PRD §7.3 / D9/D10，自上而下）：
  ①身份头（头像+昵称+QQ号+日期） ②吉凶大字 ③签文话语区 ④六维星数
  ⑤幸运指数 ⑥宜忌 ⑦幸运物/色/数字/方位 + 月相 + 落款。
底图：默认幸运色渐变；M6 起 anima 出图透传 bg_image（尺寸由调用方对齐，_cover 仅兜底）。
字体不打包：显式路径 → extra_dirs → 系统候选；找不到直接抛错由调用方回退纯文本。
"""
from __future__ import annotations

import io
import urllib.request
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

# 常见 CJK 字体候选（按优先级；Windows 在前，Linux Noto/文泉驿在后）
_SYSTEM_FONT_CANDIDATES = [
    "C:/Windows/Fonts/msyh.ttc",
    "C:/Windows/Fonts/msyhbd.ttc",
    "C:/Windows/Fonts/simhei.ttf",
    "C:/Windows/Fonts/simsun.ttc",
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
    "/usr/share/fonts/opentype/noto/NotoSansCJKsc-Regular.otf",
    "/usr/share/fonts/noto-cjk/NotoSansCJK-Regular.ttc",
    "/usr/share/fonts/truetype/wqy/wqy-microhei.ttc",
]

_font_cache: dict = {}


def find_font(explicit: str | None = None, extra_dirs=None) -> str | None:
    """多级查找：显式路径 → extra_dirs 下的 ttf/ttc/otf → 系统候选。找不到返回 None。"""
    candidates: list = []
    if explicit:
        candidates.append(explicit)
    for d in extra_dirs or []:
        p = Path(d)
        if p.is_dir():
            for pat in ("*.ttf", "*.otf", "*.ttc"):
                candidates += [str(x) for x in sorted(p.glob(pat))]
    candidates += _SYSTEM_FONT_CANDIDATES
    for c in candidates:
        if c and Path(c).is_file():
            return c
    return None


def _bold_variant(font_file: str) -> str:
    """同目录粗体变体（msyh.ttc→msyhbd.ttc、*Regular*→*Bold*）；没有就退回原字体。"""
    p = Path(font_file)
    for a, b in (("msyh.ttc", "msyhbd.ttc"), ("msyh.ttf", "msyhbd.ttc"), ("Regular", "Bold")):
        if a in p.name:
            cand = p.with_name(p.name.replace(a, b))
            if cand.is_file():
                return str(cand)
    return font_file


def _font(font_file: str, size: float) -> ImageFont.FreeTypeFont:
    key = (font_file, int(size))
    if key not in _font_cache:
        _font_cache[key] = ImageFont.truetype(font_file, int(size))
    return _font_cache[key]


def _hex_rgb(hex_color: str) -> tuple:
    h = str(hex_color).lstrip("#")
    if len(h) != 6:
        return (246, 198, 211)
    try:
        return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))
    except ValueError:
        return (246, 198, 211)


def _mix(c1: tuple, c2: tuple, t: float) -> tuple:
    return tuple(round(a + (b - a) * t) for a, b in zip(c1, c2))


def _wrap(text: str, font: ImageFont.FreeTypeFont, max_width: int) -> list[str]:
    """按像素宽度贪心换行（中文逐字、英文按字符，够用）。"""
    lines, buf = [], ""
    for ch in text:
        if ch == "\n":
            lines.append(buf)
            buf = ""
            continue
        if draw_len(buf + ch, font) <= max_width or not buf:
            buf += ch
        else:
            lines.append(buf)
            buf = ch
    if buf:
        lines.append(buf)
    return lines or [""]


def draw_len(text: str, font: ImageFont.FreeTypeFont) -> float:
    try:
        return font.getlength(text)
    except AttributeError:  # 老版 Pillow
        return font.getsize(text)[0]


def _cover(img: Image.Image, w: int, h: int) -> Image.Image:
    """等比 cover 裁切到目标尺寸（理想情况底图尺寸已与卡布一致，仅兜底）。"""
    sw, sh = img.size
    scale = max(w / sw, h / sh)
    nw, nh = round(sw * scale), round(sh * scale)
    img = img.resize((nw, nh))
    left, top = (nw - w) // 2, (nh - h) // 2
    return img.crop((left, top, left + w, top + h))


def _fetch_avatar(url: str, timeout: float = 5.0) -> Image.Image | None:
    """下载头像；任何失败返回 None（调用方画占位头像）。"""
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return Image.open(io.BytesIO(resp.read())).convert("RGBA")
    except Exception:
        return None


def _circle_img(img: Image.Image, diameter: int) -> Image.Image:
    img = img.resize((diameter, diameter))
    mask = Image.new("L", (diameter * 4, diameter * 4), 0)
    ImageDraw.Draw(mask).ellipse((0, 0, diameter * 4 - 1, diameter * 4 - 1), fill=255)
    mask = mask.resize((diameter, diameter))
    out = Image.new("RGBA", (diameter, diameter), (0, 0, 0, 0))
    out.paste(img, (0, 0), mask)
    return out


def _gradient(w: int, h: int, base_rgb: tuple, dark: bool = False) -> Image.Image:
    """纵向渐变：light=白底为主幸运色氛围；dark=暗夜底混入幸运色。"""
    if dark:
        top = _mix(base_rgb, (24, 25, 38), 0.86)
        bottom = _mix(base_rgb, (24, 25, 38), 0.94)
    else:
        top = _mix(base_rgb, (255, 255, 255), 0.74)
        bottom = _mix(base_rgb, (255, 255, 255), 0.92)
    img = Image.new("RGB", (1, h))
    px = img.load()
    for y in range(h):
        t = y / max(1, h - 1)
        px[0, y] = _mix(top, bottom, t)
    return img.resize((w, h))


def _sparkle(draw: ImageDraw.ImageDraw, cx: float, cy: float, r: float, rgb: tuple, alpha: int = 120):
    """四角星装饰。"""
    color = rgb + (alpha,)
    draw.polygon(
        [(cx, cy - r), (cx + r * 0.28, cy - r * 0.28), (cx + r, cy), (cx + r * 0.28, cy + r * 0.28),
         (cx, cy + r), (cx - r * 0.28, cy + r * 0.28), (cx - r, cy), (cx - r * 0.28, cy - r * 0.28)],
        fill=color,
    )


def render_card(
    result: dict,
    cards_root,
    font_path: str | None = None,
    extra_font_dirs=None,
    width: int = 1024,
    height: int = 1536,
    signer: str = "星语者",
    nickname: str = "",
    avatar_url: str = "",
    uid: str = "",
    bg_image=None,
    theme: str = "light",
) -> str:
    """渲染当日星语签，落盘 cards_root/<date>.png 并返回路径。失败抛异常由调用方回退。"""
    font_file = find_font(font_path, extra_font_dirs)
    if not font_file:
        raise RuntimeError("未找到可用中文字体（card_font_path / extra_font_dirs / 系统）")

    W, H = int(width), int(height)
    u = W / 1024.0
    lucky = result.get("lucky_color") or {}
    lucky_rgb = _hex_rgb(lucky.get("hex", "#F6C6D3"))
    grade_rgb = _hex_rgb(result.get("grade_color", "#E86A8A"))
    dark = str(theme or "light").lower() == "dark"
    if dark:
        ink, sub = (230, 230, 240), (158, 160, 178)
        panel_fill, divider_rgb = (30, 31, 44, 240), (62, 63, 80, 255)
    else:
        ink, sub = (74, 74, 96), (150, 150, 168)
        panel_fill, divider_rgb = (255, 255, 255, 236), (238, 236, 242, 255)

    if bg_image:
        base = _cover(Image.open(bg_image).convert("RGB"), W, H)
        scrim = Image.new("RGBA", (W, H), (255, 255, 255, 170))
        base = Image.alpha_composite(base.convert("RGBA"), scrim)
    else:
        base = _gradient(W, H, lucky_rgb, dark=dark).convert("RGBA")

    # 背景装饰：几颗四角星（淡）
    deco = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    dd = ImageDraw.Draw(deco)
    _sparkle(dd, W * 0.14, H * 0.08, 16 * u, lucky_rgb, 90)
    _sparkle(dd, W * 0.86, H * 0.16, 12 * u, lucky_rgb, 80)
    _sparkle(dd, W * 0.10, H * 0.30, 9 * u, lucky_rgb, 70)
    img = Image.alpha_composite(base, deco)

    # 白色圆角内容面板
    margin = int(56 * u)
    panel = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    ImageDraw.Draw(panel).rounded_rectangle(
        [margin, margin, W - margin, H - margin],
        radius=int(44 * u), fill=panel_fill,
    )
    img = Image.alpha_composite(img, panel)
    draw = ImageDraw.Draw(img)

    # 生日特权（F14）：金环描边
    if result.get("birthday_today"):
        draw.rounded_rectangle(
            [margin - int(10 * u), margin - int(10 * u),
             W - margin + int(10 * u), H - margin + int(10 * u)],
            radius=int(54 * u), outline=(240, 184, 96, 230),
            width=max(2, int(5 * u)),
        )

    pad = int(48 * u)
    left = margin + pad
    right = W - margin - pad
    inner_w = right - left
    y = margin + int(28 * u)

    # ① 身份头：头像 + 昵称 + QQ号 + 日期
    av_d = int(128 * u)
    av = None
    if avatar_url:
        av = _fetch_avatar(avatar_url)
    if av is not None:
        avatar_img = _circle_img(av, av_d)
    else:
        placeholder = Image.new("RGBA", (av_d * 2, av_d * 2), _mix(lucky_rgb, (255, 255, 255), 0.35) + (255,))
        pd = ImageDraw.Draw(placeholder)
        initial = (nickname or "星")[0]
        pd.text((av_d, av_d), initial, font=_font(font_file, int(88 * u)), fill=(255, 255, 255, 255), anchor="mm")
        avatar_img = _circle_img(placeholder, av_d)
    img.paste(avatar_img, (left, y), avatar_img)
    tx = left + av_d + int(36 * u)
    draw.text((tx, y + int(8 * u)), nickname or "旅行者",
              font=_font(font_file, int(50 * u)), fill=ink)
    if uid:
        qq_line = f"QQ {uid}"
        if result.get("constellation"):
            qq_line += f" · {result['constellation']}"
        draw.text((tx, y + int(74 * u)), qq_line,
                  font=_font(font_file, int(34 * u)), fill=sub)
    draw.text((right, y + int(8 * u)), str(result.get("date", "")),
              font=_font(font_file, int(34 * u)), fill=sub, anchor="ra")
    y += av_d + int(34 * u)

    # 分隔线
    draw.line([(left, y), (right, y)], fill=divider_rgb, width=max(1, int(2 * u)))
    y += int(30 * u)

    # ② 吉凶大字（主题色随档位，粗体更有签的分量；愚人节等显示态用 grade_display）
    grade = str(result.get("grade_display") or result.get("grade", "？"))
    draw.text((W // 2, y + int(78 * u)), grade,
              font=_font(_bold_variant(font_file), int(148 * u)), fill=grade_rgb, anchor="mm")
    y += int(182 * u)

    # ③ 签文话语区（主体文字，居中，最多 5 行）
    sign_lines = _wrap(str(result.get("sign_text", "")), _font(font_file, int(40 * u)), inner_w)[:5]
    line_h = int(62 * u)
    for line in sign_lines:
        draw.text((W // 2, y), line, font=_font(font_file, int(40 * u)), fill=ink, anchor="ma")
        y += line_h
    y += int(20 * u)

    # ④ 六维星数（2 列 × 3 行）
    dims = result.get("dims") or {}
    cell_w = inner_w / 2
    for i, (k, v) in enumerate(dims.items()):
        cx = left + cell_w * (i % 2) + int(16 * u)
        cy = y + (i // 2) * int(62 * u)
        draw.text((cx, cy), k, font=_font(font_file, int(32 * u)), fill=sub)
        stars = "★" * v + "☆" * (5 - v)
        draw.text((cx + int(140 * u), cy), stars,
                  font=_font(font_file, int(34 * u)), fill=grade_rgb)
    rows = (len(dims) + 1) // 2
    y += int(62 * u) * rows + int(18 * u)

    # ⑤ 幸运指数（大数字，档位色）
    draw.text((W // 2, y + int(6 * u)), "幸运指数",
              font=_font(font_file, int(30 * u)), fill=sub, anchor="ma")
    draw.text((W // 2, y + int(44 * u)), str(result.get("score", "？")),
              font=_font(_bold_variant(font_file), int(92 * u)), fill=grade_rgb, anchor="ma")
    y += int(152 * u)

    # ⑥ 宜忌（彩色圆角章 + 内容）
    for label, items, rgb in (("宜", result.get("yi") or [], (122, 178, 138)),
                              ("忌", result.get("ji") or [], (216, 128, 128))):
        chip_w, chip_h = int(76 * u), int(52 * u)
        draw.rounded_rectangle([left, y, left + chip_w, y + chip_h],
                               radius=int(14 * u), fill=_mix(rgb, (255, 255, 255), 0.35) + (255,))
        draw.text((left + chip_w / 2, y + chip_h / 2), label,
                  font=_font(font_file, int(36 * u)), fill=(255, 255, 255, 255), anchor="mm")
        draw.text((left + chip_w + int(28 * u), y + chip_h / 2), "、".join(items),
                  font=_font(font_file, int(36 * u)), fill=ink, anchor="lm")
        y += chip_h + int(14 * u)
    y += int(6 * u)

    # ⑦ 幸运物 / 色 / 数字 / 方位（2×2 网格）+ 月相 + 连签
    grid = [
        ("幸运物", str(result.get("lucky_item", "？"))),
        ("幸运色", str((result.get("lucky_color") or {}).get("name", "？"))),
        ("幸运数字", str(result.get("lucky_number", "？"))),
        ("幸运方位", str(result.get("lucky_dir", "？"))),
    ]
    for i, (label, value) in enumerate(grid):
        cx = left + cell_w * (i % 2) + int(16 * u)
        cy = y + (i // 2) * int(90 * u)
        draw.text((cx, cy), label, font=_font(font_file, int(28 * u)), fill=sub)
        draw.text((cx, cy + int(34 * u)), value,
                  font=_font(font_file, int(38 * u)), fill=ink)
    y += int(90 * u) * 2 + int(4 * u)

    phase = result.get("phase") or {}
    foot = f"月相：{phase.get('name', '？')}——{phase.get('text', '')}"
    streak = result.get("streak") or 0
    if streak >= 2:
        foot += f" ｜ 连签 {streak} 天"
    # 底部保险：月相行不许压到落款区
    y = min(y, H - margin - int(96 * u))
    draw.text((W // 2, y), foot, font=_font(font_file, int(28 * u)), fill=sub, anchor="ma")
    y += int(48 * u)

    # 落款 + 小月牙
    draw.text((right, H - margin - int(30 * u)), f"—— {signer}",
              font=_font(font_file, int(34 * u)), fill=sub, anchor="rs")
    mr = int(16 * u)
    mcx, mcy = left + mr, H - margin - int(36 * u)
    draw.ellipse([mcx - mr, mcy - mr, mcx + mr, mcy + mr], fill=_mix(lucky_rgb, (255, 255, 255), 0.15) + (255,))
    draw.ellipse([mcx - mr * 0.1, mcy - mr * 1.15, mcx + mr * 1.5, mcy + mr * 1.15],
                 fill=(255, 255, 255, 255))

    cards_root = Path(cards_root)
    cards_root.mkdir(parents=True, exist_ok=True)
    out = cards_root / f"{result.get('date', 'unknown')}.png"
    img.convert("RGB").save(out, "PNG")
    return str(out)
