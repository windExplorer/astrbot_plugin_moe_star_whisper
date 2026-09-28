# -*- coding: utf-8 -*-
"""萌萌星语 · Pillow 图卡渲染（纯 Pillow，无 astrbot 依赖，可独立测试）。

运势卡两种版式（M8/M8.5）：
  单联：无 AI 牌面时的竖版运势卡（含塔罗行）；
  塔罗双联：有 AI 牌面时左图右文的 2:1 横图（左 = 萌绘牌面 + 塔罗框，
  右 = 幸运色渐变面板 + 全部运势信息，弹性间隙等分布局）。
提示卡（M9）：星尘钱包 / 道具商店 / 星语榜 / PK / 通用通知 / 运势日历，
共用 _utility_card_base 底座（渐变背景 + 圆角面板 + 标题区），风格与运势卡一致。
字体分层：展示文字（吉凶/牌名/大数字）用楷体系，正文用基础字体；均不打包、多级查找。
"""
from __future__ import annotations

import io
import re
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


def _font_loadable(path: str) -> bool:
    """试加载一次（20 号），失败说明这个字体本机读不了。

    为什么要试：woff2 需要 FreeType 带 brotli 支持（Pillow 9+ 官方 wheel 一般都有，
    但老环境可能没有）。不试的话会等到整张卡渲染时才炸，用户只能拿到纯文本兜底。
    加载结果进 _font_cache，不会重复解析。
    """
    try:
        _font(path, 20)
        return True
    except Exception:
        return False


def find_font(explicit: str | None = None, extra_dirs=None) -> str | None:
    """多级查找：显式路径 → extra_dirs 下的 ttf/otf/ttc/woff2 → 系统候选。

    每个候选先试加载（见 _font_loadable），读不了就跳到下一个。找不到返回 None。
    emoji / symbol / icon 类字体直接跳过——它们没有中文字形，被选中会渲染出一片空白
    （萌萌资料卡目录里就有 NotoColorEmoji.ttf，字母序还排在圆体前面，v1.9.6 踩过）。
    """
    candidates: list = []
    if explicit:
        candidates.append(explicit)
    for d in extra_dirs or []:
        p = Path(d)
        if p.is_dir():
            for pat in ("*.ttf", "*.otf", "*.ttc", "*.woff2"):
                for x in sorted(p.glob(pat)):
                    if any(h in x.name.lower() for h in _SKIP_FONT_NAME_HINTS):
                        continue
                    candidates.append(str(x))
    candidates += _SYSTEM_FONT_CANDIDATES
    for c in candidates:
        if c and Path(c).is_file() and _font_loadable(c):
            return c
    return None


# 用户输入（QQ 昵称等）里的危险空白：换行/制表符会把单行排版撑破，
# 零宽字符等不可见字符会画出看不见的东西（v1.10.2）
_ZW_RE = re.compile(r"[\u200b-\u200f\u2028\u2029\u2060\ufeff]")  # 零宽类：直接删除
_BAD_WS_RE = re.compile(r"\s+")  # 其余空白（含换行/制表）：压成单个空格


def sanitize_name(text, max_len: int = 16) -> str:
    """清洗昵称类用户输入：删零宽字符、空白压成单个空格并限长。

    QQ 昵称什么都能塞：换行、制表符、零宽连接符都见过——直接上卡会把单行
    排版撑破或渲染出看不见的字符。这里统一压平 + 截断（超长加省略号）。
    所有把昵称画上卡片的入口都必须先过这个函数。
    """
    cleaned = _BAD_WS_RE.sub(" ", _ZW_RE.sub("", str(text or ""))).strip()
    if len(cleaned) > max_len:
        cleaned = cleaned[: max_len - 1].rstrip() + "…"
    return cleaned


# 不能当正文用的字体名特征（emoji/symbol/icon 字体没有中文字形）
_SKIP_FONT_NAME_HINTS = ("emoji", "symbol", "icon")
_FONT_PATTERNS = ("*.ttf", "*.otf", "*.ttc", "*.woff2")


def font_dirs(data_dir) -> list:
    """卡片字体候选目录（v1.9.9）。

    只认两个位置，**不依赖任何其它插件**：
      1. 插件自己的数据目录 `data/plugin_data/<插件名>/fonts/`；
      2. AstrBot 的公共字体目录 `data/fonts/`——由数据目录反推两级得到（不依赖进程 cwd），
         另外补一条 `data/fonts` 相对写法兜底（cwd 恰好不是 AstrBot 根目录时也能命中）。

    返回顺序即优先级；两处都没有可用字体时，由 `find_font` 继续走系统字体候选。
    """
    d = Path(data_dir)
    out = [d / "fonts", d.parent.parent / "fonts"]
    legacy = Path("data/fonts")
    if legacy not in out:
        out.append(legacy)
    return out


def _iter_font_files(dirs):
    """遍历候选目录里的字体文件（跳过 emoji/symbol/icon 类，v1.9.9）。"""
    for d in dirs or []:
        p = Path(d)
        if not p.is_dir():
            continue
        for pat in _FONT_PATTERNS:
            for x in sorted(p.glob(pat)):
                if any(skip in x.name.lower() for skip in _SKIP_FONT_NAME_HINTS):
                    continue
                yield x


def _norm_font_name(text: str) -> str:
    """字体名归一化：小写 + 去掉空格/连字符/下划线/点，用于模糊匹配（v1.9.9）。"""
    return re.sub(r"[\s\-_.]+", "", str(text).lower())


def list_fonts_by_hint(dirs, hints=("rounded",)) -> list[str]:
    """列出候选目录里**文件名匹配**的字体（不校验可否加载，供排查日志用，v1.9.8）。

    区分「没有这个字体」和「有这个字体但本机读不了」——后者要提示用户换格式
    （woff2 需要 FreeType 带 brotli 支持），两者对用户的处置方式完全不同。
    """
    hints = tuple(str(h).lower() for h in hints)
    return [str(x) for x in _iter_font_files(dirs)
            if any(h in x.name.lower() for h in hints)]


def find_font_by_hint(dirs, hints=("rounded",)) -> str | None:
    """在候选目录里按**文件名关键词**挑一个可用字体（v1.9.7，圆体风格用）。

    与 `find_font` 的分工：`find_font` 取目录里字典序第一个可用字体（默认风格用）；
    这里要的是「名字对得上」的那个——使用者可能把圆体、黑体、楷体一起丢进
    公共字体目录，只有按名字挑才能稳定拿到想要的圆体。

    字体放哪完全由使用者决定（推荐 AstrBot 的 `data/fonts/` 公共目录），
    插件不借用、也不依赖任何其它插件的字体。
    """
    for c in list_fonts_by_hint(dirs, hints):
        if _font_loadable(c):
            return c
    return None


