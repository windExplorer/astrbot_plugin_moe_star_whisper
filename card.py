# -*- coding: utf-8 -*-
"""萌萌星语 · Pillow 图卡渲染（纯 Pillow，无 astrbot 依赖，可独立测试）。

两种版式（M8/M8.5）：
  单联：无 AI 牌面时的竖版运势卡（含塔罗行）；
  塔罗双联：有 AI 牌面时左图右文的 2:1 横图（左 = anima 牌面 + 塔罗框，
  右 = 幸运色渐变面板 + 全部运势信息，弹性间隙等分布局）。
字体分层：展示文字（吉凶/牌名）用楷体系，正文用基础字体；均不打包、多级查找。
"""
from __future__ import annotations

import io
from datetime import datetime
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

# 展示字体候选（楷体/宋体系——命签感）
_DISPLAY_CANDIDATES = (
    "C:/Windows/Fonts/simkai.ttf",
    "C:/Windows/Fonts/STKAITI.TTF",
    "C:/Windows/Fonts/KAIU.TTF",
)

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


def _font(font_file: str, size: float) -> ImageFont.FreeTypeFont:
    key = (font_file, int(size))
    if key not in _font_cache:
        _font_cache[key] = ImageFont.truetype(font_file, int(size))
    return _font_cache[key]


def _bold_variant(font_file: str) -> str:
    """同目录粗体变体（msyh.ttc→msyhbd.ttc、*Regular*→*Bold*）；没有就退回原字体。"""
    p = Path(font_file)
    for a, b in (("msyh.ttc", "msyhbd.ttc"), ("msyh.ttf", "msyhbd.ttc"), ("Regular", "Bold")):
        if a in p.name:
            cand = p.with_name(p.name.replace(a, b))
            if cand.is_file():
                return str(cand)
    return font_file


def _display_font_file(font_file: str) -> str:
    """展示字体：楷体/宋体系（命签感），都没有则退回粗体变体。"""
    for cand in _DISPLAY_CANDIDATES:
        if Path(cand).is_file():
            return cand
    return _bold_variant(font_file)


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


def _circle_img(img: Image.Image, diameter: int) -> Image.Image:
    img = img.resize((diameter, diameter))
    mask = Image.new("L", (diameter * 4, diameter * 4), 0)
    ImageDraw.Draw(mask).ellipse((0, 0, diameter * 4 - 1, diameter * 4 - 1), fill=255)
    mask = mask.resize((diameter, diameter))
    out = Image.new("RGBA", (diameter, diameter), (0, 0, 0, 0))
    out.paste(img, (0, 0), mask)
    return out


def _gradient(w: int, h: int, base_rgb: tuple, dark: bool = False,
              top_mix: float | None = None, bottom_mix: float | None = None) -> Image.Image:
    """纵向渐变：light=白底混幸运色；dark=暗夜底混幸运色。混合度可调。"""
    if dark:
        top = _mix(base_rgb, (24, 25, 38), top_mix if top_mix is not None else 0.86)
        bottom = _mix(base_rgb, (24, 25, 38), bottom_mix if bottom_mix is not None else 0.94)
    else:
        top = _mix(base_rgb, (255, 255, 255), top_mix if top_mix is not None else 0.74)
        bottom = _mix(base_rgb, (255, 255, 255), bottom_mix if bottom_mix is not None else 0.92)
    img = Image.new("RGB", (1, h))
    px = img.load()
    for y in range(h):
        t = y / max(1, h - 1)
        px[0, y] = _mix(top, bottom, t)
    return img.resize((w, h))