def resolve_font(spec: str, dirs=None) -> tuple[str | None, str]:
    """把配置里的「字体」解析成可加载的文件路径，返回 `(路径 | None, 说明)`（v1.9.9）。

    `spec` 支持三种写法，按下列顺序尝试：
      1. **路径**（含 `/`、`\\`，或以 `~` 开头，或带字体扩展名）：
         `/AstrBot/data/fonts/x.ttf`、`./fonts/x.ttf`、`ResourceHanRoundedCN-Medium.woff2`；
      2. **文件名**：与候选目录里的文件同名（忽略大小写）；
      3. **字体名**：归一化后做子串匹配（忽略大小写/空格/连字符/下划线/点），
         `Resource Han Rounded`、`resourcehanrounded` 都能命中 `ResourceHanRoundedCN-Medium.woff2`。

    第 1 步没命中会继续走 2/3 —— 用户只写文件名时也能在候选目录里找到。
    说明文本用于日志，解释「为什么没用上」。
    """
    spec = str(spec or "").strip()
    if not spec:
        return None, "字体未配置"
    dirs = list(dirs or [])
    tried_path = ""
    looks_like_path = ("/" in spec) or ("\\" in spec) or spec.startswith("~")
    if looks_like_path or Path(spec).suffix.lower() in (".ttf", ".otf", ".ttc", ".woff2"):
        p = Path(spec).expanduser()
        if p.is_file():
            if _font_loadable(str(p)):
                return str(p), "按路径命中"
            return None, f"文件存在但本机无法加载：{p.name}（woff2 需要 FreeType 带 brotli 支持）"
        tried_path = str(p)

    candidates = list(_iter_font_files(dirs))
    want_file = spec.lower()
    want_names = {_norm_font_name(spec), _norm_font_name(Path(spec).stem)}
    broken: list[str] = []

    # 2) 文件名精确匹配先于 3) 字体名模糊匹配：多目录时精确命中不会被模糊结果抢走
    for x in candidates:
        if x.name.lower() == want_file:
            if _font_loadable(str(x)):
                return str(x), "按文件名命中"
            broken.append(x.name)
    for x in candidates:
        norm = _norm_font_name(x.stem)
        if any(w and w in norm for w in want_names):
            if _font_loadable(str(x)):
                return str(x), "按字体名命中"
            broken.append(x.name)

    if broken:
        return None, (f"匹配到 {broken} 但本机无法加载"
                      "（woff2 需要 FreeType 带 brotli 支持，建议改用 ttf/otf/ttc）")
    where = [str(d) for d in dirs]
    if tried_path:
        return None, f"路径不存在：{tried_path}；候选目录 {where} 里也没有匹配的字体"
    return None, (f"候选目录 {where} 里没有名为 {spec} 的字体"
                  "（可填文件名或字体名，如 Resource Han Rounded）")


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
    """展示字体：楷体/宋体系（命签感），都没有则退回粗体变体。

    例外：圆体（如 Resource Han Rounded，`card_font_style=rounded`）本身就是完整风格，
    直接沿用不替换——否则会出现「圆体正文 + 楷体标题」的割裂感（v1.9.6）。
    """
    if "rounded" in Path(str(font_file)).name.lower():
        return font_file
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


def _fit_text(text: str, font: ImageFont.FreeTypeFont, max_width: int) -> str:
    """按像素宽度截断并补省略号（二分回退）；放不下一个字符时返回空串。

    v1.9.5 新增：榜单里昵称会跟右侧分数抢位置，标题会跟右上角日期抢位置，
    统一用「量宽 + 截断」而不是硬排版，宽度不够也不会叠字。
    """
    text = str(text)
    if max_width <= 0:
        return ""
    if draw_len(text, font) <= max_width:
        return text
    ell = "…"
    lo, hi = 0, len(text)
    while lo < hi:
        mid = (lo + hi + 1) // 2
        if draw_len(text[:mid] + ell, font) <= max_width:
            lo = mid
        else:
            hi = mid - 1
    return (text[:lo] + ell) if lo > 0 else ""


def _cover(img: Image.Image, w: int, h: int) -> Image.Image:
    """等比 cover 裁切到目标尺寸（理想情况底图尺寸已与卡布一致，仅兜底）。"""
    sw, sh = img.size
    scale = max(w / sw, h / sh)
    nw, nh = round(sw * scale), round(sh * scale)
    img = img.resize((nw, nh))
    left, top = (nw - w) // 2, (nh - h) // 2
    return img.crop((left, top, left + w, top + h))


def _contain(img: Image.Image, w: int, h: int, fill_rgb: tuple) -> Image.Image:
    """等比缩放到完全放入目标框（不裁切），居中放置，空隙填底色——塔罗牌面专用。"""
    sw, sh = img.size
    scale = min(w / sw, h / sh)
    nw, nh = max(1, round(sw * scale)), max(1, round(sh * scale))
    img = img.resize((nw, nh))
    out = Image.new("RGB", (w, h), fill_rgb)
    out.paste(img, ((w - nw) // 2, (h - nh) // 2))
    return out


def _circle_img(img: Image.Image, diameter: int) -> Image.Image:
    img = img.resize((diameter, diameter))
    mask = Image.new("L", (diameter * 4, diameter * 4), 0)
    ImageDraw.Draw(mask).ellipse((0, 0, diameter * 4 - 1, diameter * 4 - 1), fill=255)
    mask = mask.resize((diameter, diameter))
    out = Image.new("RGBA", (diameter, diameter), (0, 0, 0, 0))
    out.paste(img, (0, 0), mask)
    return out


def _gradient(w: int, h: int, base_rgb: tuple, dark: bool = False,
              top_mix: float | None = None, bottom_mix: float | None = None,
              dark_rgb: tuple = (24, 25, 38)) -> Image.Image:
    """纵向渐变：light=白底混幸运色；dark=暗夜底混幸运色。混合度可调。"""
    if dark:
        top = _mix(base_rgb, dark_rgb, top_mix if top_mix is not None else 0.86)
        bottom = _mix(base_rgb, dark_rgb, bottom_mix if bottom_mix is not None else 0.94)
    else:
        top = _mix(base_rgb, (255, 255, 255), top_mix if top_mix is not None else 0.74)
        bottom = _mix(base_rgb, (255, 255, 255), bottom_mix if bottom_mix is not None else 0.92)
    img = Image.new("RGB", (1, h))
    px = img.load()
    for y in range(h):
        t = y / max(1, h - 1)
        px[0, y] = _mix(top, bottom, t)
    return img.resize((w, h))


def _panel_base(w: int, h: int, base_rgb: tuple, dark: bool, radius: int,
                dark_rgb: tuple = (24, 25, 38)) -> Image.Image:
    """圆角面板的幸运色渐变底（顶浓底淡、全不透明）——告别纯白。"""
    grad = _gradient(w, h, base_rgb, dark=dark,
                     top_mix=(0.78 if dark else 0.52),
                     bottom_mix=(0.92 if dark else 0.90),
                     dark_rgb=dark_rgb).convert("RGBA")
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
    tarot_label_on_image: bool = False,
    stardust_today: int | None = None,
    stardust_total: int | None = None,
) -> str:
    """渲染当日星语签，落盘 cards_root/<date>.png 并返回路径。失败抛异常由调用方回退。"""
    nickname = sanitize_name(nickname)
    font_file = find_font(font_path, extra_font_dirs)
    if not font_file:
        raise RuntimeError("未找到可用中文字体")

    # 塔罗双联模式（M8）：有 AI 牌面图 + 塔罗信息时走左右合成版式
    if bg_image and Path(bg_image).exists() and result.get("tarot"):
        return render_tarot_card(
            result, str(bg_image), cards_root, font_file,
            width=int(width), height=int(height),
            signer=str(signer), nickname=nickname,
            avatar_data=avatar_data, uid=str(uid or ""),
            theme=str(theme or "light"),
            tarot_label_on_image=bool(tarot_label_on_image),
            stardust_today=stardust_today, stardust_total=stardust_total,
        )

    SW, H_cfg = int(width), int(height)
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

    # 内容感知画布（M9 布局修复）：塔罗行/四件套/星尘行叠加后块高常超出配置高度，
    # 先按各区块标称高度实测，画布不够就自动加高（配置值仍是最小高度），不再截断。
    margin = int(56 * u)
    pad = int(48 * u)
    inner_w = W - 2 * margin - 2 * pad
    _tarot_row = result.get("tarot")
    _sign_n = min(5, len(_wrap(str(result.get("sign_text", "")),
                               _font(font_file, int(40 * u)), inner_w)))
    _dims = result.get("dims") or {}
    _dims_rows = (len(_dims) + 1) // 2
    _est = u * (28 + 162 + 20 + (78 if _tarot_row else 0) + 168 + _sign_n * 58 + 20
                + _dims_rows * 58 + 18 + 140 + 126 + 180 + (44 if stardust_total is not None else 0)
                + 132)  # 132 = 脚注区（96 单行基准 + 36 预留第二行）
    H = max(H_cfg, 2 * margin + int(_est) + int(96 * u) + int(14 * u))

    base = _gradient(W, H, lucky_rgb, dark=dark).convert("RGBA")
    deco = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    dd = ImageDraw.Draw(deco)
    _sparkle(dd, W * 0.14, H * 0.08, 16 * u, lucky_rgb, 90)
    _sparkle(dd, W * 0.86, H * 0.16, 12 * u, lucky_rgb, 80)
    _sparkle(dd, W * 0.10, H * 0.30, 9 * u, lucky_rgb, 70)
    img = Image.alpha_composite(base, deco)

    panel = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    ImageDraw.Draw(panel).rounded_rectangle(
        [margin, margin, W - margin, H - margin],
        radius=int(44 * u), fill=panel_fill,
    )
    img = Image.alpha_composite(img, panel)
    draw = ImageDraw.Draw(img)

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
    line_h = int(58 * u)
    for line in sign_lines:
        draw.text((W // 2, y), line, font=_font(font_file, int(40 * u)), fill=ink, anchor="ma")
        y += line_h
    y += int(20 * u)

    # ⑤ 六维星数（2 列 × 3 行）
    dims = result.get("dims") or {}
    cell_w = inner_w / 2
    for i, (k, v) in enumerate(dims.items()):
        cx = left + cell_w * (i % 2) + int(16 * u)
        cy = y + (i // 2) * int(58 * u)
        draw.text((cx, cy), k, font=_font(font_file, int(32 * u)), fill=sub)
        stars = "★" * v + "☆" * (5 - v)
        draw.text((cx + int(140 * u), cy), stars,
                  font=_font(font_file, int(34 * u)), fill=grade_rgb)
    rows = (len(dims) + 1) // 2
    y += int(58 * u) * rows + int(18 * u)

    # ⑥ 幸运指数（大数字，档位色）
    draw.text((W // 2, y + int(6 * u)), "幸运指数",
              font=_font(font_file, int(30 * u)), fill=sub, anchor="ma")
    draw.text((W // 2, y + int(44 * u)), str(result.get("score", "？")),
              font=_font(_bold_variant(font_file), int(92 * u)), fill=grade_rgb, anchor="ma")
    y += int(140 * u)

    # ⑦ 宜忌（彩色圆角章 + 内容）
    for label, items, rgb in (("宜", result.get("yi") or [], (122, 178, 138)),
                              ("忌", result.get("ji") or [], (216, 128, 128))):
        chip_w, chip_h = int(76 * u), int(48 * u)
        draw.rounded_rectangle([left, y, left + chip_w, y + chip_h],
                               radius=int(14 * u), fill=_mix(rgb, (255, 255, 255), 0.35) + (255,))
        draw.text((left + chip_w / 2, y + chip_h / 2), label,
                  font=_font(font_file, int(34 * u)), fill=(255, 255, 255, 255), anchor="mm")
        draw.text((left + chip_w + int(28 * u), y + chip_h / 2), "、".join(items),
                  font=_font(font_file, int(36 * u)), fill=ink, anchor="lm")
        y += chip_h + int(12 * u)
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
        cy = y + (i // 2) * int(88 * u)
        draw.text((cx, cy), label, font=_font(font_file, int(28 * u)), fill=sub)
        draw.text((cx, cy + int(34 * u)), value,
                  font=_font(font_file, int(38 * u)), fill=ink)
    y += int(88 * u) * 2 + int(4 * u)

    # ⑧.5 星尘行（M9：今日获得 + 累计；经济关闭或调用方未传时不画）
    gold_soft = (176, 142, 48) if not dark else (222, 186, 84)
    if stardust_total is not None:
        y = min(y, H - margin - int(134 * u))
        sd_line = (
            f"★ 今日星尘 +{stardust_today} ｜ 累计 {stardust_total}"
            if (stardust_today or 0) > 0 else f"★ 累计星尘 {stardust_total}"
        )
        draw.text((W // 2, y), sd_line,
                  font=_font(font_file, int(30 * u)), fill=gold_soft, anchor="ma")
        y += int(44 * u)

    # ⑨ 脚注（超宽自动换行，最多两行）+ 落款
    phase = result.get("phase") or {}
    foot = f"月相：{phase.get('name', '？')}——{phase.get('text', '')}"
    streak = result.get("streak") or 0
    if streak >= 2:
        foot += f" ｜ 连签 {streak} 天"
    foot_lines = _wrap(foot, _font(font_file, int(26 * u)), inner_w)[:2]
    y = min(y, H - margin - int(96 * u) - int(34 * u) * (len(foot_lines) - 1))
    for i, line in enumerate(foot_lines):
        draw.text((W // 2, y + i * int(34 * u)), line,
                  font=_font(font_file, int(26 * u)), fill=sub, anchor="ma")
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
    tarot_label_on_image: bool = False,
    stardust_today: int | None = None,
    stardust_total: int | None = None,
) -> str:
    """塔罗双联版式（M8/M8.5）：左联 AI 牌面 + 右联运势面板。

    右联为幸运色渐变圆角面板（顶浓底淡），布局按「固定块高 + 弹性间隙」
    等分剩余空间——不留大片空白也不挤压；吉凶/牌名用楷体系展示字体。
    """
    nickname = sanitize_name(nickname)  # render_card 已清洗，此处兜底直接调用
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

    canvas = Image.new("RGBA", (W, H), (8, 8, 12, 255))

    # ---- 左联：AI 牌面（塔罗框 + 底部牌名条） ----
    side = _contain(Image.open(bg_image).convert("RGB"), SW, H, (8, 8, 12)).convert("RGBA")
    canvas.paste(side, (0, 0))
    sdraw = ImageDraw.Draw(canvas)
    sdraw.rectangle([6, 6, SW - 7, H - 7], outline=gold + (235,), width=max(2, int(3 * u)))
    sdraw.rectangle([int(12 * u), int(12 * u), SW - int(13 * u), H - int(13 * u)],
                    outline=gold + (150,), width=1)
    tarot = result.get("tarot") or {}
    if tarot_label_on_image:
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
    bw = int(10 * u)
    pw, ph = SW - bw * 2, H - bw * 2
    panel = _panel_base(pw, ph, lucky_rgb, dark, 0)
    canvas.paste(panel, (SW + bw, bw))
    draw = ImageDraw.Draw(canvas)
    # 塔罗式双线金框：画在内嵌面板边缘，金边之外露黑
    draw.rectangle([SW + bw, bw, W - bw, H - bw], outline=gold + (235,), width=max(2, int(3 * u)))
    draw.rectangle([SW + bw + int(6 * u), bw + int(6 * u), W - bw - int(6 * u), H - bw - int(6 * u)],
                   outline=gold + (150,), width=1)
    _sparkle(draw, SW + (W - SW) * 0.5, int(18 * u), int(9 * u), gold, 220)

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
            draw.text((cx + cw - int(8 * u), cy + int(10 * u)), note,
                      font=_font(font_file, int(17 * u)), fill=sub, anchor="ra")
    block(int(2 * (64 * u + 10 * u)), b_lucky)

    # ⑧.5 星尘（M9：今日获得 + 累计；经济关闭或调用方未传时不画）
    gold_soft = (222, 186, 84) if dark else (176, 142, 48)
    if stardust_total is not None:
        def b_stardust(y):
            cy = y + int(30 * u)
            draw.text((left, cy), "星尘", font=_font(font_file, int(24 * u)), fill=sub, anchor="lm")
            if (stardust_today or 0) > 0:
                draw.text((left + int(84 * u), cy), f"+{stardust_today}",
                          font=_font(disp, int(46 * u)), fill=gold_soft, anchor="lm")
                draw.text((left + int(84 * u) + draw_len(f"+{stardust_today}", _font(disp, int(46 * u))) + int(14 * u), cy),
                          "今日获得", font=_font(font_file, int(20 * u)), fill=sub, anchor="lm")
            draw.text((right, cy), f"累计 {stardust_total}",
                      font=_font(font_file, int(26 * u)), fill=ink, anchor="rm")
        block(int(60 * u), b_stardust)

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


def render_help_card(
    groups: list,
    cards_root,
    font_path: str | None = None,
    extra_font_dirs=None,
    width: int = 960,
    signer: str = "星语者",
    subtitle: str = "萌萌星语 · 每日运势签",
    footer: str = "从 /星语 开始 · 每天一支专属星语签",
    accent_hex: str = "#F6C6D3",
    theme: str = "light",
) -> str:
    """帮助图（v1.8.5 重排）：与提示卡同族版式——渐变底座 + 分组节面板。

    groups: [(组名, [(指令, 说明), ...]), ...]；
    行内指令列按节内最宽指令对齐（强调色粗体），说明按剩余宽度折行；
    字号固定大字号（v1.8.4 起），画布宽度按内容自适应收窄（v1.8.5：
    固定 1120 宽右侧留大片空白；width 参数只是上限，下限 820）；
    高度随内容自适应，文件名固定 help.png。
    页脚 footer 是发给群友看的引导语，不要放管理员向内容（配置页他们进不去）。
    """
    font_file = find_font(font_path, extra_font_dirs)
    if not font_file:
        raise RuntimeError("未找到可用中文字体")
    dark = str(theme or "light").lower() == "dark"
    probe = ImageDraw.Draw(Image.new("RGBA", (8, 8)))
    # 字号固定（不随画布缩放）；画布宽度按内容自适应收窄
    f_cmd = _font(_bold_variant(font_file), 17)
    f_desc = _font(font_file, 15)
    f_lab = _font(_display_font_file(font_file), 22)
    sec_pad, head_h, row_lh, row_gap, sec_gap = 16, 34, 22, 7, 15
    inner_pad = 176  # 底座左右留白合计的标称值（900 宽时）

    def _natural_row_widths() -> int:
        """按「说明不折行」估最宽行（第一遍，用于收窄画布）。"""
        max_row = 0
        for _title, rows in groups:
            col = 0
            for cmd, _d in rows:
                cmd = str(cmd or "").strip()
                if cmd:
                    col = max(col, probe.textlength(cmd, font=f_cmd))
            col = min(int(col) + 20, int(728 * 0.55))
            for cmd, desc in rows:
                cmd, desc = str(cmd or "").strip(), str(desc or "").strip()
                if cmd and desc:
                    row_w = col + min(probe.textlength(desc, font=f_desc), 728 - col)
                elif desc:
                    row_w = min(probe.textlength(desc, font=f_desc), 728)
                else:
                    row_w = col
                max_row = max(max_row, row_w)
        return max_row

    natural = _natural_row_widths()
    width = int(min(max(820, natural + inner_pad), max(820, width)))
    u0 = width / 900.0
    inner_w = int(width - (44 + 42) * 2 * u0)
    cmd_col_cap = int(inner_w * 0.55)

    # ---- 第二遍（真实内容区）：指令列宽取节内最宽指令，说明按剩余宽度折行 ----
    sec_geo: list[tuple[int, str, list[tuple[str, str, list[str]]], int]] = []
    for title, rows in groups:
        col = 0
        for cmd, _desc in rows:
            cmd = str(cmd or "").strip()
            if cmd:
                col = max(col, probe.textlength(cmd, font=f_cmd))
        col = min(int(col) + 20, cmd_col_cap)
        rows_geo: list[tuple[str, str, list[str]]] = []
        for cmd, desc in rows:
            cmd, desc = str(cmd or "").strip(), str(desc or "").strip()
            if cmd and desc:
                lines = _wrap(desc, f_desc, inner_w - col)
            elif desc:
                lines = _wrap(desc, f_desc, inner_w)
            else:
                lines = []
            rows_geo.append((cmd, desc, lines))
        h = sec_pad + head_h
        for _cmd, _desc, lines in rows_geo:
            h += max(26, row_lh * max(1, len(lines)) + 6) + row_gap
        h += sec_pad - row_gap
        sec_geo.append((h, title, rows_geo, col))

    H = int((218 + 12) * u0 + sum(h for h, _t, _r, _c in sec_geo)
            + sec_gap * max(0, len(sec_geo) - 1) + (96 + 14) * u0)
    ctx = _utility_card_base(width, H, accent_hex, font_file,
                             subtitle=subtitle, title="星语帮助", dark=dark, theme=theme)
    draw, u, ff = ctx["draw"], ctx["u"], ctx["font_file"]
    left, right = ctx["left"], ctx["right"]
    y = ctx["y"]
    disp = ctx["disp"]
    sec_bg = _mix(ctx["accent"], (255, 255, 255) if not dark else (30, 30, 48),
                  0.6 if not dark else 0.86) + (190,)
    sec_border = _mix(ctx["accent"], (74, 74, 96) if not dark else (232, 230, 240), 0.6) + (255,)
    cmd_rgb = _mix(ctx["accent"], (232, 230, 240) if dark else (56, 48, 66), 0.45)
    badge_rgb = _mix(ctx["accent"], (74, 74, 96) if not dark else (232, 230, 240), 0.4) + (255,)

    for h, title, rows_geo, col in sec_geo:
        draw.rounded_rectangle([left, y, right, y + h], radius=int(14 * u),
                               fill=sec_bg, outline=sec_border, width=1)
        # 组头：强调色竖条 + 组名（展示字体）+ 细分隔线
        iy = y + sec_pad
        draw.rounded_rectangle([left + int(16 * u), iy + int(2 * u),
                                left + int(22 * u), iy + int(24 * u)],
                               radius=int(3 * u), fill=badge_rgb)
        draw.text((left + int(32 * u), iy), str(title), font=f_lab, fill=ctx["ink"])
        lab_w = draw_len(str(title), f_lab)
        ly = iy + int(13 * u)
        draw.line([(left + int(44 * u) + lab_w, ly), (right - int(16 * u), ly)],
                  fill=sec_border, width=1)
        ry = iy + head_h
        for cmd, _desc, lines in rows_geo:
            row_h = max(26, row_lh * max(1, len(lines)) + 6)
            if cmd:
                draw.text((left + int(18 * u), ry), cmd, font=f_cmd, fill=cmd_rgb)
            dx = left + int(18 * u) + (col if cmd else 0)
            for i, ln in enumerate(lines):
                draw.text((dx, ry + i * row_lh), ln, font=f_desc, fill=ctx["sub"])
            ry += row_h + row_gap
        y += h + sec_gap

    # 文件名带主题（v1.10.3）：换了风格就是新文件，QQ/协议端不会拿旧缓存图充数
    return _utility_card_save(ctx, cards_root,
                              f"help_{str(theme or 'light').strip().lower()}.png",
                              signer, footer=footer)


# ---------------------------------------------------------------------- #
# 提示卡（M9）：星尘钱包 / 道具商店 / 星语榜 / PK / 通用通知 / 运势日历
# 共用底座：渐变背景 + 圆角面板 + 星饰 + 标题区，风格与运势卡同源
# ---------------------------------------------------------------------- #

# 日历格的吉凶配色（与词库 grade_colors 同值；调用方会传词库覆盖）
_CALENDAR_GRADE_COLORS = {
    "大吉": "#E86A8A", "吉": "#F0A0B8", "中吉": "#E8C46A",
    "小吉": "#A8C8E8", "凶": "#9BA8B8", "大凶": "#7A86A8",
}


def _draw_card_frame(draw, W: int, H: int, style: str, accent_rgb: tuple, u: float) -> None:
    """提示卡外框装饰（v1.10.3）：随主题变化，不只是换颜色。

    soft  = light/dark 默认，维持原观感（不画外框）
    tarot = 塔罗牌风：金色双线框 + 四角小星
    dots  = 樱花：细圆角框 + 四角双圆环
    frame = 薄荷：单细圆角框
    """
    if style == "tarot":
        gold = (212, 175, 55)
        i1, i2 = int(10 * u), int(18 * u)
        draw.rectangle([i1, i1, W - i1, H - i1], outline=gold + (235,), width=max(2, int(2.5 * u)))
        draw.rectangle([i2, i2, W - i2, H - i2], outline=gold + (120,), width=1)
        for cx, cy in ((i2, i2), (W - i2, i2), (i2, H - i2), (W - i2, H - i2)):
            _sparkle(draw, cx, cy, 7 * u, gold, 230)
    elif style == "dots":
        c = accent_rgb + (170,)
        i = int(12 * u)
        draw.rounded_rectangle([i, i, W - i, H - i], radius=int(10 * u), outline=c, width=1)
        r = int(4 * u)
        for cx, cy in ((i, i), (W - i, i), (i, H - i), (W - i, H - i)):
            draw.ellipse([cx - 2 * r, cy - 2 * r, cx + 2 * r, cy + 2 * r], outline=c, width=1)
    elif style == "frame":
        i = int(12 * u)
        draw.rounded_rectangle([i, i, W - i, H - i], radius=int(8 * u),
                               outline=accent_rgb + (150,), width=max(1, int(1.5 * u)))
    # soft：不画外框


# 提示卡主题表（v1.10.3）：不只是换色——底色、面板、文字、线条、边框装饰一起变。
# accent 固定的主题（tarot）会用主题色替换幸运色，避免金框配粉底不伦不类。
_THEME_DEFS = {
    "light": dict(dark=False, border="soft"),
    "dark": dict(dark=True, border="soft"),
    "tarot": dict(dark=True, border="tarot", dark_rgb=(28, 24, 42),
                  ink=(238, 226, 200), sub=(176, 160, 134), line=(120, 104, 74, 255),
                  accent="#D4AF37"),
    "sakura": dict(dark=False, border="dots",
                   ink=(96, 62, 80), sub=(176, 130, 150), line=(247, 186, 207, 255)),
    "mint": dict(dark=False, border="frame",
                 ink=(48, 92, 76), sub=(124, 166, 148), line=(140, 205, 178, 255)),
}


def _utility_card_base(
    width: int,
    height: int,
    accent_hex: str,
    font_file: str,
    subtitle: str,
    title: str,
    dark: bool = False,
    title_right: str = "",
    theme: str = "",
) -> dict:
    """提示卡通用底座：渐变背景 + 圆角面板 + 星饰 + 标题区 + 主题化外框。

    theme 优先于 dark：在 _THEME_DEFS 里登记的主题（tarot/sakura/mint）会连
    边框与装饰一起换；light/dark/auto/未知值保持原观感。
    返回 ctx 字典（img/draw/left/right/y/u/ink/sub/disp/accent/line/W/H/margin/
    font_file），内容从 ctx["y"] 起画，收尾调 _utility_card_save。
    """
    W, H = int(width), int(height)
    u = W / 900.0
    tdef = _THEME_DEFS.get(str(theme or "").strip().lower())
    if tdef is None:
        tdef = _THEME_DEFS["dark" if dark else "light"]
    dark = bool(tdef["dark"])
    dark_rgb = tuple(tdef.get("dark_rgb") or (24, 25, 38))
    accent = _hex_rgb(tdef["accent"]) if tdef.get("accent") else _hex_rgb(accent_hex)
    if tdef.get("ink"):
        ink, sub = tuple(tdef["ink"]), tuple(tdef["sub"])
    elif dark:
        ink, sub = (232, 230, 240), (158, 160, 178)
    else:
        ink, sub = (74, 74, 96), (150, 150, 168)
    if tdef.get("line"):
        line_rgb = tuple(tdef["line"])
    else:
        line_rgb = (62, 63, 80, 255) if dark else (238, 236, 242, 255)
    img = _gradient(W, H, accent, dark=dark, dark_rgb=dark_rgb).convert("RGBA")
    deco = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    dd = ImageDraw.Draw(deco)
    # 星饰放在面板外的上下留白条里，避免被面板边缘切出一半像缺口
    _sparkle(dd, W * 0.80, int(20 * u), 11 * u, accent, 110)
    _sparkle(dd, W * 0.16, H - int(20 * u), 8 * u, accent, 90)
    img = Image.alpha_composite(img, deco)
    margin = int(44 * u)
    panel = _panel_base(W - 2 * margin, H - 2 * margin, accent, dark, int(36 * u),
                        dark_rgb=dark_rgb)
    img.paste(panel, (margin, margin), panel)
    draw = ImageDraw.Draw(img)
    _draw_card_frame(draw, W, H, str(tdef.get("border") or "soft"), accent, u)
    left, right = margin + int(42 * u), W - margin - int(42 * u)
    y = margin + int(32 * u)
    disp = _display_font_file(font_file)
    meta_font = _font(font_file, int(25 * u))
    draw.text((left, y), subtitle, font=meta_font, fill=sub)
    # 右侧信息（日期）固定右上角、与副标题同一行：早先跟大标题挤在同一行，
    # 标题一长就叠在一起（v1.9.5 修）
    right_text = str(title_right or "")
    right_w = 0.0
    if right_text:
        right_w = draw_len(right_text, meta_font)
        draw.text((right, y), right_text, font=meta_font, fill=sub, anchor="ra")
    # 大标题按剩余宽度自适应：先逐档缩字号，仍然放不下才截断
    avail = right - left - (int(right_w) + int(28 * u) if right_text else 0)
    avail = max(int(150 * u), int(avail))
    title_size = int(56 * u)
    title_font = _font(disp, title_size)
    while title_size > int(34 * u) and draw_len(str(title), title_font) > avail:
        title_size -= int(4 * u)
        title_font = _font(disp, title_size)
    title_text = _fit_text(str(title), title_font, avail)
    draw.text((left, y + int(34 * u)), title_text, font=title_font, fill=ink)
    y += int(116 * u)
    draw.line([(left, y), (right, y)], fill=line_rgb, width=max(1, int(2 * u)))
    y += int(24 * u)
    return {
        "img": img, "draw": draw, "left": left, "right": right, "y": y, "u": u,
        "ink": ink, "sub": sub, "disp": disp, "accent": accent,
        "line": line_rgb, "W": W, "H": H, "margin": margin, "font_file": font_file,
    }


def _utility_card_save(ctx: dict, cards_root, filename: str, signer: str,
                       footer: str = "") -> str:
    """提示卡收尾：左下脚注（可选）+ 右下落款 + 落盘，返回路径。"""
    draw, u, ff = ctx["draw"], ctx["u"], ctx["font_file"]
    fy = ctx["H"] - ctx["margin"] - int(24 * u)
    if footer:
        draw.text((ctx["left"], fy), footer,
                  font=_font(ff, int(22 * u)), fill=ctx["sub"], anchor="ls")
    draw.text((ctx["right"], fy), f"—— {signer}",
              font=_font(ff, int(26 * u)), fill=ctx["sub"], anchor="rs")
    cards_root = Path(cards_root)
    cards_root.mkdir(parents=True, exist_ok=True)
    out = cards_root / filename
    ctx["img"].convert("RGB").save(out, "PNG")
    return str(out)


def _identity_row(ctx: dict, nickname: str, uid: str, avatar_data) -> None:
    """提示卡身份行：圆头像 + 昵称 + QQ 号（推进 ctx["y"]）。"""
    nickname = sanitize_name(nickname)
    img, draw, u, ff = ctx["img"], ctx["draw"], ctx["u"], ctx["font_file"]
    left, y = ctx["left"], ctx["y"]
    av_d = int(88 * u)
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
                                _mix(ctx["accent"], (255, 255, 255), 0.35) + (255,))
        ImageDraw.Draw(placeholder).text(
            (av_d, av_d), (nickname or "星")[0],
            font=_font(ff, int(60 * u)), fill=(255, 255, 255, 255), anchor="mm")
        avatar_img = _circle_img(placeholder, av_d)
    img.paste(avatar_img, (left, y), avatar_img)
    tx = left + av_d + int(26 * u)
    draw.text((tx, y + int(4 * u)), nickname or "旅行者",
              font=_font(ff, int(38 * u)), fill=ctx["ink"])
    if uid:
        draw.text((tx, y + int(54 * u)), f"QQ {uid}",
                  font=_font(ff, int(22 * u)), fill=ctx["sub"])
    ctx["y"] = y + av_d + int(24 * u)


def render_wallet_card(
    nickname: str,
    balance: int,
    items: list,
    cards_root,
    file_key: str = "wallet",
    uid: str = "",
    avatar_data: bytes | None = None,
    today_gain: int | None = None,
    date_str: str = "",
    accent_hex: str = "#F6C6D3",
    hint: str = "购买与使用：/星语商店 · /星语使用",
    font_path: str | None = None,
    extra_font_dirs=None,
    signer: str = "星语者",
    width: int = 900,
    theme: str = "light",
) -> str:
    """星尘钱包卡：余额大数字 + 今日获得 + 背包 2×2 持有格。items=[(名称, 数量)]。"""
    font_file = find_font(font_path, extra_font_dirs)
    if not font_file:
        raise RuntimeError("未找到可用中文字体")
    dark = str(theme or "light").lower() == "dark"
    u0 = width / 900.0
    grid_rows = (len(items) + 1) // 2
    # 版式高度 = 标题区 218 + 身份行 112 + 余额块 171 + 小标题 44 + 网格 + 底部 96
    H = int((218 + 112 + 171 + 44 + grid_rows * 100 + 96) * u0)
    ctx = _utility_card_base(width, H, accent_hex, font_file,
                             subtitle="萌萌星语 · 道具经济", title="星尘钱包",
                             dark=dark, title_right=date_str, theme=theme)
    _identity_row(ctx, nickname, uid, avatar_data)
    draw, u, ff = ctx["draw"], ctx["u"], ctx["font_file"]
    left, right = ctx["left"], ctx["right"]
    y = ctx["y"]
    gold_soft = (222, 186, 84) if dark else (176, 142, 48)

    draw.line([(left, y), (right, y)], fill=ctx["line"], width=1)
    y += int(21 * u)
    draw.text((left, y), "星尘余额", font=_font(ff, int(26 * u)), fill=ctx["sub"])
    big_font = _font(ctx["disp"], int(84 * u))
    draw.text((left, y + int(38 * u)), str(balance), font=big_font, fill=ctx["ink"])
    draw.text((left + draw_len(str(balance), big_font) + int(16 * u), y + int(102 * u)),
              "颗", font=_font(ff, int(28 * u)), fill=ctx["sub"])
    if today_gain:
        draw.text((right, y + int(58 * u)), f"+{today_gain}",
                  font=_font(ctx["disp"], int(48 * u)), fill=gold_soft, anchor="ra")
        draw.text((right, y + int(116 * u)), "今日抽签所得",
                  font=_font(ff, int(20 * u)), fill=ctx["sub"], anchor="ra")
    y += int(150 * u)

    draw.text((left, y), "—— 背包 ——", font=_font(ff, int(26 * u)), fill=ctx["sub"])
    y += int(44 * u)
    cw = (right - left) / 2 - int(8 * u)
    ch = int(88 * u)
    tint = _mix(ctx["accent"], (255, 255, 255) if not dark else (30, 30, 48),
                0.55 if not dark else 0.86) + (210,)
    for i, (name, count) in enumerate(items):
        cx = left + (cw + int(16 * u)) * (i % 2)
        cy = y + (ch + int(12 * u)) * (i // 2)
        draw.rounded_rectangle([cx, cy, cx + cw, cy + ch], radius=int(12 * u), fill=tint)
        draw.text((cx + int(16 * u), cy + int(12 * u)), name,
                  font=_font(ff, int(23 * u)), fill=ctx["sub"])
        draw.text((cx + int(16 * u), cy + int(38 * u)), f"×{count}",
                  font=_font(ctx["disp"], int(36 * u)), fill=ctx["ink"])
    return _utility_card_save(ctx, cards_root, f"wallet_{file_key}.png", signer, footer=hint)


def render_shop_card(
    nickname: str,
    entries: list,
    cards_root,
    file_key: str = "shop",
    uid: str = "",
    avatar_data: bytes | None = None,
    accent_hex: str = "#F6C6D3",
    hint: str = "购买：/星语购买 <名称> [数量]",
    font_path: str | None = None,
    extra_font_dirs=None,
    signer: str = "星语者",
    width: int = 900,
    theme: str = "light",
) -> str:
    """道具商店卡：每道具一栏（名称+说明+售价+持有）。entries=[(名称, 价格, 说明, 持有)]。"""
    font_file = find_font(font_path, extra_font_dirs)
    if not font_file:
        raise RuntimeError("未找到可用中文字体")
    dark = str(theme or "light").lower() == "dark"
    u0 = width / 900.0
    # 预测量每行说明行数（售价右栏约占 190u 宽）
    row_hs = []
    for _name, _price, desc, _held in entries:
        n_desc = len(_wrap(str(desc), _font(font_file, int(22 * u0)), int((width - 88 - 88 - 190) * u0)))
        row_hs.append(int((84 + max(1, n_desc) * 30) * u0))
    H = int((218 + 96 + sum(row_hs) + len(row_hs) * 14 * u0 + 96) * u0)
    ctx = _utility_card_base(width, H, accent_hex, font_file,
                             subtitle="萌萌星语 · 道具经济", title="道具商店",
                             dark=dark, theme=theme)
    _identity_row(ctx, nickname, uid, avatar_data)
    draw, u, ff = ctx["draw"], ctx["u"], ctx["font_file"]
    left, right = ctx["left"], ctx["right"]
    y = ctx["y"]
    gold_soft = (222, 186, 84) if dark else (176, 142, 48)
    row_bg = _mix(ctx["accent"], (255, 255, 255) if not dark else (30, 30, 48),
                  0.6 if not dark else 0.86) + (185,)
    inner_w = right - left

    for (name, price, desc, held), rh in zip(entries, row_hs):
        draw.rounded_rectangle([left, y, right, y + rh], radius=int(14 * u), fill=row_bg)
        draw.text((left + int(20 * u), y + int(14 * u)), str(name),
                  font=_font(ff, int(30 * u)), fill=ctx["ink"])
        draw.text((right - int(20 * u), y + int(16 * u)), f"★ {price}",
                  font=_font(ctx["disp"], int(32 * u)), fill=gold_soft, anchor="ra")
        draw.text((right - int(20 * u), y + int(56 * u)), f"持有 ×{held}",
                  font=_font(ff, int(20 * u)), fill=ctx["sub"], anchor="ra")
        dy = y + int(54 * u)
        for line in _wrap(str(desc), _font(ff, int(22 * u)), inner_w - int(230 * u))[:3]:
            draw.text((left + int(20 * u), dy), line,
                      font=_font(ff, int(22 * u)), fill=ctx["sub"])
            dy += int(30 * u)
        y += rh + int(14 * u)
    return _utility_card_save(ctx, cards_root, f"shop_{file_key}.png", signer, footer=hint)


def render_rank_card(
    title: str,
    rows: list,
    cards_root,
    file_key: str = "rank",
    empty_text: str = "还没有人抽签，快来当第一个！",
    date_str: str = "",
    subtitle: str = "萌萌星语",
    accent_hex: str = "#F6C6D3",
    font_path: str | None = None,
    extra_font_dirs=None,
    signer: str = "星语者",
    width: int = 900,
    theme: str = "light",
    avatars=None,
) -> str:
    """星语榜卡：rows=[(名次, 昵称, 右侧主文本, 右侧小注)]，前三名奖牌色。

    avatars（v1.10.3）：与 rows 等长的 (bytes|None) 列表——传了就在名次后画
    圆形 QQ 头像，取不到的行画「名字首字」占位圆。
    标题（title）只放榜名，统计口径走 subtitle（小字，空间充裕），
    这样标题不会因为口径文字太长被截断（v1.9.5）。
    """
    font_file = find_font(font_path, extra_font_dirs)
    if not font_file:
        raise RuntimeError("未找到可用中文字体")
    dark = str(theme or "light").lower() == "dark"
    u0 = width / 900.0
    row_h = int(78 * u0)
    H = int((218 + 30 + max(1, len(rows)) * row_h + 96 + 16) * u0)
    ctx = _utility_card_base(width, H, accent_hex, font_file,
                             subtitle=subtitle, title=title,
                             dark=dark, title_right=date_str, theme=theme)
    draw, u, ff = ctx["draw"], ctx["u"], ctx["font_file"]
    left, right = ctx["left"], ctx["right"]
    y = ctx["y"]
    medal = [(212, 175, 55), (176, 180, 196), (205, 140, 100)]

    if not rows:
        box_h = int(120 * u)
        draw.rounded_rectangle([left, y, right, y + box_h], radius=int(14 * u),
                               fill=_mix(ctx["accent"], (255, 255, 255) if not dark else (30, 30, 48),
                                         0.6 if not dark else 0.86) + (185,))
        draw.text(((left + right) // 2, y + box_h / 2), empty_text,
                  font=_font(ff, int(30 * u)), fill=ctx["sub"], anchor="mm")
        return _utility_card_save(ctx, cards_root, f"rank_{file_key}.png", signer)

    # 名次列自适应（v1.9.5）：按实际最大名次宽度排版（两位数、三位数都不会挤到昵称）；
    # 名次过宽时先缩字号，昵称再按剩余宽度截断，绝不与右侧分数叠字。
    name_font = _font(ff, int(32 * u))
    rank_size = int(44 * u)
    rank_font = _font(ctx["disp"], rank_size)
    rank_cap = int(72 * u)
    while rank_size > int(26 * u) and max(
        draw_len(str(r[0]), rank_font) for r in rows
    ) > rank_cap:
        rank_size -= int(4 * u)
        rank_font = _font(ctx["disp"], rank_size)
    rank_col = max(draw_len(str(r[0]), rank_font) for r in rows)
    # 头像列（v1.10.3）：名次与昵称之间画圆形头像
    avatars = list(avatars or [])
    has_av = bool(avatars)
    av_d, av_gap = int(46 * u), int(14 * u)
    name_x = left + int(rank_col) + int(22 * u) + ((av_d + av_gap) if has_av else 0)
    # 右侧信息列宽取「所有行的主文本/小注里最宽的那个」，昵称右边界因此对齐全表
    sub_font = _font(ff, int(20 * u))
    right_w = max(
        max(draw_len(str(r[2]), _font(ctx["disp"], int(40 * u) if r[3] else int(42 * u))),
            draw_len(str(r[3]), sub_font) if r[3] else 0.0)
        for r in rows
    )
    name_avail = int(right - name_x - right_w - int(30 * u))

    for i, (rank, name, main_text, sub_text) in enumerate(rows):
        name = sanitize_name(name)  # 榜单行也是 QQ 昵称，同样要压平空白
        cy = y + row_h * i
        rank_rgb = medal[rank - 1] if isinstance(rank, int) and 1 <= rank <= 3 else ctx["sub"]
        draw.text((left, cy + row_h / 2), str(rank),
                  font=rank_font, fill=rank_rgb, anchor="lm")
        if has_av:
            # 圆形 QQ 头像；取不到的画「名字首字」占位圆（与运势卡头像同风格）
            av_x = left + int(rank_col) + int(22 * u)
            av_y = cy + row_h // 2 - av_d // 2
            data = avatars[i] if i < len(avatars) else None
            av_img = None
            if data:
                try:
                    av_img = _circle_img(Image.open(io.BytesIO(data)).convert("RGBA"), av_d)
                except Exception:
                    av_img = None
            if av_img is not None:
                ctx["img"].paste(av_img, (av_x, av_y), av_img)
            else:
                ph = Image.new("RGBA", (av_d, av_d), (0, 0, 0, 0))
                pd = ImageDraw.Draw(ph)
                pd.ellipse([0, 0, av_d - 1, av_d - 1],
                           fill=_mix(ctx["accent"], (255, 255, 255) if not dark else (30, 30, 48),
                                     0.5) + (255,))
                pd.text((av_d / 2, av_d / 2), (name or "星")[0],
                        font=_font(ff, int(22 * u)), fill=ctx["ink"], anchor="mm")
                ctx["img"].paste(ph, (av_x, av_y), ph)
        draw.text((name_x, cy + row_h / 2), _fit_text(name, name_font, name_avail),
                  font=name_font, fill=ctx["ink"], anchor="lm")
        if sub_text:
            draw.text((right, cy + int(14 * u)), str(main_text),
                      font=_font(ctx["disp"], int(40 * u)), fill=ctx["ink"], anchor="ra")
            draw.text((right, cy + row_h - int(14 * u)), str(sub_text),
                      font=_font(ff, int(20 * u)), fill=ctx["sub"], anchor="ra")
        else:
            draw.text((right, cy + row_h / 2), str(main_text),
                      font=_font(ctx["disp"], int(42 * u)), fill=ctx["ink"], anchor="rm")
        if i < len(rows) - 1:
            draw.line([(left, cy + row_h), (right, cy + row_h)], fill=ctx["line"], width=1)
    return _utility_card_save(ctx, cards_root, f"rank_{file_key}.png", signer)


def render_pk_card(
    left_name: str,
    left_score: int,
    right_name: str,
    right_score: int,
    verdict: str,
    flavor: str,
    cards_root,
    file_key: str = "pk",
    winner: str = "left",
    accent_hex: str = "#F6C6D3",
    font_path: str | None = None,
    extra_font_dirs=None,
    signer: str = "星语者",
    width: int = 1000,
    theme: str = "light",
) -> str:
    """星语 PK 卡：左右分数对撞 + 中央 VS 徽 + 判词与碎碎念。winner: left/right/tie。"""
    left_name = sanitize_name(left_name)
    right_name = sanitize_name(right_name)
    font_file = find_font(font_path, extra_font_dirs)
    if not font_file:
        raise RuntimeError("未找到可用中文字体")
    dark = str(theme or "light").lower() == "dark"
    u0 = width / 900.0
    flavor_lines = _wrap(str(flavor), _font(font_file, int(28 * u0)), int((width - 88 - 88) * u0))[:3]
    H = int((218 + 260 + 36 + 78 + len(flavor_lines) * 44 + 96) * u0)
    ctx = _utility_card_base(width, H, accent_hex, font_file,
                             subtitle="萌萌星语", title="星语 PK",
                             dark=dark, theme=theme)
    draw, u, ff = ctx["draw"], ctx["u"], ctx["font_file"]
    left, right = ctx["left"], ctx["right"]
    y = ctx["y"]
    gold_soft = (222, 186, 84) if dark else (176, 142, 48)
    panel_w = (right - left - int(72 * u)) / 2
    panel_h = int(240 * u)
    score_font = _font(ctx["disp"], int(96 * u))

    for side, (px, name, score) in enumerate((
            (left, left_name, left_score), (left + panel_w + int(72 * u), right_name, right_score))):
        draw.rounded_rectangle([px, y, px + panel_w, y + panel_h], radius=int(18 * u),
                               fill=_mix(ctx["accent"], (255, 255, 255) if not dark else (30, 30, 48),
                                         0.6 if not dark else 0.86) + (200,))
        draw.text((px + panel_w / 2, y + int(34 * u)), str(name)[:8],
                  font=_font(ff, int(30 * u)), fill=ctx["ink"], anchor="ma")
        is_win = (winner == "left" and side == 0) or (winner == "right" and side == 1)
        score_rgb = gold_soft if is_win else (ctx["sub"] if winner != "tie" else ctx["ink"])
        draw.text((px + panel_w / 2, y + int(148 * u)), str(score),
                  font=score_font, fill=score_rgb, anchor="mm")
        draw.text((px + panel_w / 2, y + panel_h - int(20 * u)), "幸运指数",
                  font=_font(ff, int(20 * u)), fill=ctx["sub"], anchor="ms")

    vs_cx = (left + right) / 2
    vs_cy = y + panel_h / 2
    vs_r = int(46 * u)
    draw.ellipse([vs_cx - vs_r, vs_cy - vs_r, vs_cx + vs_r, vs_cy + vs_r],
                 fill=_mix(ctx["accent"], (74, 74, 96) if not dark else (232, 230, 240), 0.55) + (255,))
    draw.text((vs_cx, vs_cy), "VS", font=_font(ctx["disp"], int(40 * u)),
              fill=(255, 255, 255, 255) if not dark else (30, 30, 44, 255), anchor="mm")
    y += panel_h + int(36 * u)

    draw.text(((left + right) / 2, y), str(verdict),
              font=_font(ctx["disp"], int(46 * u)), fill=ctx["ink"], anchor="ma")
    y += int(78 * u)
    for line in flavor_lines:
        draw.text(((left + right) / 2, y), line,
                  font=_font(ff, int(28 * u)), fill=ctx["sub"], anchor="ma")
        y += int(44 * u)
    return _utility_card_save(ctx, cards_root, f"pk_{file_key}.png", signer)


def render_notice_card(
    title: str,
    lines: list,
    cards_root,
    file_key: str = "notice",
    subtitle: str = "萌萌星语",
    accent_hex: str = "#F6C6D3",
    footer: str = "",
    font_path: str | None = None,
    extra_font_dirs=None,
    signer: str = "星语者",
    width: int = 860,
    theme: str = "light",
) -> str:
    """通用通知卡（购买/使用/绑定/星座等结果提示）：标题 + 若干行正文，高度自适应。"""
    font_file = find_font(font_path, extra_font_dirs)
    if not font_file:
        raise RuntimeError("未找到可用中文字体")
    dark = str(theme or "light").lower() == "dark"
    u0 = width / 900.0
    inner_w = int((width - 88 - 84 - 40) * u0)
    body = _font(font_file, int(32 * u0))
    wrapped = []
    for line in lines:
        wrapped += _wrap(str(line), body, inner_w)[:3]
    H = int((218 + len(wrapped) * 54 + 40 + 96) * u0)
    ctx = _utility_card_base(width, H, accent_hex, font_file,
                             subtitle=subtitle, title=title, dark=dark, theme=theme)
    draw, u, ff = ctx["draw"], ctx["u"], ctx["font_file"]
    left = ctx["left"]
    y = ctx["y"]
    for line in wrapped:
        # 每行左侧的小色条，弱化 bullet 感
        draw.rounded_rectangle([left, y + int(8 * u), left + int(6 * u), y + int(40 * u)],
                               radius=int(3 * u),
                               fill=_mix(ctx["accent"], (74, 74, 96) if not dark else (232, 230, 240), 0.4) + (255,))
        draw.text((left + int(22 * u), y), line, font=body, fill=ctx["ink"])
        y += int(54 * u)
    return _utility_card_save(ctx, cards_root, f"notice_{file_key}.png", signer, footer=footer)


def render_calendar_card(
    year: int,
    month: int,
    days: dict,
    cards_root,
    file_key: str = "calendar",
    today: str = "",
    nickname: str = "",
    accent_hex: str = "#F6C6D3",
    grade_colors: dict | None = None,
    stats: dict | None = None,
    font_path: str | None = None,
    extra_font_dirs=None,
    signer: str = "星语者",
    width: int = 1000,
    theme: str = "light",
) -> str:
    """运势日历卡：当月真实月历网格，每日吉凶（档位色）+ 分数。

    days: {"YYYY-MM-DD": (吉凶, 分数)}（仅已占卜的日子）；
    stats: {"drawn": n, "daji": n, "avg": 均分, "stardust": 累计星尘或 None}。
    未占卜的日子画小圆点；未来日期灰显；今日金框。
    """
    nickname = sanitize_name(nickname)
    font_file = find_font(font_path, extra_font_dirs)
    if not font_file:
        raise RuntimeError("未找到可用中文字体")
    dark = str(theme or "light").lower() == "dark"
    u0 = width / 900.0
    first = datetime(year, month, 1)
    nxt = datetime(year + (1 if month == 12 else 0), 1 if month == 12 else month + 1, 1)
    n_days = (nxt - first).days
    offset = first.weekday()  # Monday=0
    weeks = (offset + n_days + 6) // 7
    cell_h = int(122 * u0)
    H = int((218 + 50 + weeks * (cell_h + 10 * u0) + 88 + 96) * u0)
    ctx = _utility_card_base(width, H, accent_hex, font_file,
                             subtitle=f"{year} 年 {month} 月 · {nickname or '旅行者'}",
                             title="运势日历", dark=dark, theme=theme)
    draw, u, ff = ctx["draw"], ctx["u"], ctx["font_file"]
    left, right = ctx["left"], ctx["right"]
    y = ctx["y"]
    gold = (212, 175, 55)
    gcolors = dict(_CALENDAR_GRADE_COLORS)
    if grade_colors:
        gcolors.update(grade_colors)
    inner_w = right - left
    gap = int(9 * u)
    cell_w = (inner_w - gap * 6) / 7
    faint = _mix(ctx["sub"], (255, 255, 255) if not dark else (30, 30, 48), 0.45)

    # 星期表头（周末染主色）
    for i, name in enumerate(("一", "二", "三", "四", "五", "六", "日")):
        cx = left + (cell_w + gap) * i + cell_w / 2
        color = ctx["sub"] if i < 5 else _mix(ctx["accent"], ctx["ink"], 0.35)
        draw.text((cx, y), name, font=_font(ff, int(26 * u)), fill=color, anchor="ma")
    y += int(50 * u)

    for wk in range(weeks):
        for i in range(7):
            day_num = wk * 7 + i - offset + 1
            if not (1 <= day_num <= n_days):
                continue
            date_str = f"{year:04d}-{month:02d}-{day_num:02d}"
            cx = left + (cell_w + gap) * i
            cy = y + wk * (cell_h + gap)
            box = [cx, cy, cx + cell_w, cy + cell_h]
            is_today = bool(today) and date_str == str(today)
            is_future = bool(today) and date_str > str(today)
            entry = days.get(date_str)
            radius = int(14 * u)
            if entry is not None:
                grade, score = entry
                g_rgb = _hex_rgb(gcolors.get(grade, "#E86A8A"))
                if dark:
                    g_rgb = _mix(g_rgb, (255, 255, 255), 0.35)
                draw.rounded_rectangle(box, radius=radius,
                                       fill=_mix(ctx["accent"], (255, 255, 255) if not dark else (30, 30, 48),
                                                 0.55 if not dark else 0.84) + (215,))
                draw.text((cx + int(12 * u), cy + int(9 * u)), str(day_num),
                          font=_font(ff, int(22 * u)), fill=ctx["sub"])
                draw.text((cx + cell_w / 2, cy + int(62 * u)), str(grade),
                          font=_font(ctx["disp"], int(34 * u)), fill=g_rgb, anchor="mm")
                draw.text((cx + cell_w / 2, cy + cell_h - int(18 * u)), str(score),
                          font=_font(ff, int(23 * u)), fill=ctx["ink"], anchor="ms")
            elif is_future:
                draw.text((cx + int(12 * u), cy + int(9 * u)), str(day_num),
                          font=_font(ff, int(22 * u)), fill=faint)
            else:
                # 未占卜：细描边 + 居中小圆点；今天未抽则写「未抽」
                draw.rounded_rectangle(box, radius=radius, outline=ctx["line"], width=1)
                draw.text((cx + int(12 * u), cy + int(9 * u)), str(day_num),
                          font=_font(ff, int(22 * u)), fill=faint)
                if is_today:
                    draw.text((cx + cell_w / 2, cy + int(62 * u)), "未抽",
                              font=_font(ff, int(24 * u)), fill=ctx["sub"], anchor="mm")
                else:
                    dr = int(4 * u)
                    draw.ellipse([cx + cell_w / 2 - dr, cy + int(58 * u),
                                  cx + cell_w / 2 + dr, cy + int(58 * u) + 2 * dr], fill=ctx["sub"])
            if is_today:
                draw.rounded_rectangle(box, radius=radius, outline=gold + (255,),
                                       width=max(2, int(3 * u)))
    y += weeks * (cell_h + gap)

    mid = (left + right) / 2
    draw.text((mid, y + int(2 * u)), "底色 · 已占卜　小点 · 未占卜　金框 · 今日",
              font=_font(ff, int(22 * u)), fill=ctx["sub"], anchor="ma")
    y += int(44 * u)
    st = stats or {}
    parts = []
    if st.get("drawn"):
        parts.append(f"占卜 {st['drawn']} 天")
        parts.append(f"大吉 {st.get('daji', 0)} 次")
        parts.append(f"均分 {st.get('avg', 0)}")
    if st.get("stardust") is not None:
        parts.append(f"累计星尘 {st['stardust']}")
    if parts:
        draw.text((mid, y), " ｜ ".join(parts),
                  font=_font(ff, int(26 * u)), fill=ctx["ink"], anchor="ma")
    return _utility_card_save(ctx, cards_root, f"calendar_{file_key}.png", signer)