def _panel_base(w: int, h: int, base_rgb: tuple, dark: bool, radius: int) -> Image.Image:
    """圆角面板的幸运色渐变底（顶浓底淡、全不透明）——告别纯白。"""
    grad = _gradient(w, h, base_rgb, dark=dark,
                     top_mix=(0.78 if dark else 0.52),
                     bottom_mix=(0.92 if dark else 0.90)).convert("RGBA")
    mask = Image.new("L", (w, h), 0)
    ImageDraw.Draw(mask).rounded_rectangle([0, 0, w - 1, h - 1], radius=radius, fill=255)
    grad.putalpha(mask)
    return grad


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
    avatar_data: bytes | None = None,
    uid: str = "",
    bg_image=None,
    theme: str = "light",
) -> str:
    """渲染当日星语签，落盘 cards_root/<date>.png 并返回路径。失败抛异常由调用方回退。"""
    font_file = find_font(font_path, extra_font_dirs)
    if not font_file:
        raise RuntimeError("未找到可用中文字体")

    # 塔罗双联模式（M8）：有 AI 牌面图 + 塔罗信息时走左右合成版式
    if bg_image and Path(bg_image).exists() and result.get("tarot"):
        return render_tarot_card(
            result, str(bg_image), cards_root, font_file,
            width=int(width), height=int(height),
            signer=str(signer), nickname=str(nickname or ""),
            avatar_data=avatar_data, uid=str(uid or ""),
            theme=str(theme or "light"),
        )

    SW, H = int(width), int(height)
    u = SW / 700.0
    W = SW
    lucky = result.get("lucky_color") or {}
    lucky_rgb = _hex_rgb(lucky.get("hex", "#F6C6D3"))
    grade_rgb = _hex_rgb(result.get("grade_color", "#E86A8A"))
    dark = str(theme or "light").lower() == "dark"
    if dark:
        ink, sub = (232, 230, 240), (158, 160, 178)
        panel_fill = _mix(lucky_rgb, (26, 27, 40), 0.92) + (238,)
        divider_rgb = (62, 63, 80, 255)
    else:
        ink, sub = (74, 74, 96), (150, 150, 168)
        # 面板带幸运色的极淡底，渐变层次透出（不再是纯白）
        panel_fill = _mix(lucky_rgb, (255, 255, 255), 0.88) + (233,)
        divider_rgb = (238, 236, 242, 255)

    base = _gradient(W, H, lucky_rgb, dark=dark).convert("RGBA")
    deco = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    dd = ImageDraw.Draw(deco)
    _sparkle(dd, W * 0.14, H * 0.08, 16 * u, lucky_rgb, 90)
    _sparkle(dd, W * 0.86, H * 0.16, 12 * u, lucky_rgb, 80)
    _sparkle(dd, W * 0.10, H * 0.30, 9 * u, lucky_rgb, 70)
    img = Image.alpha_composite(base, deco)

    margin = int(56 * u)
    panel = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    ImageDraw.Draw(panel).rounded_rectangle(
        [margin, margin, W - margin, H - margin],
        radius=int(44 * u), fill=panel_fill,
    )
    img = Image.alpha_composite(img, panel)
    draw = ImageDraw.Draw(img)

    pad = int(48 * u)
    left = margin + pad
    right = W - margin - pad
    inner_w = right - left
    y = margin + int(28 * u)

    # ① 身份头：头像 + 昵称 + QQ号 + 日期（头像 bytes 由调用方异步下载）
    av_d = int(128 * u)
    av = None
    if avatar_data:
        try:
            av = Image.open(io.BytesIO(avatar_data)).convert("RGBA")
        except Exception:
            av = None
    if av is not None:
        avatar_img = _circle_img(av, av_d)
    else:
        placeholder = Image.new("RGBA", (av_d * 2, av_d * 2),
                                _mix(lucky_rgb, (255, 255, 255), 0.35) + (255,))
        pdr = ImageDraw.Draw(placeholder)
        pdr.text((av_d, av_d), (nickname or "星")[0],
                 font=_font(font_file, int(88 * u)), fill=(255, 255, 255, 255), anchor="mm")
        avatar_img = _circle_img(placeholder, av_d)
    img.paste(avatar_img, (left, y), avatar_img)
    tx = left + av_d + int(36 * u)
    draw.text((tx, y + int(8 * u)), nickname or "旅行者",
              font=_font(font_file, int(50 * u)), fill=ink)
    qq_line = f"QQ {uid}" if uid else ""
    if result.get("constellation"):
        qq_line += f" · {result['constellation']}"
    draw.text((tx, y + int(74 * u)), qq_line,
              font=_font(font_file, int(34 * u)), fill=sub)
    draw.text((right, y + int(8 * u)), str(result.get("date", "")),
              font=_font(font_file, int(34 * u)), fill=sub, anchor="ra")
    y += av_d + int(34 * u)

    # 分隔线
    draw.line([(left, y), (right, y)], fill=divider_rgb, width=max(1, int(2 * u)))
    y += int(20 * u)

    # ② 塔罗行（M8：单联也展示今日大阿卡纳）
    tarot = result.get("tarot")
    if tarot:
        draw.text((left, y), f"{tarot.get('name_cn', '？')} · {tarot.get('label', '')}",
                  font=_font(_display_font_file(font_file), int(36 * u)), fill=(212, 175, 55))
        draw.text((right, y + int(4 * u)), tarot.get("name_en", ""),
                  font=_font(font_file, int(22 * u)), fill=sub, anchor="ra")
        y += int(44 * u)
        draw.text((left, y), tarot.get("keywords", ""),
                  font=_font(font_file, int(22 * u)), fill=sub)
        y += int(34 * u)

    # ③ 吉凶大字（楷体系展示字体；愚人节等显示态用 grade_display）
    grade = str(result.get("grade_display") or result.get("grade", "？"))
    draw.text((W // 2, y + int(72 * u)), grade,
              font=_font(_display_font_file(font_file), int(140 * u)), fill=grade_rgb, anchor="mm")
    y += int(168 * u)

    # ④ 签文话语区（主体文字，居中，最多 5 行）
    sign_lines = _wrap(str(result.get("sign_text", "")), _font(font_file, int(40 * u)), inner_w)[:5]
    line_h = int(62 * u)
    for line in sign_lines:
        draw.text((W // 2, y), line, font=_font(font_file, int(40 * u)), fill=ink, anchor="ma")
        y += line_h
    y += int(20 * u)

    # ⑤ 六维星数（2 列 × 3 行）
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

    # ⑥ 幸运指数（大数字，档位色）
    draw.text((W // 2, y + int(6 * u)), "幸运指数",
              font=_font(font_file, int(30 * u)), fill=sub, anchor="ma")
    draw.text((W // 2, y + int(44 * u)), str(result.get("score", "？")),
              font=_font(_bold_variant(font_file), int(92 * u)), fill=grade_rgb, anchor="ma")
    y += int(152 * u)

    # ⑦ 宜忌（彩色圆角章 + 内容）
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

    # ⑧ 幸运物 / 色 / 数字 / 方位（2×2 网格）
    grid = [
        ("幸运物", str(result.get("lucky_item", "？"))),
        ("幸运色", str((result.get("lucky_color") or {}).get("name", "？"))),
        ("幸运数字", str(result.get("lucky_number", "？"))),
        ("幸运方位", str(result.get("lucky_dir", "？"))),
    ]
    for i, (label, value) in enumerate(grid):
        cx = left + cell_w * (i % 2) + int(16 * u)
        cy = y + (i // 2) * int(82 * u)
        draw.text((cx, cy), label, font=_font(font_file, int(28 * u)), fill=sub)
        draw.text((cx, cy + int(34 * u)), value,
                  font=_font(font_file, int(38 * u)), fill=ink)
    y += int(82 * u) * 2 + int(4 * u)

    # ⑨ 脚注 + 落款
    phase = result.get("phase") or {}
    foot = f"月相：{phase.get('name', '？')}——{phase.get('text', '')}"
    streak = result.get("streak") or 0
    if streak >= 2:
        foot += f" ｜ 连签 {streak} 天"
    y = min(y, H - margin - int(96 * u))
    draw.text((W // 2, y), foot, font=_font(font_file, int(28 * u)), fill=sub, anchor="ma")
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


def render_tarot_card(
    result: dict,
    bg_image: str,
    cards_root,
    font_file: str,
    width: int,
    height: int,
    signer: str = "星语者",
    nickname: str = "",
    avatar_data: bytes | None = None,
    uid: str = "",
    theme: str = "light",
) -> str:
    """塔罗双联版式（M8/M8.5）：左联 AI 牌面 + 右联运势面板。

    右联为幸运色渐变圆角面板（顶浓底淡），布局按「固定块高 + 弹性间隙」
    等分剩余空间——不留大片空白也不挤压；吉凶/牌名用楷体系展示字体。
    """
    SW, H = int(width), int(height)
    u = SW / 700.0
    W = SW * 2
    lucky = result.get("lucky_color") or {}
    lucky_rgb = _hex_rgb(lucky.get("hex", "#F6C6D3"))
    grade_rgb = _hex_rgb(result.get("grade_color", "#E86A8A"))
    gold = (212, 175, 55)
    dark = str(theme or "light").lower() == "dark"
    if dark:
        ink, sub = (232, 230, 240), (158, 160, 178)
        line_rgb = (70, 71, 88, 255)
    else:
        ink, sub = (74, 74, 96), (150, 150, 168)
        line_rgb = (238, 236, 242, 255)
    disp = _display_font_file(font_file)

    canvas = Image.new("RGBA", (W, H), (0, 0, 0, 0))

    # ---- 左联：AI 牌面（塔罗框 + 底部牌名条） ----
    side = _cover(Image.open(bg_image).convert("RGB"), SW, H).convert("RGBA")
    canvas.paste(side, (0, 0))
    sdraw = ImageDraw.Draw(canvas)
    sdraw.rectangle([6, 6, SW - 7, H - 7], outline=gold + (235,), width=max(2, int(3 * u)))
    sdraw.rectangle([int(12 * u), int(12 * u), SW - int(13 * u), H - int(13 * u)],
                    outline=gold + (150,), width=1)
    tarot = result.get("tarot") or {}
    band_h = int(96 * u)
    band = Image.new("RGBA", (SW, band_h), (0, 0, 0, 0))
    bdraw = ImageDraw.Draw(band)
    for yy in range(band_h):
        bdraw.line([(0, yy), (SW, yy)], fill=(10, 10, 18, int(150 * yy / max(1, band_h))))
    canvas.paste(band, (0, H - band_h), band)
    sdraw.text((int(24 * u), H - band_h + int(14 * u)),
               f"{tarot.get('name_cn', '？')} · {tarot.get('label', '')}",
               font=_font(_display_font_file(font_file), int(38 * u)), fill=(255, 255, 255, 255))
    sdraw.text((int(24 * u), H - band_h + int(58 * u)),
               f"{tarot.get('name_en', '')} ｜ {tarot.get('keywords', '')}",
               font=_font(font_file, int(22 * u)), fill=(228, 226, 236, 255))
    _sparkle(sdraw, SW * 0.86, H * 0.08, 13 * u, gold, 200)

    # ---- 右联：幸运色渐变面板（顶浓底淡） ----
    grad = _gradient(SW, H, lucky_rgb, dark=dark,
                     top_mix=(0.50 if not dark else 0.74),
                     bottom_mix=(0.90 if not dark else 0.92)).convert("RGBA")
    canvas.paste(grad, (SW, 0))
    inset = int(12 * u)
    pw, ph = SW - inset, H - inset
    panel = _panel_base(pw, ph, lucky_rgb, dark, int(18 * u))
    canvas.paste(panel, (SW + inset // 2, inset // 2), panel)
    draw = ImageDraw.Draw(canvas)
    draw.rectangle([SW + 6, 6, W - 7, H - 7], outline=gold + (200,), width=max(1, int(2 * u)))

    left = SW + int(32 * u)
    right = W - int(32 * u)
    mid = (left + right) // 2
    top = int(28 * u)
    content_h = H - top - int(52 * u)

    blocks = []

    def block(h, fn):
        blocks.append((int(h), fn))

    # ① 身份头
    def b_head(y):
        av_d = int(84 * u)
        av = None
        if avatar_data:
            try:
                av = Image.open(io.BytesIO(avatar_data)).convert("RGBA")
            except Exception:
                av = None
        if av is not None:
            avatar_img = _circle_img(av, av_d)
        else:
            placeholder = Image.new("RGBA", (av_d * 2, av_d * 2),
                                    _mix(lucky_rgb, (255, 255, 255), 0.35) + (255,))
            pdr = ImageDraw.Draw(placeholder)
            pdr.text((av_d, av_d), (nickname or "星")[0],
                     font=_font(font_file, int(60 * u)), fill=(255, 255, 255, 255), anchor="mm")
            avatar_img = _circle_img(placeholder, av_d)
        canvas.paste(avatar_img, (left, y), avatar_img)
        tx = left + av_d + int(24 * u)
        draw.text((tx, y), nickname or "旅行者", font=_font(font_file, int(40 * u)), fill=ink)
        qq_line = f"QQ {uid}" if uid else ""
        if result.get("constellation"):
            qq_line += f" · {result['constellation']}"
        draw.text((tx, y + int(54 * u)), qq_line, font=_font(font_file, int(24 * u)), fill=sub)
        draw.text((right, y), str(result.get("date", "")),
                  font=_font(font_file, int(24 * u)), fill=sub, anchor="ra")
    block(int(88 * u), b_head)

    def b_divider(y):
        draw.line([(left, y + int(4 * u)), (right, y + int(4 * u))], fill=line_rgb, width=1)
    block(int(10 * u), b_divider)

    # ② 塔罗行（牌名/正逆位/关键词/解读，行距拉开避免重叠）
    interp_lines = _wrap(str(tarot.get("interp", "")), _font(font_file, int(22 * u)), right - left)[:2]
    def b_tarot(y):
        draw.text((left, y), tarot.get("name_cn", "？"),
                  font=_font(disp, int(40 * u)), fill=gold)
        draw.text((right, y + int(10 * u)), f"{tarot.get('label', '')} · {tarot.get('name_en', '')}",
                  font=_font(font_file, int(22 * u)), fill=sub, anchor="ra")
        draw.text((left, y + int(56 * u)), tarot.get("keywords", ""),
                  font=_font(font_file, int(21 * u)), fill=sub)
        for i, line in enumerate(interp_lines):
            draw.text((left, y + int(84 * u) + i * int(32 * u)), line,
                      font=_font(font_file, int(22 * u)), fill=ink)
    block(int(84 * u) + int(32 * u) * len(interp_lines) + int(10 * u), b_tarot)

    # ③ 吉凶大字
    grade = str(result.get("grade_display") or result.get("grade", "？"))
    def b_grade(y):
        draw.text((mid, y + int(52 * u)), grade,
                  font=_font(disp, int(108 * u)), fill=grade_rgb, anchor="mm")
    block(int(112 * u), b_grade)

    # ④ 签文话语区
    sign_lines = _wrap(str(result.get("sign_text", "")), _font(font_file, int(30 * u)), right - left)[:4]
    line_h = int(46 * u)
    def b_sign(y):
        for i, line in enumerate(sign_lines):
            draw.text((mid, y + i * line_h), line,
                      font=_font(font_file, int(30 * u)), fill=ink, anchor="ma")
    block(line_h * len(sign_lines) + int(4 * u), b_sign)

    # ⑤ 六维星数
    dims = result.get("dims") or {}
    cell_w = (right - left) / 2
    def b_dims(y):
        for i, (k, v) in enumerate(dims.items()):
            cx = left + cell_w * (i % 2) + int(8 * u)
            cy = y + (i // 2) * int(46 * u)
            draw.text((cx, cy), k, font=_font(font_file, int(24 * u)), fill=sub)
            draw.text((cx + int(112 * u), cy), "★" * v + "☆" * (5 - v),
                      font=_font(font_file, int(26 * u)), fill=grade_rgb)
    block(int(46 * u) * ((len(dims) + 1) // 2), b_dims)

    # ⑥ 幸运指数（label 与数字同一中线，不再错位）
    def b_score(y):
        cy = y + int(28 * u)
        draw.text((left, cy), "幸运指数", font=_font(font_file, int(24 * u)), fill=sub, anchor="lm")
        draw.text((left + int(110 * u), cy), str(result.get("score", "？")),
                  font=_font(disp, int(52 * u)), fill=grade_rgb, anchor="lm")
        draw.text((right, cy), f"满分 100", font=_font(font_file, int(20 * u)), fill=sub, anchor="rm")
    block(int(60 * u), b_score)

    # ⑦ 宜忌
    def b_yiji(y):
        yy = y
        for label, items, rgb in (("宜", result.get("yi") or [], (122, 178, 138)),
                                  ("忌", result.get("ji") or [], (216, 128, 128))):
            chip_w, chip_h = int(52 * u), int(36 * u)
            draw.rounded_rectangle([left, yy, left + chip_w, yy + chip_h],
                                   radius=int(9 * u), fill=_mix(rgb, (255, 255, 255), 0.35) + (255,))
            draw.text((left + chip_w / 2, yy + chip_h / 2), label,
                      font=_font(font_file, int(24 * u)), fill=(255, 255, 255, 255), anchor="mm")
            draw.text((left + chip_w + int(16 * u), yy + chip_h / 2), "、".join(items),
                      font=_font(font_file, int(26 * u)), fill=ink, anchor="lm")
            yy += chip_h + int(8 * u)
    block(int(2 * (36 * u + 8 * u)), b_yiji)

    # ⑧ 幸运四件套（2×2 小卡网格，带淡底与润色小注）
    def b_lucky(y):
        cells = [
            ("幸运物", str(result.get("lucky_item", "？")), "带在身边试试"),
            ("幸运色", str((result.get("lucky_color") or {}).get("name", "？")), "今天多看它两眼"),
            ("幸运数字", str(result.get("lucky_number", "？")), "做选择时想起它"),
            ("幸运方位", str(result.get("lucky_dir", "？")), "朝它走两步"),
        ]
        cw, ch, gapx = (right - left) / 2 - int(8 * u), int(64 * u), int(12 * u)
        for i, (label, value, note) in enumerate(cells):
            cx = left + (cw + gapx) * (i % 2)
            cy = y + (ch + int(10 * u)) * (i // 2)
            draw.rounded_rectangle([cx, cy, cx + cw, cy + ch],
                                   radius=int(10 * u),
                                   fill=_mix(lucky_rgb, (255, 255, 255), 0.55) + (200,))
            draw.text((cx + int(14 * u), cy + int(10 * u)), label,
                      font=_font(font_file, int(19 * u)), fill=sub)
            draw.text((cx + int(14 * u), cy + int(30 * u)), value,
                      font=_font(font_file, int(27 * u)), fill=ink)
            draw.text((right - int(6 * u) if i % 2 == 0 else W - int(32 * u) + int(6 * u), cy + int(10 * u)),
                      note, font=_font(font_file, int(17 * u)), fill=sub, anchor="ra")
    block(int(2 * (64 * u + 10 * u)), b_lucky)

    # ⑨ 脚注（月相/连签）
    phase = result.get("phase") or {}
    foot = f"月相·{phase.get('name', '？')}：{phase.get('text', '')}"
    streak = result.get("streak") or 0
    if streak >= 2:
        foot += f" ｜ 连签 {streak} 天"
    def b_foot(y):
        draw.text((mid, y), foot, font=_font(font_file, int(21 * u)), fill=sub, anchor="ma")
    block(int(30 * u), b_foot)

    # ---- 弹性间隙等分布局 ----
    total = sum(h for h, _ in blocks)
    gaps = max(1, len(blocks) - 1)
    free = max(0, content_h - total)
    gap = int(min(30 * u, max(6 * u, free / gaps)))
    y = top
    for i, (h, fn) in enumerate(blocks):
        fn(y)
        y += h
        if i < gaps:
            y += gap

    draw.text((right, H - int(34 * u)), f"—— {signer}",
              font=_font(font_file, int(24 * u)), fill=sub, anchor="rs")

    cards_root = Path(cards_root)
    cards_root.mkdir(parents=True, exist_ok=True)
    out = cards_root / f"{result.get('date', 'unknown')}.png"
    canvas.convert("RGB").save(out, "PNG")
    return str(out)


def render_push_card(
    date_str: str,
    weekday_name: str,
    phase: dict,
    festival_line: str = "",
    accent_hex: str = "#F6C6D3",
    cards_root=None,
    font_path: str | None = None,
    extra_font_dirs=None,
    width: int = 1024,
    height: int = 620,
    signer: str = "星语者",
) -> str:
    """每日推送的「今日星象」卡（F17）：日期 + 月相 + 节日 + 抽签引导。"""
    font_file = find_font(font_path, extra_font_dirs)
    if not font_file:
        raise RuntimeError("未找到可用中文字体")
    W, H = int(width), int(height)
    u = W / 1024.0
    accent = _hex_rgb(accent_hex)
    ink, sub = (74, 74, 96), (150, 150, 168)
    img = _gradient(W, H, accent).convert("RGBA")
    deco = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    dd = ImageDraw.Draw(deco)
    _sparkle(dd, W * 0.16, H * 0.24, 14 * u, accent, 90)
    _sparkle(dd, W * 0.86, H * 0.34, 10 * u, accent, 80)
    img = Image.alpha_composite(img, deco)

    margin = int(48 * u)
    panel = _panel_base(W - 2 * margin, H - 2 * margin, accent, False, int(40 * u))
    img.paste(panel, (margin, margin), panel)
    draw = ImageDraw.Draw(img)
    left, right = margin + int(48 * u), W - margin - int(48 * u)
    y = margin + int(44 * u)

    draw.text((left, y), "萌萌星语 · 今日星象",
              font=_font(font_file, int(34 * u)), fill=sub)
    try:
        d = datetime.strptime(date_str, "%Y-%m-%d")
        big = f"{d.month} 月 {d.day} 日"
    except Exception:
        big = date_str
    draw.text((left, y + int(56 * u)), big,
              font=_font(_display_font_file(font_file), int(96 * u)), fill=ink)
    draw.text((right, y + int(96 * u)), weekday_name,
              font=_font(font_file, int(44 * u)), fill=sub, anchor="ra")
    y += int(200 * u)
    draw.line([(left, y), (right, y)], fill=(238, 236, 242, 255), width=max(1, int(2 * u)))
    y += int(40 * u)

    draw.text((left, y), f"月相 · {(phase or {}).get('name', '？')}",
              font=_font(_display_font_file(font_file), int(46 * u)), fill=ink)
    draw.text((left, y + int(64 * u)), (phase or {}).get("text", ""),
              font=_font(font_file, int(34 * u)), fill=sub)
    y += int(124 * u)
    if festival_line:
        draw.text((left, y), festival_line,
                  font=_font(font_file, int(34 * u)), fill=sub)
        y += int(52 * u)

    draw.text((left, H - margin - int(72 * u)), "今天的专属星语签已就位",
              font=_font(font_file, int(38 * u)), fill=ink)
    draw.text((right, H - margin - int(30 * u)), f"—— {signer}",
              font=_font(font_file, int(30 * u)), fill=sub, anchor="rs")

    cards_root = Path(cards_root)
    cards_root.mkdir(parents=True, exist_ok=True)
    out = cards_root / f"push_{date_str}.png"
    img.convert("RGB").save(out, "PNG")
    return str(out)
