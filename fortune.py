# -*- coding: utf-8 -*-
"""萌萌星语 · 运势核心（纯函数，不依赖 astrbot，可独立测试）。

确定性原则（PRD §3.1）：
    seed = SHA-256(f"{date}|{user_id}|{salt}|{nonce}")
所有维度由种子派生（hashlib，禁止全局 random），同一天同一人结果恒定：
跨时刻、跨群一致；换签卡 = nonce+1 重掷；底图种子同理，一人一天一张。
"""
from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

GRADES = ("大吉", "吉", "中吉", "小吉", "凶", "大凶")

# 权重表（D2）：大吉略高于传统十取一，群里更欢乐；运行时以配置覆盖
DEFAULT_GRADE_WEIGHTS = {"大吉": 20, "吉": 25, "中吉": 25, "小吉": 15, "凶": 10, "大凶": 5}

# 各吉凶档的六维星数区间 [lo, hi]（含端点）
GRADE_DIM_RANGE = {
    "大吉": (4, 5),
    "吉": (3, 5),
    "中吉": (3, 4),
    "小吉": (2, 4),
    "凶": (1, 3),
    "大凶": (1, 2),
}

DIM_KEYS = ("恋爱运", "学业运", "财运", "健康运", "社交运", "摸鱼运")


def _sub_int(seed: bytes, tag: str, modulus: int) -> int:
    """由种子+标签派生 [0, modulus) 内的确定整数。modulus 必须 >= 1。"""
    digest = hashlib.sha256(seed + b"|" + tag.encode("utf-8")).digest()
    return int.from_bytes(digest[:8], "big") % modulus


def _pick(seed: bytes, tag: str, pool):
    return pool[_sub_int(seed, tag, len(pool))]


def _weighted_pick(seed: bytes, tag: str, weights: dict) -> str:
    total = int(sum(weights.values()))
    if total <= 0:
        raise ValueError(f"吉凶权重之和必须为正：{weights}")
    point = _sub_int(seed, tag, total)
    acc = 0
    last = None
    for key, weight in weights.items():
        acc += int(weight)
        last = key
        if point < acc:
            return key
    return last


def _pick_two(seed: bytes, tag: str, pool: list) -> list:
    """从池中确定地取两个不重复项（池长度 >= 2）。"""
    n = len(pool)
    i = _sub_int(seed, tag, n)
    j = _sub_int(seed, tag + "#2", n - 1)
    if j >= i:
        j += 1
    return [pool[i], pool[j]]


def derive_seed(date_str: str, user_id: str, salt: str, nonce: int = 0) -> bytes:
    raw = f"{date_str}|{user_id}|{salt}|{int(nonce)}".encode("utf-8")
    return hashlib.sha256(raw).digest()


def now_in(tz_name: str = "Asia/Shanghai") -> datetime:
    """插件时区的当前时刻（aware）。回退链：配置时区 → Asia/Shanghai → 固定 UTC+8。"""
    try:
        tz = ZoneInfo(tz_name)
    except Exception:
        try:
            tz = ZoneInfo("Asia/Shanghai")
        except Exception:
            tz = timezone(timedelta(hours=8))
    return datetime.now(tz)


def local_today(tz_name: str = "Asia/Shanghai") -> str:
    """插件时区的今天（YYYY-MM-DD）。"""
    return now_in(tz_name).strftime("%Y-%m-%d")


def prev_date(date_str: str) -> str:
    d = datetime.strptime(date_str, "%Y-%m-%d")
    return (d - timedelta(days=1)).strftime("%Y-%m-%d")


def roll_fortune(seed: bytes, lex: dict, grade_weights: dict | None = None) -> dict:
    """由种子确定地掷出一支完整运势（返回值可直接 JSON 序列化落库）。"""
    weights = dict(grade_weights) if grade_weights else dict(DEFAULT_GRADE_WEIGHTS)
    grade = _weighted_pick(seed, "grade", weights)
    lo, hi = GRADE_DIM_RANGE[grade]
    dims = {}
    for key in DIM_KEYS:
        dims[key] = lo + _sub_int(seed, f"dim:{key}", hi - lo + 1)
    score = round(sum(dims.values()) / (5 * len(DIM_KEYS)) * 100)
    score = max(5, min(100, score))

    item = _pick(seed, "item", lex["lucky_items"])
    color = lex["lucky_colors"][_sub_int(seed, "color", len(lex["lucky_colors"]))]
    yi = _pick_two(seed, "yi", lex["yi"])
    ji = _pick_two(seed, "ji", lex["ji"])
    phase = _pick(seed, "phase", lex["phases"])
    direction = _pick(seed, "dir", lex["directions"])
    number = 1 + _sub_int(seed, "number", 99)

    comment = _pick(seed, f"comment:{grade}", lex["comments"][grade])
    item_line = _pick(seed, "item_line", lex["item_lines"]).format(item=item)
    wish = _pick(seed, f"wish:{grade}", lex["wishes"][grade])
    sign_text = f"{comment}{item_line}{wish}"

    return {
        "grade": grade,
        "grade_color": lex["grade_colors"].get(grade, "#E8A2B8"),
        "score": score,
        "dims": dims,
        "lucky_item": item,
        "lucky_color": color,
        "lucky_number": number,
        "lucky_dir": direction,
        "yi": yi,
        "ji": ji,
        "phase": phase,
        "sign_text": sign_text,
        "boosts": {"amulet": False, "candle": False},
    }


def pick_text(seed: bytes, tag: str, pool: list) -> str:
    """从池中确定性取一条（公开接口，供 PK 文案等场景使用）。"""
    return _pick(seed, tag, pool)


def pick_two(seed: bytes, tag: str, pool: list) -> list:
    """从池中确定性取两条不重复项（公开接口，v1.10.15 每日推送的宜忌用）。

    池长 < 2 时抛 ValueError：调用方（每日推送）自己兜底，不要在这里静默返回
    残缺结果——宜忌两条是这个功能的合同，少一条就该走降级分支。
    """
    if len(pool) < 2:
        raise ValueError(f"词库池不足两项：{tag}（{len(pool)}）")
    return _pick_two(seed, tag, pool)


def pick_number(seed: bytes, tag: str = "number") -> int:
    """1-99 的确定整数（公开接口）：与运势卡的幸运数字同区间，每日推送用。"""
    return 1 + _sub_int(seed, tag, 99)


# 星座区间（含跨年的摩羯）；MM-DD -> 名称
CONSTELLATION_RANGES = (
    ("摩羯座", (12, 22), (1, 19)),
    ("水瓶座", (1, 20), (2, 18)),
    ("双鱼座", (2, 19), (3, 20)),
    ("白羊座", (3, 21), (4, 19)),
    ("金牛座", (4, 20), (5, 20)),
    ("双子座", (5, 21), (6, 21)),
    ("巨蟹座", (6, 22), (7, 22)),
    ("狮子座", (7, 23), (8, 22)),
    ("处女座", (8, 23), (9, 22)),
    ("天秤座", (9, 23), (10, 23)),
    ("天蝎座", (10, 24), (11, 22)),
    ("射手座", (11, 23), (12, 21)),
)


def constellation_of(mmdd: str) -> str:
    """MM-DD -> 星座名；非法日期返回空串（绑定入口已先行校验，此处双保险）。"""
    try:
        m, d = int(str(mmdd)[:2]), int(str(mmdd)[3:5])
        datetime(2000, m, d)  # 日历合法性（拦截 13-40 之类，防跨年 or 误判）
    except Exception:
        return ""
    for name, (m1, d1), (m2, d2) in CONSTELLATION_RANGES:
        if (m1, d1) <= (m2, d2):
            hit = (m1, d1) <= (m, d) <= (m2, d2)
        else:  # 跨年（摩羯）
            hit = (m, d) >= (m1, d1) or (m, d) <= (m2, d2)
        if hit:
            return name
    return ""


def amulet_weights(weights: dict | None = None) -> dict:
    """厄运护身符（F22，M7 使用）：凶/大凶的权重并入小吉，实现「保底小吉」。"""
    base = dict(weights) if weights else dict(DEFAULT_GRADE_WEIGHTS)
    merged = int(base.pop("凶", 0)) + int(base.pop("大凶", 0))
    base["小吉"] = int(base.get("小吉", 0)) + merged
    return base


def apply_candle(result: dict) -> dict:
    """幸运香烛（F22，M7 使用）：幸运指数 +8（封顶 100），不改吉凶档，幂等。"""
    boosts = result.setdefault("boosts", {})
    if boosts.get("candle"):
        return result
    result["score"] = min(100, int(result.get("score", 0)) + 8)
    boosts["candle"] = True
    return result


DEFAULT_LLM_PERSONA = (
    "你是「星语者」，一位温柔微傲娇的占星见习生，为抽到签的用户写今日签文。"
    "先记住：卡片上已经展示了吉凶、幸运指数、六维星数、宜忌，以及幸运物/幸运色/"
    "幸运数字/幸运方位四件套——签文里【一个都不要再提】：不要出现幸运物的名字、"
    "幸运数字、方位、颜色的词，也不要复述宜忌条目原词，那是复读不是解签。"
    "你要写的是对这一天的解读：顺着运势走向（吉凶与六维强弱）与今日抽到的那张牌的"
    "正位或逆位含义，用画面感说一句只属于今天的话——吉日大方恭喜、给一个值得期待的方向；"
    "凶日温柔安慰、教用户把今天过得松一点。"
    "今日牌为逆位时语气要偏「提醒与松绑」，不要写成一路顺风的恭喜；"
    "也不要把牌名和牌面画面直接复述一遍，要写的是它对这一天意味着什么。"
    "第二人称，60 字以内，2~3 句，像写给朋友的短笺。"
    "只输出签文本身：不要解释、不要引号、不要表情、不要罗列。"
)

# 生图时随事实清单一起下发的两条硬约束（v1.11.9）。
# 以前 facts 里只有牌名与关键词，LLM 只能凭「The Hanged Man」这个名字自由发挥，
# 结果 22 张牌全画成一个站着的少女——倒吊人永远是正的、星星从没跪下倒过水。
# 现在把每张牌的具体画面要素喂进去，并明确「关键姿态不可省略」「逆位怎么画」。
TAROT_VISUAL_RULE_ZH = (
    "画面规则：牌面意象里的关键姿态（倒挂、跪姿、倒水、举剑等）必须照画，"
    "不能偷懒换成普通站姿；牌面边框保持端正水平、左右对称，逆位只靠主体或道具的"
    "翻转倾斜来表达；画面里只出现一位少女，牌义涉及他人时用倒影、雕像或象征物代替；"
    "不要出现任何文字、牌名、罗马数字或水印"
)
TAROT_VISUAL_RULE_EN = (
    "Visual rules: draw the key pose from the Card motif line literally (hanging upside down, "
    "kneeling, pouring water, raising a sword, etc.), never fall back on a generic standing pose; "
    "keep the card frame upright and symmetrical, express a reversed card only by inverting the "
    "figure or tilting the props INSIDE the frame; only one girl, use reflections or statues "
    "instead of extra people; no text, no card names, no roman numerals, no watermark"
)
ELEMENT_EN = {"火": "fire", "水": "water", "风": "air", "土": "earth"}


def llm_facts(result: dict, visual_lang: str = "") -> str:
    """当日运势事实清单（F16：喂给 LLM 的脱敏事实，不含任何用户身份信息）。

    visual_lang 为空 = 给「LLM 星语」用，只给文字事实（签文不该复述牌面画面）；
    传 "zh"/"en" = 给「封面图提示词」用，额外附上牌面意象、牌组与画面规则。
    两种用途共用 {facts} 占位符，所以用户自定义模板也能自动吃到新信息。
    """
    dims = result.get("dims") or {}
    dim_text = "、".join(f"{k}{v}星" for k, v in dims.items())
    color = (result.get("lucky_color") or {}).get("name", "")
    phase = result.get("phase") or {}
    tarot = complement_tarot(result.get("tarot") or {})
    tarot_text = ""
    if tarot:
        # v1.11.11：塔罗与神谕卡共用一条事实清单，但牌种标题要如实分开写，
        # 否则「新月」会被当成一张塔罗牌喂给 LLM。
        card_title = ("今日星语神谕卡" if tarot.get("deck_kind") == "oracle"
                      else "今日塔罗")
        tarot_text = (f"\n{card_title}：{tarot.get('name_cn', '')}"
                      f"（{tarot.get('label', '')}）——{tarot.get('keywords', '')}")
        if visual_lang:
            zh = visual_lang == "zh"
            suit_cn = str(tarot.get("suit_cn") or "")
            element = str(tarot.get("element") or "")
            if suit_cn:
                en_suit = ELEMENT_EN.get(element, "")
                if zh:
                    tarot_text += "\n牌组：" + suit_cn + (f"（{element}元素）" if element else "")
                elif en_suit:
                    tarot_text += "\nElement: " + en_suit
                else:
                    # 神谕卡没有四元素，写分类英文名；塔罗大阿卡纳保持历史口径
                    group_en = str(tarot.get("group_en") or "Major Arcana")
                    tarot_text += "\nCard group: " + group_en
            visual = str(tarot.get("visual_zh" if zh else "visual_en") or "")
            if visual:
                tarot_text += (f"\n牌面意象：{visual}" if zh
                               else f"\nCard motif (must draw exactly): {visual}")
            tarot_text += ("\n" + (TAROT_VISUAL_RULE_ZH if zh else TAROT_VISUAL_RULE_EN))
    return (
        f"吉凶：{result.get('grade', '')}（幸运指数 {result.get('score', '')}）\n"
        f"六维：{dim_text}\n"
        f"幸运物：{result.get('lucky_item', '')}；幸运色：{color}；"
        f"幸运数字：{result.get('lucky_number', '')}；幸运方位：{result.get('lucky_dir', '')}\n"
        f"宜：{'、'.join(result.get('yi') or [])}；忌：{'、'.join(result.get('ji') or [])}\n"
        f"月相：{phase.get('name', '')}"
        f"{tarot_text}"
    )


# ---------- M6：萌绘底图联动的提示词与响应解析 ----------

# v1.8.6：卡面主角一律为女性角色，不出现男性形象（可被内置负向提示词进一步兜底）
FEMALE_SUBJECT_ZH = "画面主体必须是一位女性角色（动漫少女），不要出现任何男性角色、男孩或男性形象"
FEMALE_SUBJECT_EN = "1girl, solo, female focus, female only, no males, no boys"
# v1.10.4：负向提示词加入裁切类标签——AI 倾向把装饰边框画到画布边缘，
# 一侧被裁就会左右不对称；光靠正向的 fully visible 压不住。
# v1.10.6：再加白边与构图类标签（用户反馈）：白边 / 卡片偏移 / 构图偏心 /
# 画面倾斜 / 透视 / 立体卡牌 / 投影阴影 / 卡片悬浮 / 边角缺失
# v1.11.9：再补文字/水印与「第二个人」——牌面上 AI 常写 THE HANGED MAN、罗马数字，
# 或把「恋人」「审判」画成两个人，既和右侧面板的中文重复，也违反单人少女约定。
DEFAULT_DRAW_NEGATIVE = (
    "1boy, male, man, boy, masculine, male focus, "
    "white border, white edges, white frame, blank margins, white background, plain background, "
    "cropped, cropped border, cut off, out of frame, "
    "partially visible frame, uneven border, missing corners, "
    "off-center card, off-center composition, card shifted to one side, "
    "tilted, skewed, perspective, 3d card, "
    "drop shadow, cast shadow, shadow, floating card, "
    "text, letters, card name, roman numerals, card number, watermark, signature, "
    "2girls, multiple girls, extra people"
)
DRAW_NEGATIVE_HINT_ZH = "画面中只有女性角色，禁止出现男性角色"
# v1.10.4 起：边框完整可见、左右对称；v1.10.6 用户反馈后改成「画面铺满画布」——
# 早期版本要求「边框与画布留空隙」，模型会把空隙画成白边，故严禁再加回留空隙。
# v1.11.11：两套牌共用同一套「华丽对称牌框」的视觉风格，措辞改成通用，
# 不再把神谕卡的牌面也叫成塔罗牌（边框样式本身仍是塔罗式金框）。
BORDER_MARGIN_ZH = ("配华丽对称的星语牌边框——边框完整可见、不被裁切，左右两侧粗细一致，"
                    "画面铺满整个画布，四周不要留白边")
BORDER_MARGIN_EN = ("ornate symmetrical fortune card frame, entire frame fully visible "
                    "and not cropped, left and right sides of the frame equally thick, "
                    "the illustration fills the entire canvas edge to edge, "
                    "no blank white margins around the image")


def draw_system_hint(lang: str) -> str:
    """生图提示词的系统提示——按目标语言切换，避免 LLM 跟着英文提示输出英文。

    v1.11.9 起把「照着牌面意象画」写成硬约束：牌名只是主题提示，
    关键姿态（倒挂 / 跪姿 / 倒水 / 举剑）必须落到画面上，不许退化成通用站姿。
    """
    if lang == "zh":
        return ("你为一张动漫风格的星语牌面撰写绘图提示词。"
                + FEMALE_SUBJECT_ZH + "。"
                "事实清单里的「牌面意象」是必须画出来的画面：写倒吊就画头下脚上地倒挂，"
                "写跪姿就画跪着，写倒水就画两只杯子来回倾倒，不许偷懒换成普通站姿；"
                "只画一位少女，牌义涉及他人时用倒影、雕像或象征物代替；"
                "不要出现文字、牌名、罗马数字、水印。"
                "牌面边框必须完整可见、不被裁切，左右对称。"
                "必须使用中文输出。只输出提示词本身，不要任何解释。")
    return ("You write image-generation prompts for a moe astrology fortune card. "
            "The subject must be a female character (a single anime girl); "
            "never include male characters. "
            "Follow the Card motif line in the facts literally: an upside-down hanged girl "
            "must actually hang upside down, a kneeling girl must kneel, pouring water must "
            "show the jugs. Never fall back on a generic standing pose. "
            "Only one girl; replace extra people with reflections, statues or symbols. "
            "No text, no card names, no roman numerals, no watermark. "
            "The card border must be fully visible, never cropped, symmetrical "
            "left to right. "
            "Output ONLY the prompt itself.")


def lang_matches(text: str, lang: str) -> bool:
    """校验生成文本的语言是否符合配置（zh 需足够的中文，en 不得含中文）。"""
    text = str(text or "")
    if not text:
        return False
    cn = sum(1 for ch in text if '\u4e00' <= ch <= '\u9fff')
    if lang == "zh":
        return cn >= max(2, int(len(text) * 0.2))
    return cn == 0

DRAW_GRADE_MOODS_EN = {
    "大吉": "radiant smile, sparkling eyes, golden sparkles, celebration",
    "吉": "gentle smile, warm light, soft glow",
    "中吉": "calm expression, serene, soft pastel mood",
    "小吉": "shy smile, cute, delicate",
    "凶": "melancholy, gloomy mood, drizzle",
    "大凶": "tearful pout, dramatic clouds, under a broken umbrella",
}

DRAW_GRADE_MOODS_ZH = {
    "大吉": "光芒四射、喜气洋洋", "吉": "温柔微笑、暖光环绕",
    "中吉": "平静安详、淡彩氛围", "小吉": "害羞可爱",
    "凶": "微微忧郁、细雨", "大凶": "委屈嘟嘴、头顶乌云",
}


def builtin_draw_prompt(lang: str, fmt: str) -> str:
    """封面图提示词的 LLM 指令模板（星语牌面 + 动漫风格，PRD §7.6-3）。

    v1.11.9：牌池扩到 78 张后不能再写死「大阿卡纳」；更重要的是明确要求
    「照着事实清单里的牌面意象画」，否则 LLM 只知道牌名，依旧会画出通用站姿。
    """
    if lang == "zh":
        shape = "一段自然流畅的中文画面描述（不要标签堆砌）" if fmt == "natural" else "中文短语式描述"
        return (
            "根据下面的事实清单，为一张**动漫风格的星语牌面**插画写" + shape + "："
            "画面严格按清单里那张今日牌的「牌面意象」来画，关键姿态不可省略——"
            "写倒吊就画头下脚上地倒挂，写跪姿就画跪着，写倒水就画两只杯子来回倾倒；"
            "牌名只作主题提示，不能只画一个普通站着的少女。"
            + FEMALE_SUBJECT_ZH + "，"
            + BORDER_MARGIN_ZH + "，"
            "星月与神秘学纹样，动漫赛璐璐质感，不要出现任何文字、牌名、罗马数字或水印。"
            "⚠️ 必须输出中文描述，不要翻译成英文。只输出描述本身。\n{facts}"
        )
    if fmt == "natural":
        return (
            "Based on the fortune facts below, write ONE English sentence describing an "
            "ANIME-STYLE FORTUNE CARD illustration: a single anime girl as the central figure "
            "(female only, no male characters), the card named in the facts as the "
            "central motif, FOLLOW the Card motif line literally (an upside-down hanged girl "
            "really hangs upside down, a kneeling girl really kneels) instead of drawing a "
            "generic standing girl, " + BORDER_MARGIN_EN + ", "
            "centered composition, portrait orientation, nothing "
            "cropped at the edges, mystical star-and-moon ambience, cel-shaded anime art, "
            "no text, no roman numerals. "
            "No Chinese, no explanations, output only the sentence.\n{facts}"
        )
    return (
        "Based on the fortune facts below, write ONE line of English Danbooru-style tags for an "
        "ANIME-STYLE FORTUNE CARD illustration: " + FEMALE_SUBJECT_EN + ", "
        "the card named in the facts as the central motif, "
        "include the key pose from the Card motif line (hanging upside down, kneeling, "
        "pouring water, raising a sword, etc.) as explicit tags, never a generic standing pose, "
        "symmetrical composition, centered, " + BORDER_MARGIN_EN + ", "
        "nothing cropped, portrait orientation, "
        "mystical symbols, star and crescent moon background, anime style, cel shading, "
        "masterpiece, best quality, no text, no watermark. "
        "Comma-separated lowercase tags, no sentences, no Chinese, "
        "no explanations. Output only the tags.\n{facts}"
    )


def local_draw_prompt(result: dict, lang: str, fmt: str) -> str:
    """LLM 不可用/语言不合规时的本地兜底提示词。

    v1.11.9 之前这里只有「牌名 + 吉凶氛围」一句话，出图信息量比 LLM 路径少一大截，
    于是 LLM 一超时，图就退化成「一个站着的少女」。现在兜底也把牌面意象、正逆位、
    牌组、幸运色与月相一起带上去（严格按 lang，不混中文进英文提示词）。
    """
    grade = result.get("grade", "")
    tarot = complement_tarot(result.get("tarot") or {})
    name_cn = str(tarot.get("name_cn") or "星星")
    # 无塔罗数据（旧 payload / 单测）时保留历史兜底牌名，保证提示词不空
    name_en = str(tarot.get("name_en") or "The Star")
    label = str(tarot.get("label") or "正位")
    color = str((result.get("lucky_color") or {}).get("name") or "")
    phase = str((result.get("phase") or {}).get("name") or "")
    visual = str(tarot.get("visual_zh" if lang == "zh" else "visual_en") or "")
    if lang == "zh":
        mood = DRAW_GRADE_MOODS_ZH.get(grade, "温柔")
        visual = visual or "星月与神秘学纹样环绕中央少女，画面铺满"
        extras = "、".join(x for x in (
            f"幸运色{color}" if color else "",
            f"{phase}夜空" if phase else "",
        ) if x)
        tail = ("、" + extras) if extras else ""
        body = (f"动漫风格星语牌面：{name_cn}（{label}）主题的少女，"
                f"【牌面画面】{visual}，{mood}"
                f"，{DRAW_NEGATIVE_HINT_ZH}，" + BORDER_MARGIN_ZH + "，"
                "构图饱满不裁边，竖版构图，星月神秘氛围，淡彩，画质精美" + tail)
        # 标签式用顿号分隔短语，自然语言保持上面的完整句子
        return body if fmt == "natural" else body.replace("，", "、")
    mood = DRAW_GRADE_MOODS_EN.get(grade, "gentle smile")
    visual = visual or "a girl surrounded by stars and crescent moon mystic symbols"
    pos = "reversed" if tarot.get("reversed") else "upright"
    # The Fool / The Hanged Man 这类牌名自带冠词，别拼出 "the The Hanged Man"
    card_phrase = name_en if name_en.lower().startswith("the ") else f"the {name_en}"
    return (
        "fortune card design, anime style, " + FEMALE_SUBJECT_EN + f", {mood}, "
        f"{card_phrase} fortune card motif, {pos} card, " + visual + ", "
        + BORDER_MARGIN_EN + ", symmetrical composition, centered, nothing cropped, "
        "portrait orientation, stars, crescent moon, mystical ambience, "
        "soft pastel colors, no text, masterpiece, best quality"
    )


def parse_draw_response(raw) -> list:
    """解析萌绘 comfyui_draw 的返回文本 → 本地图片路径列表。

    external=True（或萌绘历史 source 约定值）时萌绘返回 JSON 文本：
    {"image_paths": [...], "status": "ok"}（兼容旧的单数 image_path 字段，
    也兼容截图里只取 image_path 的写法）；容错：截取花括号段再解析，失败返回空表。
    """
    text = str(raw or "")
    data = {}
    try:
        loaded = json.loads(text)
        if isinstance(loaded, dict):
            data = loaded
    except Exception:
        m = re.search(r"\{.*\}", text, re.S)
        if m:
            try:
                loaded = json.loads(m.group(0))
                if isinstance(loaded, dict):
                    data = loaded
            except Exception:
                data = {}
    paths = data.get("image_paths") or []
    if not paths and data.get("image_path"):
        paths = [data["image_path"]]
    out = []
    for p in paths:
        if isinstance(p, str) and p.strip():
            out.append(p.strip())
    return out


# ---------- M7：道具经济（F22/D8，口径见 PRD「道具经济明细」） ----------

STARDUST_GRADE_BONUS = {
    "大吉": 20, "吉": 15, "中吉": 12, "小吉": 10, "凶": 14, "大凶": 18,
}


def stardust_reward(grade: str, streak: int, base: int = 10) -> int:
    """每日抽签的星尘奖励：基础 + 吉凶修正（越倒霉补偿越多）+ 连签加成（2/4/6 档）。"""
    if streak >= 30:
        streak_bonus = 6
    elif streak >= 7:
        streak_bonus = 4
    elif streak >= 3:
        streak_bonus = 2
    else:
        streak_bonus = 0
    return int(base) + STARDUST_GRADE_BONUS.get(grade, 10) + streak_bonus


# ---------- M8 / v1.11.11：每日牌库（塔罗 78 张 + 星语神谕卡 36 张） ----------

# 每张牌统一字段（两套牌形状完全一致，卡面与生图链路无需分支）：
#   cn/en          中英文牌名
#   suit/suit_cn   牌组（塔罗：major / wands / cups / swords / pentacles；
#                   神谕卡：moon / season / creature / elemental）
#   element        四元素（大阿卡纳与神谕卡为空）
#   deck           仅神谕卡带 "oracle"，塔罗缺省视为 "tarot"
#   group_en       牌组英文名（神谕卡用于生图事实清单的 Card group 行）
#   kw_up/kw_rev   正位 / 逆位关键词（卡面显示）
#   up/rev         正位 / 逆位解读（卡面显示，控制在两行内）
#   vzh_up/vzh_rev 正位 / 逆位牌面画面意象（中文，喂给 LLM 与自然语兜底）
#   ven_up/ven_rev 正位 / 逆位牌面画面意象（英文标签，喂给萌绘与 tags 兜底）
#
# 倒吊人这类「姿态就是牌义」的牌，正位意象里必须把关键姿态写死（UPSIDE DOWN），
# 否则模型一律画成站着的少女——用户反馈的「倒吊人都是正的」就是这么来的。
TAROT_MAJOR = [
    dict(cn="愚者", en="The Fool", suit="major", suit_cn="大阿卡纳", element="",
         kw_up="新起点 · 冒险 · 自由", kw_rev="鲁莽 · 迟疑 · 没准备",
         up="背起行囊就出发吧，路会教你怎么走。",
         rev="想太多反而迈不开步，先迈一小步就好。",
         vzh_up="少女背着小行囊站在晨光里的悬崖边，脚边一只小白狗，一手伸向天空，远处雪山",
         vzh_rev="少女在崖边回头张望，行囊散开、物件悬在半空，云层压低，脚步迟迟不落",
         ven_up="girl with a small satchel at a sunlit cliff edge, a little white dog at her feet, one hand reaching up, distant snow mountains, morning light",
         ven_rev="girl looking back hesitating at a cliff edge, satchel spilled open with belongings floating in midair, heavy low clouds, dim light"),
    dict(cn="魔术师", en="The Magician", suit="major", suit_cn="大阿卡纳", element="",
         kw_up="创造 · 行动 · 资源", kw_rev="空谈 · 分心 · 使不上劲",
         up="你手里其实什么都有，缺的只是把它们用起来。",
         rev="工具都摆好了却迟迟不动手，先挑最小的一件做。",
         vzh_up="少女一手举魔杖指向天空、一手指地，桌上摆着杯与剑与金币与木杖，头顶浮着无限符号光环",
         vzh_rev="魔杖垂下，桌上器物倾倒散乱，无限符号光环断成两截，光点变暗",
         ven_up="girl raising a wand toward the sky with one hand and pointing down with the other, a chalice a sword a coin and a wand on the table, glowing infinity halo above her head",
         ven_rev="wand lowered, table objects toppled and scattered, broken infinity halo, fading light"),
    dict(cn="女祭司", en="The High Priestess", suit="major", suit_cn="大阿卡纳", element="",
         kw_up="直觉 · 静谧 · 内在之声", kw_rev="自我怀疑 · 听信杂音",
         up="安静下来，答案早就藏在你的直觉里。",
         rev="别人的声音太吵了，先把自己的那条找回来。",
         vzh_up="少女端坐在黑白两根石柱之间，膝上摊着一卷卷轴，身后垂帘与一弯新月，脚边石榴纹样",
         vzh_rev="垂帘被风掀起，卷轴滑落在地，月影倒转，柱影歪斜",
         ven_up="girl seated between a black and a white pillar, an open scroll on her lap, veiled curtain behind her, crescent moon, pomegranate pattern at her feet",
         ven_rev="curtain blown open, scroll slipped to the floor, inverted crescent reflection, tilted pillar shadows"),
    dict(cn="皇后", en="The Empress", suit="major", suit_cn="大阿卡纳", element="",
         kw_up="丰饶 · 温柔 · 滋养", kw_rev="耗尽 · 忽略自己",
         up="好好犒劳自己，温柔和丰盛你都配得上。",
         rev="一直在照顾别人，今天记得也分一点给自己。",
         vzh_up="少女坐在麦田与花丛中的软垫上，怀里抱着一束麦穗，身后是溪流与森林，身旁一枚心形盾牌",
         vzh_rev="麦穗低垂发枯，花丛稀疏，溪流变浅，心形盾牌蒙上薄灰",
         ven_up="girl sitting on a cushion in a wheat field among flowers, holding a sheaf of wheat, stream and forest behind her, heart-shaped shield beside her",
         ven_rev="drooping dry wheat, sparse flowers, shallow stream, heart-shaped shield covered in dust"),
    dict(cn="皇帝", en="The Emperor", suit="major", suit_cn="大阿卡纳", element="",
         kw_up="秩序 · 稳固 · 掌控", kw_rev="固执 · 绷太紧",
         up="把节奏握在自己手里，今天你说了算。",
         rev="计划不必一丝不苟，留一点余地更舒服。",
         vzh_up="少女端坐石质王座，一手持权杖一手托宝球，背后是峻峭山岭，椅背刻着羊头纹饰",
         vzh_rev="王座裂了一道缝，权杖斜靠在扶手边，宝球滚落脚边，山岭被雾遮住",
         ven_up="girl seated on a stone throne, holding a scepter and an orb, rugged mountains behind her, ram-head carving on the throne",
         ven_rev="cracked throne, scepter leaning against the armrest, orb rolled onto the floor, misty mountains"),
    dict(cn="教皇", en="The Hierophant", suit="major", suit_cn="大阿卡纳", element="",
         kw_up="指引 · 传统 · 学习", kw_rev="照搬 · 被规矩困住",
         up="听听过来人的话，经验是今天最短的捷径。",
         rev="别人的经验可以参考，但不必照单全收。",
         vzh_up="少女立于两根石柱之间，戴三重冠饰，一手举起作祝福手势，面前两把交叉的金钥匙",
         vzh_rev="金钥匙倒置散开，冠饰歪了，祝福的手势收回胸前，柱间光线变窄",
         ven_up="girl standing between two pillars wearing a triple crown, one hand raised in blessing, two crossed golden keys before her",
         ven_rev="golden keys turned upside down and separated, tilted crown, hand lowered to her chest, narrow light between pillars"),
    dict(cn="恋人", en="The Lovers", suit="major", suit_cn="大阿卡纳", element="",
         kw_up="选择 · 契合 · 心意", kw_rev="摇摆 · 话说不清",
         up="跟随心意做选择，坦诚一点会更好。",
         rev="两边都想要时，先问自己真正舍不得哪个。",
         vzh_up="少女与自己在水面里的倒影对望，手边两枝并排的花，头顶太阳，身后一道淡彩虹，只有她一个人",
         vzh_rev="水中倒影错位碎开，两枝花各自倒向一边，彩虹褪成浅灰",
         ven_up="girl facing her own reflection on still water, two flowers side by side in her hand, sun above, faint rainbow behind her, single person only",
         ven_rev="broken displaced reflection on water, two flowers leaning apart, faded grey rainbow"),
    dict(cn="战车", en="The Chariot", suit="major", suit_cn="大阿卡纳", element="",
         kw_up="前进 · 意志 · 胜利", kw_rev="失控 · 用力过猛",
         up="目标已经明确，别踩刹车，冲就对了。",
         rev="方向比速度重要，先停下来把方向盘扶正。",
         vzh_up="少女站在星篷战车上握着缰绳，车前两尊发光的石兽雕像，车轮卷起细小的星尘",
         vzh_rev="车轮歪斜，缰绳松脱垂下，石兽雕像各自转向不同方向，星尘散落",
         ven_up="girl standing on a star-canopied chariot holding reins, two glowing stone beast statues at the front, stardust swirling around the wheels",
         ven_rev="skewed chariot wheel, loose dangling reins, beast statues turned away from each other, scattered stardust"),
    dict(cn="力量", en="Strength", suit="major", suit_cn="大阿卡纳", element="",
         kw_up="勇气 · 耐心 · 柔韧", kw_rev="气馁 · 跟自己较劲",
         up="不必声张，温柔而坚定就是最大的力量。",
         rev="今天别硬撑，允许自己先软下来一会儿。",
         vzh_up="少女轻轻托住一头温顺白狮的下巴，头上戴着花环，头顶浮着无限符号",
         vzh_rev="白狮转头避开，花环散落在地，无限符号的光变淡",
         ven_up="girl gently cupping the chin of a calm white lion, flower wreath on her head, glowing infinity symbol above",
         ven_rev="white lion turning its head away, flower wreath fallen on the ground, dim infinity symbol"),
    dict(cn="隐士", en="The Hermit", suit="major", suit_cn="大阿卡纳", element="",
         kw_up="沉思 · 独处 · 寻找", kw_rev="闷着 · 不肯开口",
         up="留一段独处时光，想清楚再出发也不迟。",
         rev="一个人想太久会绕圈，找个人说两句吧。",
         vzh_up="少女披着灰斗篷立在雪山顶，一手提六角星灯、一手拄长杖，脚下云海",
         vzh_rev="灯焰变得微弱并朝下垂，身影被雾遮住一半，长杖斜插在雪里",
         ven_up="girl in a grey cloak on a snowy peak, holding a six-pointed star lantern and a long staff, sea of clouds below",
         ven_rev="faint lantern flame pointing downward, figure half hidden in fog, staff tilted in the snow"),
    dict(cn="命运之轮", en="Wheel of Fortune", suit="major", suit_cn="大阿卡纳", element="",
         kw_up="转机 · 周期 · 好运", kw_rev="错过 · 节奏被打乱",
         up="转机就在眼前，轮到你时记得伸手接住。",
         rev="节奏乱了也别急，等下一圈转回来就好。",
         vzh_up="少女站在巨大的金色轮盘旁，轮缘刻着神秘符号，四角浮着云朵与星星，光从轮心散开",
         vzh_rev="轮盘明显倾斜、符号模糊，云层翻卷遮住大半轮面，光收回轮心",
         ven_up="girl beside a huge golden wheel with mystic symbols on its rim, clouds and stars in the four corners, light radiating from the hub",
         ven_rev="tilted wheel with blurred symbols, rolling clouds covering most of the wheel, light withdrawing into the hub"),
    dict(cn="正义", en="Justice", suit="major", suit_cn="大阿卡纳", element="",
         kw_up="公平 · 权衡 · 因果", kw_rev="偏心 · 迟迟不决",
         up="种什么因得什么果，今天行得正就好。",
         rev="别急着判对错，先把两边都听完整。",
         vzh_up="少女端坐两柱之间，右手举一把直剑、左手托持平的天平，身后垂着紫帘",
         vzh_rev="天平明显倾斜，剑尖朝下，一只托盘空着，紫帘皱起",
         ven_up="girl seated between two pillars, a straight sword in her right hand and a level balance scale in her left, purple curtain behind her",
         ven_rev="tilted balance scale, sword pointing down, one empty pan, wrinkled purple curtain"),
    dict(cn="倒吊人", en="The Hanged Man", suit="major", suit_cn="大阿卡纳", element="",
         kw_up="换个角度 · 暂停 · 释然", kw_rev="白等 · 迟迟不肯放下",
         up="卡住时换个视角，暂停也是一种前进。",
         rev="该松手了，一直挂着并不会等来答案。",
         vzh_up="少女被一只脚倒吊在 T 形木架上，整个人头下脚上，双手背在身后，头顶一轮柔和光环，神情平静，枝叶垂落，倒挂姿态是这张牌的关键",
         vzh_rev="绳索松开，少女重新落地站稳、低头揉着脚踝，空木架立在身后，光环轻轻飘在她头顶上方，云散开",
         ven_up="girl HANGING UPSIDE DOWN by one ankle from a T-shaped wooden gallows, head below feet, both hands behind her back, soft glowing halo above her head, calm expression, drooping leaves, upside-down pose is essential",
         ven_rev="the rope untied, girl standing upright on the ground again rubbing her ankle, empty wooden gallows behind her, halo floating above her head, clouds parting"),
    dict(cn="死神", en="Death", suit="major", suit_cn="大阿卡纳", element="",
         kw_up="告别 · 蜕变 · 新生", kw_rev="拖着 · 不肯翻篇",
         up="该翻篇的就翻篇，腾出手才接得住新的。",
         rev="不是不肯变，只是需要多一点时间告别。",
         vzh_up="少女手捧一朵深色玫瑰站在晨光里，身旁一匹配着空鞍的白马，远处升起太阳与一面黑旗，只有她一个人",
         vzh_rev="玫瑰重新绽成浅色，黑旗收起，枯枝抽出新芽，白马低头吃草",
         ven_up="girl holding a dark rose in dawn light, a white horse with an empty saddle beside her, rising sun and a black flag in the distance, single person only",
         ven_rev="rose blooming pale again, black banner folded away, new buds on a bare branch, white horse lowering its head"),
    dict(cn="节制", en="Temperance", suit="major", suit_cn="大阿卡纳", element="",
         kw_up="平衡 · 调和 · 适度", kw_rev="失衡 · 一口气太急",
         up="火候到了自然成，今天别急着求满。",
         rev="步子乱了，把一份力气分给休息就好。",
         vzh_up="少女一脚在水里一脚在岸上，把清水在两只金杯之间来回倾倒，头顶光环，岸边开着鸢尾花",
         vzh_rev="水洒到杯外，两只杯子一高一低，鸢尾花垂下，光环偏斜",
         ven_up="girl with one foot in water and one on the shore, pouring clear water between two golden cups, halo above her head, irises on the bank",
         ven_rev="water spilling outside the cups, two cups at uneven heights, drooping irises, tilted halo"),
    dict(cn="恶魔", en="The Devil", suit="major", suit_cn="大阿卡纳", element="",
         kw_up="觉察 · 破除执念 · 松绑", kw_rev="沉溺 · 自己吓自己",
         up="看清那个停不下来的执念，轻轻放下它。",
         rev="锁其实早就开了，别再替它守着了。",
         vzh_up="少女手腕上松松垂着并没有锁住的链条，身后是一团带羊角的暗影，手边一枚倒转的五角星",
         vzh_rev="链条自行滑落在地，羊角暗影退去，五角星转正，天边透进一道光",
         ven_up="girl with loose unfastened chains hanging from her wrists, a horned dark shadow behind her, an inverted pentagram beside her",
         ven_rev="chains slipped off onto the ground, horned shadow fading, pentagram turned upright, a ray of light at the horizon"),
    dict(cn="高塔", en="The Tower", suit="major", suit_cn="大阿卡纳", element="",
         kw_up="骤变 · 崩塌 · 重建", kw_rev="余震 · 勉强撑着",
         up="意外只是重建的序幕，塌过的地方更稳。",
         rev="摇摇欲坠的东西，早点自己拆更省心。",
         vzh_up="远处石塔塔顶被闪电击中、迸出冠冕状的火光，少女安然站在塔下台阶张开双手，乌云翻涌，只有她一个人",
         vzh_rev="塔身只留一道细裂纹，乌云散开，闪电只剩一点余光，少女低头捡起一块碎石",
         ven_up="stone tower struck by lightning at its crown with a crown-shaped burst of flame, girl standing safely on the steps below with open arms, storm clouds, single person only",
         ven_rev="tower with only a thin crack, storm clouds dispersing, faint lingering lightning, girl picking up a small stone"),
    dict(cn="星星", en="The Star", suit="major", suit_cn="大阿卡纳", element="",
         kw_up="希望 · 疗愈 · 星光", kw_rev="泄气 · 看不见光",
         up="许下的愿望已在路上，今晚抬头看看星光。",
         rev="光只是被云挡了一下，别急着不信它。",
         vzh_up="少女单膝跪在池边，双手各持一只水罐把清水倒进池里，夜空一颗大八角星与七颗小星，岸边鸢尾花",
         vzh_rev="水罐歪了、水洒在岸上，大星被薄云遮住一半，池面起雾",
         ven_up="girl kneeling by a pool pouring water from two jugs, one large eight-pointed star and seven small stars in the night sky, irises on the bank",
         ven_rev="tilted jugs spilling water onto the bank, large star half hidden by thin clouds, misty pool"),
    dict(cn="月亮", en="The Moon", suit="major", suit_cn="大阿卡纳", element="",
         kw_up="想象 · 梦境 · 潮汐", kw_rev="误会 · 越想越乱",
         up="暂时看不真切，别急着下结论。",
         rev="雾会散的，先把最坏的那个猜想放一放。",
         vzh_up="少女走在两座塔之间的小径上，夜空一轮带脸的满月，露珠悬在草尖，池水映着月影，只有她一个人",
         vzh_rev="满月被云半掩，小径缩短，两座塔的影子靠拢，月影碎在水面",
         ven_up="girl walking on a path between two towers, a face-like full moon in the night sky, dewdrops on grass, moon reflected in a pool, single person only",
         ven_rev="full moon half covered by clouds, shortened path, two tower shadows leaning together, broken moon reflection on water"),
    dict(cn="太阳", en="The Sun", suit="major", suit_cn="大阿卡纳", element="",
         kw_up="喜悦 · 成功 · 活力", kw_rev="透支 · 开心打了折",
         up="把开心写在脸上，今天你自带光芒。",
         rev="不用一直发光，歇一会儿也没关系。",
         vzh_up="少女站在向日葵花田里张开双臂，头顶一轮光芒四射的大太阳，身后一堵矮墙，只有她一个人",
         vzh_rev="太阳被薄云遮去一角，向日葵低头，少女收回手臂坐在矮墙边",
         ven_up="girl standing in a sunflower field with arms open wide, huge radiant sun above her, low stone wall behind her, single person only",
         ven_rev="sun partly veiled by thin clouds, drooping sunflowers, girl sitting by the low wall with arms folded"),
    dict(cn="审判", en="Judgement", suit="major", suit_cn="大阿卡纳", element="",
         kw_up="觉醒 · 召唤 · 重生", kw_rev="自责 · 反复回头看",
         up="听从内心那个声音，它很少出错。",
         rev="别再复盘旧账了，今天可以重新开始。",
         vzh_up="少女站在水面之上双手举起，云端一支号角洒下光，远处雪山，只有她一个人",
         vzh_rev="号角垂下，云雾下沉，少女一只手放低、侧身看向别处",
         ven_up="girl standing above still water with both arms raised, a trumpet in the clouds shedding light, distant snow mountains, single person only",
         ven_rev="trumpet lowered, clouds sinking, girl with one arm down and turning away"),
    dict(cn="世界", en="The World", suit="major", suit_cn="大阿卡纳", element="",
         kw_up="完成 · 圆满 · 远行", kw_rev="差一步 · 舍不得收尾",
         up="一段旅程正圆满落幕，再奔赴下一场。",
         rev="只差最后一点了，别在终点前停下。",
         vzh_up="少女在月桂花环中央单脚轻点起舞，双手各持一支短杖，四角浮着星与云，只有她一个人",
         vzh_rev="花环缺了一角，少女停住舞步，一支短杖落在地上，四角的星变暗",
         ven_up="girl dancing lightly at the center of a laurel wreath, a short wand in each hand, stars and clouds in the four corners, single person only",
         ven_rev="laurel wreath with a gap, girl pausing mid-dance, one wand fallen on the ground, dim corner stars"),
]


# 小阿卡纳：4 花色 × 14 阶位 = 56 张。花色给「道具 / 量词 / 四元素配色 / 语境」，
# 阶位给「正逆位关键词、解读与画面模板」，由 _build_minor 组合成 56 张互不重样的牌。
# 这样既把牌池从 22 张扩到标准 78 张，又不必维护 78 份几乎重复的整段文案。
TAROT_SUIT_DEFS = (
    dict(key="wands", cn="权杖", en="Wands", unit="支", element="火",
         prop_cn="开花木杖", prop_en="blossoming wooden wand",
         prop_en_plural="blossoming wooden wands",
         tone="热情与行动", palette_zh="暖橙与火光", palette_en="warm amber, ember orange, glowing sparks"),
    dict(key="cups", cn="圣杯", en="Cups", unit="只", element="水",
         prop_cn="盛着水光的金杯", prop_en="golden chalice with glowing water",
         prop_en_plural="golden chalices with glowing water",
         tone="心情与关系", palette_zh="水蓝与银辉", palette_en="soft aqua, moonlit blue, silver highlights"),
    dict(key="swords", cn="宝剑", en="Swords", unit="把", element="风",
         prop_cn="细长银剑", prop_en="slender silver sword",
         prop_en_plural="slender silver swords",
         tone="思绪与表达", palette_zh="冷银与薄紫", palette_en="cool silver, pale violet, misty grey"),
    dict(key="pentacles", cn="星币", en="Pentacles", unit="枚", element="土",
         prop_cn="刻星纹的金币", prop_en="golden coin with a star engraving",
         prop_en_plural="golden coins with star engravings",
         tone="日常与积累", palette_zh="苔绿与暖金", palette_en="moss green, warm gold, earthy brown"),
)

# kind: ace = 王牌（单件）/ pip = 数字牌（多件）/ court = 人物牌（手执一件）
TAROT_RANK_DEFS = (
    dict(cn="王牌", en="Ace", n=1, n_en="one", kind="ace",
         kw_up="新芽 · 契机 · 纯粹", kw_rev="错过 · 空转 · 起头难",
         up="一个崭新的开头正递到你手里，先接住。",
         rev="好机会在门口徘徊，别让犹豫替你关门。",
         vzh_up="少女双手捧起刚出现的{items}，细小光点像新芽一样向外散开，天空刚亮起来",
         vzh_rev="{items}悬在半空够不着，光点散落变暗，天空灰蒙蒙",
         ven_up="girl holding up {items_en}, tiny sprouts of light drifting outward, brightening dawn sky",
         ven_rev="{items_en} floating out of reach, dim scattered light spots, overcast sky"),
    dict(cn="二", en="Two", n=2, n_en="two", kind="pip",
         kw_up="权衡 · 选择 · 平衡", kw_rev="摇摆 · 拖延 · 两边顾不上",
         up="两条路都还开着，挑更想走的那条。",
         rev="左右摇摆最耗神，先定一个再说。",
         vzh_up="少女站在{items}之间，两手微微摊开像在权衡，脚下一条平静的小路",
         vzh_rev="{items}一高一低错开，少女侧过身避开，小路被雾切断",
         ven_up="girl standing between {items_en}, hands slightly open as if weighing a choice, calm path underfoot",
         ven_rev="{items_en} uneven and out of alignment, girl turning aside, path lost in fog"),
    dict(cn="三", en="Three", n=3, n_en="three", kind="pip",
         kw_up="初成 · 铺开 · 合作", kw_rev="停滞 · 各走各的 · 延期",
         up="事情有了雏形，往外再走一步就顺了。",
         rev="节奏没对上，先把话摊开说清楚。",
         vzh_up="{items}在少女身前一字排开，远处是开阔的地平线与微光",
         vzh_rev="{items}东倒西歪彼此错开，地平线被薄雾吞掉",
         ven_up="{items_en} lined up in front of the girl, open horizon, soft light",
         ven_rev="{items_en} scattered and tilted out of alignment, misty horizon"),
    dict(cn="四", en="Four", n=4, n_en="four", kind="pip",
         kw_up="稳固 · 休整 · 打底", kw_rev="僵住 · 松懈 · 不想动",
         up="底子打得不错，今天适合稳稳地歇一下。",
         rev="太舒服会变成卡住，起来走两步就好。",
         vzh_up="少女安坐，{items}围成稳稳的方形，背后一堵矮墙与静下来的云",
         vzh_rev="{items}围的方形缺了一角，矮墙落着碎屑，云重新压低",
         ven_up="girl sitting calmly, {items_en} forming a steady square, low wall behind her, still clouds",
         ven_rev="{items_en} forming a square with one corner missing, crumbling low wall, heavy clouds"),
    dict(cn="五", en="Five", n=5, n_en="five", kind="pip",
         kw_up="波折 · 缺口 · 调整", kw_rev="缓过来 · 修补 · 别自责",
         up="有点小缺口，补上就好，不必全盘重来。",
         rev="最难的那段过去了，慢慢收拾残局。",
         vzh_up="{items}里有一两件倾倒，少女低头看着空出来的位置，风吹散几片叶子",
         vzh_rev="倾倒的{items}被一件件扶正，叶落尽，天光重新透进来",
         ven_up="{items_en} with one or two toppled over, girl looking down at the empty spot, leaves blown by wind",
         ven_rev="{items_en} being set upright one by one, bare branches, light returning"),
    dict(cn="六", en="Six", n=6, n_en="six", kind="pip",
         kw_up="回暖 · 流动 · 被认可", kw_rev="回头看 · 迟疑 · 放不下",
         up="气氛正在回暖，顺着这股劲儿往前就好。",
         rev="总回头看会走慢，轻轻把旧事放下。",
         vzh_up="{items}排成两列，一道柔光从中间流过，少女伸手接着",
         vzh_rev="柔光折回身后，{items}排得疏密不齐，少女的手停在半空",
         ven_up="{items_en} in two rows, a soft ribbon of light flowing between them, girl reaching out gently",
         ven_rev="light flowing backward, {items_en} in uneven rows, girl's hand paused in midair"),
    dict(cn="七", en="Seven", n=7, n_en="seven", kind="pip",
         kw_up="坚持 · 盘点 · 守得住", kw_rev="疲惫 · 分心 · 想放弃",
         up="再守一会儿，你比自己以为的更耐得住。",
         rev="累了就先歇，别把坚持过成硬撑。",
         vzh_up="{items}叠成小小一座，少女侧身守在旁边，眼神笃定",
         vzh_rev="{items}滑落散了一地，少女垂下眼、肩膀松下来",
         ven_up="{items_en} stacked into a small pile, girl standing guard beside them, steady gaze",
         ven_rev="{items_en} slid off into a scattered pile, girl lowering her eyes, relaxed shoulders"),
    dict(cn="八", en="Eight", n=8, n_en="eight", kind="pip",
         kw_up="加速 · 推进 · 消息", kw_rev="卡住 · 反复 · 白忙",
         up="节奏快起来了，顺着它把事一件件清掉。",
         rev="忙得打转就先停一停，方向对了再快。",
         vzh_up="{items}带着流线从少女身边掠过，衣摆被风掀起，背景是飞快的星轨",
         vzh_rev="{items}横七竖八停在空中，星轨打结，少女皱眉站住",
         ven_up="{items_en} streaking past the girl with motion lines, wind lifting her skirt, fast star trails",
         ven_rev="{items_en} halted awkwardly in midair, tangled star trails, girl standing with a frown"),
    dict(cn="九", en="Nine", n=9, n_en="nine", kind="pip",
         kw_up="将成 · 守成 · 底气", kw_rev="戒备 · 耗损 · 太紧绷",
         up="离成了只差一点，稳住就是赢。",
         rev="别把力气都花在防备上，松一点更久。",
         vzh_up="{items}围成一道弧，少女抱臂站在弧心，姿态从容，月色温软",
         vzh_rev="弧缺了一口，{items}向外倒，少女不自觉地抱紧手臂",
         ven_up="{items_en} arranged in a graceful arc, girl standing at the center with folded arms, gentle moonlight",
         ven_rev="arc with a gap, {items_en} tipping outward, girl hugging her arms tightly"),
    dict(cn="十", en="Ten", n=10, n_en="ten", kind="pip",
         kw_up="圆满 · 收束 · 交棒", kw_rev="负担 · 放不下 · 硬扛",
         up="可以收尾了，好好给自己记上一笔。",
         rev="全背着太沉了，分一些出去也没关系。",
         vzh_up="{items}排成一道拱，少女抬头从拱下走过，天光落满肩头",
         vzh_rev="{items}压弯了拱，少女低头扛着最上面那件，影子拖得很长",
         ven_up="{items_en} forming an arch, girl walking beneath it looking up, light falling on her shoulders",
         ven_rev="bent arch of {items_en}, girl carrying the topmost piece with lowered head, long shadow"),
    dict(cn="侍从", en="Page", n=0, n_en="", kind="court",
         kw_up="消息 · 好奇 · 起步", kw_rev="分心 · 空话 · 三分钟热度",
         up="有个新消息值得点开看看，保持好奇。",
         rev="说得多做得少，先挑一件真的动手。",
         vzh_up="少女捧着{items}凑近端详，脚边一封没拆的信，眼里全是好奇",
         vzh_rev="信被随手丢在一边，{items}拿反了，少女东张西望",
         ven_up="girl holding {items_en} close and studying it curiously, an unopened letter at her feet",
         ven_rev="letter tossed aside, {items_en} held the wrong way up, girl looking elsewhere"),
    dict(cn="骑士", en="Knight", n=0, n_en="", kind="court",
         kw_up="行动 · 奔赴 · 直率", kw_rev="冒进 · 虎头蛇尾 · 急",
         up="想做就去做，今天的行动力站在你这边。",
         rev="慢半拍反而更稳，别被一时兴起带跑。",
         vzh_up="少女披着短斗篷快步向前，{items}举在身前，身后扬起细小的尘光",
         vzh_rev="少女急停回头，{items}差点脱手，尘光乱成一团",
         ven_up="girl in a short cape striding forward, {items_en} raised before her, tiny sparkling dust behind her",
         ven_rev="girl stopping abruptly and looking back, {items_en} nearly slipping from her hand, swirling dust"),
    dict(cn="王后", en="Queen", n=0, n_en="", kind="court",
         kw_up="包容 · 照料 · 细腻", kw_rev="过度付出 · 情绪化",
         up="你照顾得了别人，也照顾得了今天。",
         rev="别把自己排在最后，先歇一会儿。",
         vzh_up="少女坐在软椅上轻抚{items}，膝上搭着绒毯，四周暖光与小花",
         vzh_rev="绒毯滑到地上，{items}被搁在一旁，少女低头揉着太阳穴",
         ven_up="girl on a cushioned chair gently touching {items_en}, a soft blanket on her lap, warm light and small flowers",
         ven_rev="blanket slipped to the floor, {items_en} set aside, girl rubbing her temple"),
    dict(cn="国王", en="King", n=0, n_en="", kind="court",
         kw_up="掌控 · 定夺 · 可靠", kw_rev="固执 · 独断 · 听不进",
         up="该拍板就拍板，今天你比想象中可靠。",
         rev="留一点空间给别人，答案会更完整。",
         vzh_up="少女坐在石椅上握着{items}，背后一枚纹章，神情沉稳",
         vzh_rev="纹章歪挂，{items}横放在膝上，少女偏过头不看人",
         ven_up="girl seated on a stone chair holding {items_en}, a heraldic emblem behind her, composed expression",
         ven_rev="crooked heraldic emblem, {items_en} laid across her lap, girl turning her head away"),
)


def _build_minor() -> list:
    """4 花色 × 14 阶位 → 56 张小阿卡纳（纯函数，模块加载时算一次）。"""
    out = []
    for suit in TAROT_SUIT_DEFS:
        for rank in TAROT_RANK_DEFS:
            if rank["kind"] == "pip":
                items_cn = f"{rank['n']}{suit['unit']}{suit['prop_cn']}"
                items_en = f"{rank['n_en']} {suit['prop_en_plural']}"
            elif rank["kind"] == "ace":
                items_cn = f"一{suit['unit']}{suit['prop_cn']}"
                items_en = f"a single {suit['prop_en']}"
            else:
                items_cn = suit["prop_cn"]
                items_en = f"a {suit['prop_en']}"
            fmt = {"items": items_cn, "items_en": items_en}
            out.append(dict(
                cn=f"{suit['cn']}{rank['cn']}",
                en=f"{rank['en']} of {suit['en']}",
                suit=suit["key"], suit_cn=suit["cn"], element=suit["element"],
                kw_up=f"{rank['kw_up']} · {suit['tone']}",
                kw_rev=f"{rank['kw_rev']} · {suit['tone']}",
                up=f"{suit['tone']}上，{rank['up']}",
                rev=f"{suit['tone']}上，{rank['rev']}",
                vzh_up=rank["vzh_up"].format(**fmt) + f"，{suit['palette_zh']}色调",
                vzh_rev=rank["vzh_rev"].format(**fmt) + f"，{suit['palette_zh']}色调转暗",
                ven_up=rank["ven_up"].format(**fmt) + f", {suit['palette_en']}",
                ven_rev=rank["ven_rev"].format(**fmt) + f", dim {suit['palette_en']}",
            ))
    return out


TAROT_MINOR = _build_minor()
TAROT_DECK = list(TAROT_MAJOR) + TAROT_MINOR  # 78 张，顺序固定（种子派生依赖顺序，勿重排）


# ---------- v1.11.11：第二套牌「星语神谕卡」 ----------
#
# 78 张已经是标准韦特塔罗全集，塔罗这一支没有更多牌可加；想让每日抽到的牌
# 花样更多，只能引入第二套**独立**牌组。这里是本插件自创的 36 张神谕卡，
# 分 4 组各 9 张，每张都有自己独立的中英文牌名、正逆位关键词/解读/画面意象，
# 不走小阿卡纳那种「模板 × 花色」组合，所以不会有「四张牌长得一样」的观感。
# 沿用塔罗卡的字段形状（kw_up/rev、up/rev、vzh_*/ven_*），卡面与生图链路零改动。
ORACLE_GROUPS = {
    "moon": ("星月", "Moon & Stars"),
    "season": ("节气", "Seasons"),
    "creature": ("生灵", "Creatures"),
    "elemental": ("元素灵", "Elemental Spirits"),
}

ORACLE_DEFS = (
    # ---- 星月 9 张 ----
    dict(cn="新月", en="New Moon", suit="moon",
         kw_up="起始 · 留白 · 许愿", kw_rev="迟疑 · 空想 · 没开始",
         up="还没发生的事最自由，先悄悄许个愿。", rev="愿望停在纸上太久，今天做一件小的就好。",
         vzh_up="少女在深蓝夜空下双手合起捧着一道极细的银色月牙，四周几乎没有光，脚边一粒刚发芽的种子，靛蓝与银白",
         vzh_rev="银色月牙被云遮住只剩一圈淡影，少女摊开空空的手掌低头看，种子仍埋在土里，夜色转灰",
         ven_up="girl cupping a very thin silver crescent between both hands under a deep blue night sky, almost no light around her, one newly sprouting seed at her feet, indigo and silver white",
         ven_rev="thin silver crescent hidden behind clouds leaving only a faint halo, girl looking down at her empty open palms, seed still buried in soil, grey dim night"),
    dict(cn="娥眉月", en="Waxing Crescent", suit="moon",
         kw_up="微光 · 试探 · 慢慢来", kw_rev="畏缩 · 半途 · 怕被看见",
         up="一点点亮起来就够了，不必一次照满。", rev="别把刚冒头的小心思又藏回去。",
         vzh_up="少女侧身踮脚，用指尖轻触天边一弯正在变亮的细月，肩头落着几粒星屑，浅紫与银蓝",
         vzh_rev="少女把手缩回袖子里背过身，细月被薄云盖住一半，星屑落进草丛变暗，浅紫转灰",
         ven_up="girl standing on tiptoe and touching a slowly brightening thin crescent with one fingertip, a few star motes on her shoulder, pale violet and silver blue",
         ven_rev="girl withdrawing her hand into her sleeve and turning away, crescent half covered by thin cloud, star motes fallen into the grass and dimmed, grey violet"),
    dict(cn="上弦月", en="First Quarter Moon", suit="moon",
         kw_up="决断 · 推进 · 成形", kw_rev="拉扯 · 较劲 · 卡在中途",
         up="该拍板了，半途其实已经走完最难那段。", rev="两边都想要最耗神，先选一边站定。",
         vzh_up="少女站在一道把夜空分成明暗两半的半圆月前，一手向前伸出，脚下一条笔直的石阶，金与墨蓝对半",
         vzh_rev="半圆月歪向一侧，明暗分界倾斜，石阶在中间断开，少女两手各指一边停住，金光变淡",
         ven_up="girl standing before a half moon that splits the night sky into light and dark, one hand reaching forward, a straight stone stair underfoot, gold and deep blue halves",
         ven_rev="half moon tilted to one side, slanted light-dark divide, stone stair broken in the middle, girl pointing to both sides and frozen, faded gold"),
    dict(cn="盈凸月", en="Waxing Gibbous", suit="moon",
         kw_up="将满 · 打磨 · 再一步", kw_rev="急躁 · 贪多 · 差一口气",
         up="快好了，最后那点耐心比冲劲值钱。", rev="想一次做完反而拖慢，收一收手上的事。",
         vzh_up="少女仰头望着快圆起来的月亮，手里用软布细细擦亮一枚将满的银盘，暖金与月白",
         vzh_rev="少女同时抱着好几枚银盘，最上面那枚滑落倾斜，月亮缺口被云补暗，暖金褪成灰黄",
         ven_up="girl looking up at an almost full moon, carefully polishing a near-round silver disc with a soft cloth, warm gold and moon white",
         ven_rev="girl holding too many silver discs at once, the topmost one slipping and tilting, moon gap darkened by cloud, warm gold faded to dull grey"),
    dict(cn="满月", en="Full Moon", suit="moon",
         kw_up="圆满 · 照见 · 坦白", kw_rev="过曝 · 情绪 · 舍不得收",
         up="该看清的都看清了，坦坦白白说出口。", rev="光太亮反而晃眼，先把心放回肚子里。",
         vzh_up="少女站在巨大满月的正下方，湖面把月亮完整倒映出来，她张开双臂，银白与柔金",
         vzh_rev="满月白得刺眼，湖面倒影碎成波纹，少女抬手挡住眼睛微微侧身，银白泛冷",
         ven_up="girl standing directly beneath a huge full moon, a lake reflecting the moon perfectly, arms spread open, silver white and soft gold",
         ven_rev="full moon glaring overly bright, lake reflection broken into ripples, girl shielding her eyes and turning slightly aside, cold silver white"),
    dict(cn="月食", en="Lunar Eclipse", suit="moon",
         kw_up="遮掩 · 转机 · 真相", kw_rev="误会 · 恐惧 · 自己吓自己",
         up="被挡住的那部分，等一会儿就会露出来。", rev="多半是自己吓自己，先别急着下结论。",
         vzh_up="少女抬头看一轮被地球影慢慢吞成暗红铜色的月亮，手里提着一盏小灯，暗红与深靛",
         vzh_rev="暗红的月亮几乎全黑，少女把灯抱紧、影子拉长，云层压低，深靛近墨",
         ven_up="girl looking up at a moon slowly swallowed by earth shadow into dark copper red, holding a small lantern, dark red and deep indigo",
         ven_rev="copper moon almost fully black, girl hugging her lantern tightly with a long stretched shadow, low heavy clouds, near-black indigo"),
    dict(cn="流星", en="Shooting Star", suit="moon",
         kw_up="一瞬 · 机会 · 许愿成真", kw_rev="错过 · 空想 · 抓不住",
         up="机会只闪一下，伸手比想清楚更要紧。", rev="光走远了也没关系，下一颗还会来。",
         vzh_up="少女仰起脸、指尖划过一道斜穿夜空的流星尾迹，发梢与衣带被风扬起，亮银与宝蓝",
         vzh_rev="流星尾迹只剩一点将熄的余光，少女的手停在半空没赶上，夜空空落落，宝蓝转暗",
         ven_up="girl tilting her face up and tracing a shooting star trail slanting across the night sky with her fingertip, hair and ribbons lifted by wind, bright silver and sapphire blue",
         ven_rev="shooting star trail reduced to one fading spark, girl's hand paused in midair too late, empty night sky, darkened sapphire blue"),
    dict(cn="北极星", en="Polaris", suit="moon",
         kw_up="方向 · 笃定 · 不迷路", kw_rev="固执 · 绕远 · 认错方向",
         up="认准一个方向慢慢走，就不会走丢。", rev="太笃定也会走岔，抬头再对一次。",
         vzh_up="少女立在雪原上，头顶一颗特别亮的星垂直落下一道细光柱照在她脚前，深蓝与冷白",
         vzh_rev="光柱斜着落到别处，少女仍朝原方向迈步，星被薄云糊住，深蓝里多了灰雾",
         ven_up="girl standing on a snowfield, a very bright star overhead casting a thin vertical beam of light onto the ground before her feet, deep blue and cool white",
         ven_rev="beam of light slanting down somewhere else, girl still stepping in her original direction, star blurred by thin cloud, grey mist in the deep blue"),
    dict(cn="银河", en="Milky Way", suit="moon",
         kw_up="辽阔 · 连结 · 被托住", kw_rev="散漫 · 失焦 · 想太远",
         up="你不是一个人，抬头看看有多少光陪着。", rev="想得太远容易脚下踩空，先收回到今天。",
         vzh_up="少女躺在草坡上，一整条星河从她身侧横过夜空，指尖有细碎星尘连成线，靛紫与乳白",
         vzh_rev="星河散成零落光点、连线断开，少女坐起来抱着膝盖，视线落回地面，靛紫发灰",
         ven_up="girl lying on a grassy slope, a whole band of the milky way crossing the sky beside her, fine stardust linking into a line at her fingertips, indigo violet and milky white",
         ven_rev="milky way scattered into loose dots with the connecting line broken, girl sitting up hugging her knees, gaze dropped to the ground, grey indigo"),
    # ---- 节气 9 张 ----
    dict(cn="立春", en="First Spring", suit="season",
         kw_up="解冻 · 新芽 · 起身", kw_rev="倒春寒 · 犹豫 · 没力气",
         up="冻住的地方开始松了，动一下就暖。", rev="回暖得慢也别急，先把自己裹暖。",
         vzh_up="少女蹲在化开一半的溪边，指尖碰着冰面下第一片嫩绿新芽，浅绿与融雪白",
         vzh_rev="溪面重新结了薄冰，新芽缩回土里，少女把手收回袖口缩着肩，浅绿泛灰",
         ven_up="girl crouching beside a half-thawed stream, fingertip touching the first pale green shoot beneath the ice, light green and melting snow white",
         ven_rev="stream refrozen with a thin sheet of ice, shoot withdrawn into soil, girl pulling her hand back into her sleeve with hunched shoulders, greyish light green"),
    dict(cn="春分", en="Spring Equinox", suit="season",
         kw_up="平衡 · 对等 · 刚好", kw_rev="偏一边 · 失衡 · 难两全",
         up="两边刚好一样多，今天适合把话摊平。", rev="天平歪了就先别加码，扶正再说。",
         vzh_up="少女双手各托一朵同样大小的花，站在一道把白昼与黑夜均分的地平线上，嫩粉与浅青",
         vzh_rev="一朵花明显低下去，地平线倾斜，少女侧身去够矮的那边，嫩粉褪淡",
         ven_up="girl holding one flower of equal size in each hand, standing on a horizon that divides day and night evenly, tender pink and pale cyan",
         ven_rev="one flower hanging noticeably lower, tilted horizon, girl leaning sideways to reach the lower one, washed-out tender pink"),
    dict(cn="立夏", en="First Summer", suit="season",
         kw_up="舒展 · 热闹 · 长势", kw_rev="燥热 · 过猛 · 晒蔫",
         up="劲儿正足，把手伸开去做想做的事。", rev="太猛会先累着自己，躲半刻阴凉。",
         vzh_up="少女在浓绿树荫下张开手臂，藤蔓绕着她向上窜，光斑洒满裙摆，翠绿与明亮暖黄",
         vzh_rev="藤蔓垂下打蔫，叶片卷边，少女抬手遮着额头靠在树干上，暖黄晒得发白",
         ven_up="girl spreading her arms under lush green shade, vines climbing upward around her, dappled sunlight all over her skirt, vivid green and bright warm yellow",
         ven_rev="vines drooping wilted with curled leaf edges, girl leaning against the trunk shading her forehead with one hand, warm yellow bleached pale"),
    dict(cn="夏至", en="Summer Solstice", suit="season",
         kw_up="最盛 · 明亮 · 尽兴", kw_rev="透支 · 眩目 · 盛极转淡",
         up="今天最亮，尽管把喜欢的事做尽兴。", rev="亮到晃眼就歇一歇，别把力气一次用完。",
         vzh_up="少女站在正午最高的太阳下，影子短得几乎看不见，四周麦穗金浪翻涌，浓金与天青",
         vzh_rev="太阳略偏西，影子被拉长，几支麦穗垂下头，少女眯眼坐下，浓金转橘灰",
         ven_up="girl standing beneath the highest midday sun with an almost invisible short shadow, golden wheat rippling around her, rich gold and sky cyan",
         ven_rev="sun tilting westward, shadow stretched long, a few wheat ears drooping, girl squinting and sitting down, rich gold turned orange grey"),
    dict(cn="立秋", en="First Autumn", suit="season",
         kw_up="收敛 · 收获 · 转凉", kw_rev="恋夏 · 不甘 · 不肯收",
         up="该收的收进来，轻装一点更舒服。", rev="舍不得放手也会压沉，先挑一样放下。",
         vzh_up="少女抱着一小篮刚摘的果子，脚下第一片金叶落下，风把发梢吹向身后，琥珀金与浅棕",
         vzh_rev="篮子倾侧、果子滚落几颗，少女回头望向夏天的方向，金叶被风卷走，琥珀金变暗",
         ven_up="girl carrying a small basket of freshly picked fruit, first golden leaf falling at her feet, wind blowing her hair backward, amber gold and light brown",
         ven_rev="basket tipped with a few fruits rolling out, girl looking back toward summer, golden leaf blown away, darkened amber gold"),
    dict(cn="秋分", en="Autumn Equinox", suit="season",
         kw_up="平分 · 沉淀 · 妥帖", kw_rev="计较 · 摇摆 · 心不平",
         up="一半给事一半给自己，这样最妥帖。", rev="总在算谁多谁少，先把秤放下。",
         vzh_up="少女坐在石阶上，左右两堆落叶数量恰好相同，膝上摊着一本合起的书，赭红与米白",
         vzh_rev="一侧叶堆被风吹散变少，少女伸手去拨另一堆，书滑到地上，赭红转褐灰",
         ven_up="girl sitting on stone steps with two exactly equal piles of fallen leaves on either side, a closed book on her lap, ochre red and cream white",
         ven_rev="one leaf pile blown apart and smaller, girl reaching to adjust the other pile, book slipped to the ground, ochre red turned brownish grey"),
    dict(cn="立冬", en="First Winter", suit="season",
         kw_up="收藏 · 休养 · 向内", kw_rev="封冻 · 退缩 · 把自己关起来",
         up="把力气收回来，慢慢养比硬撑划算。", rev="别连门也一起关上，留条缝透透气。",
         vzh_up="少女在窗内裹着厚毯捧一杯冒热气的茶，窗玻璃上结着细小冰花，暖橘与雾白",
         vzh_rev="窗被霜糊得看不清外面，毯子堆在脚边，茶早凉了，少女抱膝背对窗，暖橘变冷灰",
         ven_up="girl wrapped in a thick blanket indoors holding a steaming cup of tea, tiny frost flowers on the window glass, warm orange and misty white",
         ven_rev="window frosted opaque, blanket piled at her feet, tea gone cold, girl hugging her knees with her back to the window, warm orange turned cold grey"),
    dict(cn="冬至", en="Winter Solstice", suit="season",
         kw_up="最长夜 · 回光 · 守候", kw_rev="熬着 · 怕黑 · 看不到头",
         up="夜最长的一天，光从明天起就多起来。", rev="别一个人硬熬，点盏小灯等天亮。",
         vzh_up="少女在最长夜里守着一盏小灯坐在门口，灯焰稳稳向上，天边有一线极淡的将明，墨蓝与暖黄",
         vzh_rev="灯焰被风吹得歪斜将熄，少女低头拢着火苗，天边那一线仍没亮，墨蓝压得更深",
         ven_up="girl keeping watch by a small lantern at her doorway on the longest night, flame steady and upright, one faint line of coming dawn at the horizon, ink blue and warm yellow",
         ven_rev="lantern flame blown sideways nearly out, girl bending low to cup the flame, the faint dawn line still unlit, deeper ink blue"),
    dict(cn="岁除", en="Year's Eve", suit="season",
         kw_up="辞旧 · 结清 · 轻装", kw_rev="拖账 · 留恋 · 翻不了篇",
         up="把旧的那页合上，明天就是新本子。", rev="总翻回前一页，新的一年就进不来。",
         vzh_up="少女把最后一页日历轻轻撕下叠好，桌上只剩一盏灯与一只空箱子，暖红与米金",
         vzh_rev="日历还挂着没撕，箱子里塞满没整理的旧物，少女坐着回头看，暖红转暗红",
         ven_up="girl gently tearing off and folding the last calendar page, only a lamp and an empty box left on the table, warm red and pale gold",
         ven_rev="calendar page still hanging unremoved, box stuffed with unsorted old things, girl sitting and looking back, warm red turned dark red"),
    # ---- 生灵 9 张 ----
    dict(cn="白猫", en="White Cat", suit="creature",
         kw_up="自在 · 直觉 · 不讨好", kw_rev="疏离 · 躲闪 · 不肯靠近",
         up="按自己的节奏来，不必谁的招呼都接。", rev="躲得太远会错过递过来的手，抬下头就好。",
         vzh_up="少女盘腿坐在窗台，一只白猫自在地蜷在她膝上，尾巴垂着轻晃，奶油白与浅灰蓝",
         vzh_rev="白猫缩到窗台角落背对着她，少女的手停在半空，窗台空出一大块，浅灰蓝转冷",
         ven_up="girl sitting cross-legged on a windowsill, a white cat curled comfortably on her lap with its tail hanging and swaying, cream white and pale grey blue",
         ven_rev="white cat shrunk into the corner of the windowsill facing away, girl's hand paused in midair, a large empty space left on the sill, cold pale grey blue"),
    dict(cn="夜枭", en="Night Owl", suit="creature",
         kw_up="看清 · 洞察 · 夜里清醒", kw_rev="多疑 · 熬夜 · 看太透",
         up="夜里反而最清醒，信你看见的那个细节。", rev="看太透会累，留一点不追究的余地。",
         vzh_up="少女肩头停着一只睁圆眼的夜枭，她借月光翻着一页摊开的书，深蓝与琥珀金",
         vzh_rev="夜枭半闭眼把头扭开，书页被风翻乱，少女揉着眼睛撑着额头，深蓝发灰",
         ven_up="girl with a wide-eyed night owl perched on her shoulder, turning an open page by moonlight, deep blue and amber gold",
         ven_rev="night owl half closing its eyes and turning its head away, book pages flipped messily by wind, girl rubbing her eyes and resting her forehead on one hand, greyish deep blue"),
    dict(cn="小狐", en="Little Fox", suit="creature",
         kw_up="机灵 · 转圜 · 俏皮", kw_rev="滑头 · 试探 · 绕圈子",
         up="换个说法就能过坎，机灵点没关系。", rev="绕太多圈反而没说到点上，直说试试。",
         vzh_up="少女蹲下身与一只橘色小狐对视，小狐翘着大尾巴把一片叶子递到她手心，橘金与苔绿",
         vzh_rev="小狐叼着叶子转身跑开、尾巴扫过草丛，少女伸出的手落空，橘金褪淡",
         ven_up="girl crouching to meet the eyes of a small orange fox, fox holding up a big fluffy tail and offering a leaf into her palm, orange gold and moss green",
         ven_rev="small fox turning away with the leaf in its mouth, tail sweeping through grass, girl's outstretched hand catching nothing, faded orange gold"),
    dict(cn="鲸歌", en="Whale Song", suit="creature",
         kw_up="深声 · 共鸣 · 被听见", kw_rev="沉底 · 闷着 · 无人回应",
         up="慢慢说也没关系，总有人接得住你。", rev="闷在心底会越沉越重，先出一点声。",
         vzh_up="少女站在浅蓝海水里，一头巨鲸在深处缓缓浮过，一圈圈声纹般的光波从水面荡开，深海蓝与青白",
         vzh_rev="鲸沉入更暗的深处只剩轮廓，光波散不成圈，少女低头看着静下来的水面，深海蓝近墨",
         ven_up="girl standing in pale blue water, a huge whale gliding slowly in the depths, rings of sound-wave-like light rippling out from the surface, deep sea blue and cyan white",
         ven_rev="whale sunk into darker depths leaving only an outline, light rings failing to form, girl looking down at the still water surface, near-black deep sea blue"),
    dict(cn="林鹿", en="Forest Deer", suit="creature",
         kw_up="轻步 · 敏感 · 温柔", kw_rev="惊跳 · 退缩 · 一有动静就跑",
         up="轻一点走，今天适合温柔地靠近。", rev="一点动静就躲，会错过原本安稳的地方。",
         vzh_up="少女在晨雾林间放轻脚步，一只小鹿从树后探出头与她对望，叶隙漏下细光，雾绿与暖白",
         vzh_rev="小鹿转身跃开只剩晃动的树枝，少女停在原地收住脚，雾更浓，雾绿转灰",
         ven_up="girl stepping softly through a misty morning forest, a small deer peeking out from behind a tree to meet her gaze, thin light through leaves, misty green and warm white",
         ven_rev="small deer turning and leaping away leaving only swaying branches, girl halted with her foot held back, mist thickening, grey misty green"),
    dict(cn="蝴蝶", en="Butterfly", suit="creature",
         kw_up="蜕变 · 轻盈 · 换模样", kw_rev="浮飘 · 三分钟 · 不肯落定",
         up="换了个模样的你，轻得能多走两步。", rev="总在飘就落不了地，先停在一件事上。",
         vzh_up="少女摊开手掌，一只刚破蛹的蝴蝶停在她指尖抖开翅膀，身后是空茧与晨光，浅粉与鹅黄",
         vzh_rev="蝴蝶在她头顶绕圈不停落，空茧垂着晃，少女抬手去够却总差一点，浅粉泛灰",
         ven_up="girl holding out her palm, a freshly emerged butterfly perched on her fingertip unfolding its wings, an empty chrysalis and morning light behind her, pale pink and soft yellow",
         ven_rev="butterfly circling above her head without landing, empty chrysalis swaying, girl reaching up and always just missing it, greyish pale pink"),
    dict(cn="月兔", en="Moon Rabbit", suit="creature",
         kw_up="陪伴 · 慢慢熬 · 有回响", kw_rev="空忙 · 重复 · 白费劲",
         up="慢慢熬的事会有回响，别嫌它久。", rev="同样的动作重复太久，换个法子吧。",
         vzh_up="少女坐在满月下看一只白兔一下一下捣着石臼，细小光粉随节奏浮起，月白与淡银",
         vzh_rev="石臼空了、木杵横搁在一边，白兔趴着不动，光粉散尽，月白转冷灰",
         ven_up="girl sitting under a full moon watching a white rabbit steadily pounding a stone mortar, fine glowing dust rising with each beat, moon white and pale silver",
         ven_rev="stone mortar empty with the pestle laid aside, white rabbit lying still, glowing dust all dispersed, cold grey moon white"),
    dict(cn="燕子", en="Swallow", suit="creature",
         kw_up="归巢 · 消息 · 顺路", kw_rev="迷航 · 迟归 · 错过季节",
         up="顺路带回的消息，正好是你等的那个。", rev="绕远了也没关系，认得回来的方向就好。",
         vzh_up="少女仰头看一只燕子掠回屋檐下的泥巢，嘴里衔着一枝新草，晴蓝与嫩绿",
         vzh_rev="燕子在岔开的屋檐间盘旋没落巢，新草掉在半空，少女踮脚张望，晴蓝蒙上灰",
         ven_up="girl looking up at a swallow sweeping back to its mud nest under the eaves, a fresh sprig of grass in its beak, clear blue and tender green",
         ven_rev="swallow circling between forked eaves without landing, sprig of grass dropping midair, girl standing on tiptoe searching the sky, clear blue veiled with grey"),
    dict(cn="萤火", en="Firefly", suit="creature",
         kw_up="微光 · 聚起来 · 一点点", kw_rev="忽明忽暗 · 散掉 · 怕被比下去",
         up="一点一点的光聚起来，就够照路了。", rev="别拿自己的微光跟别人的满月比。",
         vzh_up="少女张开双手，十几只萤火虫在她掌间连成一条弯弯的光带，草丛与夏夜，墨绿与暖黄",
         vzh_rev="萤火零星散开、光带断成几截，少女慢慢合拢手掌，墨绿更深、暖黄变弱",
         ven_up="girl opening both hands, a dozen fireflies linking into a curved ribbon of light between her palms, grass and summer night, dark green and warm yellow",
         ven_rev="fireflies scattered sparsely with the light ribbon broken into pieces, girl slowly closing her hands, darker green and weakened warm yellow"),
    # ---- 元素灵 9 张 ----
    dict(cn="火苗", en="Ember Sprite", suit="elemental",
         kw_up="热度 · 点燃 · 动手", kw_rev="蹿太快 · 烧尽 · 急躁",
         up="先动手点起来，热度会带着你往前。", rev="烧得太急容易早早熄，留点柴慢慢添。",
         vzh_up="少女双手护着一小簇稳稳向上的橘色火苗，火星像小精灵绕着她转，暖橘与炭红",
         vzh_rev="火苗猛蹿一下又矮下去只剩青烟，少女往后仰避开热浪，暖橘褪成灰烬色",
         ven_up="girl cupping both hands around a small steady upward orange flame, tiny ember sprites circling her, warm orange and charcoal red",
         ven_rev="flame flaring up sharply then shrinking to thin smoke, girl leaning back from the heat, warm orange faded to ash grey"),
    dict(cn="水珠", en="Water Droplet", suit="elemental",
         kw_up="柔软 · 包容 · 顺着走", kw_rev="漫溢 · 含糊 · 化掉边界",
         up="顺着今天的水势走，比硬顶省力得多。", rev="什么都答应会把自己漫没了，留条边。",
         vzh_up="少女托着一颗透亮的大水珠，里面映着缩小的星空，水面一圈圈缓纹，水蓝与银白",
         vzh_rev="水珠在她掌心摊开流散、映影碎掉，少女手指合不拢，水蓝变浑",
         ven_up="girl holding a large clear water droplet with a tiny reflected starry sky inside it, slow concentric ripples, water blue and silver white",
         ven_rev="water droplet spreading flat and running off her palm, reflection shattered, girl unable to close her fingers, muddy water blue"),
    dict(cn="风铃", en="Wind Chime", suit="elemental",
         kw_up="消息 · 回应 · 轻响", kw_rev="杂音 · 心浮 · 听不真切",
         up="有回应轻轻响了一下，别漏掉它。", rev="太多杂音混在一起，先安静半分钟。",
         vzh_up="少女侧耳站在檐下，一串银风铃被一阵微风拂出单一清响，纸条轻轻飘起，浅青与银",
         vzh_rev="风铃被乱风撞得七歪八响，纸条缠成一团，少女皱眉捂住一边耳朵，浅青泛灰",
         ven_up="girl tilting her head under the eaves, a silver wind chime stirred by a gentle breeze into one clear note, a paper strip floating up, pale cyan and silver",
         ven_rev="wind chime knocked askew by gusty wind into a jumble of notes, paper strip tangled, girl frowning and covering one ear, greyish pale cyan"),
    dict(cn="种子", en="Seedling", suit="elemental",
         kw_up="埋下 · 耐心 · 会发芽", kw_rev="埋太深 · 干等 · 不见动静",
         up="今天埋下的小东西，会自己慢慢长。", rev="光等不浇水可不行，给它一点动作。",
         vzh_up="少女跪在松软土上把一颗种子轻轻按进土里，指尖沾着泥，土面已有一线嫩绿顶出，褐土与新绿",
         vzh_rev="土面被踩得板实、种子还搁在旁边没埋，少女抱着空水壶坐着等，褐土发灰",
         ven_up="girl kneeling on loose soil pressing a seed gently into the earth, mud on her fingertips, a thin green shoot already pushing through, brown earth and fresh green",
         ven_rev="soil packed hard underfoot, seed still lying beside it unplanted, girl sitting with an empty watering can waiting, greyish brown earth"),
    dict(cn="雷光", en="Thunder Spark", suit="elemental",
         kw_up="顿悟 · 破局 · 一闪", kw_rev="惊吓 · 冲动 · 雷声大雨点小",
         up="想不通的那件事，今天会忽然亮一下。", rev="别被一声响吓得乱动，等光落定再走。",
         vzh_up="少女抬手指向一道劈开云层的细白雷光，发丝微微立起，眼里映着光，靛紫与电白",
         vzh_rev="雷光只剩远处一团散开的亮，云压得更低，少女缩回手眨着眼，靛紫转暗灰",
         ven_up="girl raising a hand toward a thin white lightning bolt splitting the clouds, hair slightly lifted, light reflected in her eyes, indigo violet and electric white",
         ven_rev="lightning reduced to a distant fading glow, clouds hanging lower, girl withdrawing her hand and blinking, dark grey indigo"),
    dict(cn="初雪", en="First Snow", suit="elemental",
         kw_up="洗净 · 安静 · 新白", kw_rev="冻住 · 冷场 · 覆得太厚",
         up="第一场雪把旧脚印都盖平了，重新走。", rev="盖太厚就什么都看不见，扫出一小块地。",
         vzh_up="少女伸出舌尖接住今年的第一片六角雪，肩头薄薄一层白，四周安静，雪白与浅灰蓝",
         vzh_rev="积雪压弯了枝、把小径整个埋住，少女抱着胳膊站在原地没处下脚，雪白泛青灰",
         ven_up="girl catching this year's first hexagonal snowflake on her fingertip, a thin layer of white on her shoulders, quiet all around, snow white and pale grey blue",
         ven_rev="heavy snow bending branches and burying the whole path, girl standing with folded arms with nowhere to step, bluish grey snow white"),
    dict(cn="晨雾", en="Morning Mist", suit="elemental",
         kw_up="朦胧 · 留余地 · 慢看清", kw_rev="迷路 · 遮掩 · 看不真切",
         up="看不清就慢半拍，雾会自己散。", rev="一直躲在雾里，路就更认不出来了。",
         vzh_up="少女走在及膝的晨雾里，前方树影一层层淡出来，她一手轻轻拨开面前的雾，乳白与浅金",
         vzh_rev="雾浓得连脚下的路都吞掉，少女停住四下张望，树影全糊成一片，乳白转铅灰",
         ven_up="girl walking through knee-deep morning mist, layers of tree shadows fading in ahead, one hand gently parting the mist before her, milky white and pale gold",
         ven_rev="mist thick enough to swallow the path underfoot, girl stopped and looking around, tree shadows blurred into one mass, leaden grey milky white"),
    dict(cn="彩虹", en="Rainbow", suit="elemental",
         kw_up="转晴 · 和解 · 有好结果", kw_rev="一晃就散 · 空欢喜 · 等不到",
         up="雨停了，之前那点别扭也一起放晴。", rev="等不到那道桥也没关系，雨确实停了。",
         vzh_up="少女从屋檐下探出半步，一道完整彩虹跨过刚收住的雨云，脚下积水映着光，淡彩七色与湿亮灰",
         vzh_rev="彩虹只剩一小段褪色的弧，雨云重新合拢，少女收回脚靠回门边，淡彩变灰",
         ven_up="girl stepping half out from under the eaves, a complete rainbow arching over freshly clearing rain clouds, light reflected in puddles at her feet, soft seven-colour pastel and wet grey",
         ven_rev="rainbow reduced to one short faded arc, rain clouds closing again, girl stepping back against the doorframe, pastel turned grey"),
    dict(cn="沙漏", en="Hourglass", suit="elemental",
         kw_up="时机 · 节奏 · 够用", kw_rev="漏太快 · 拖延 · 来不及",
         up="时间刚好够，按自己的节奏来就行。", rev="总说等一下，沙就漏完了，先倒过来。",
         vzh_up="少女双手扶着一只稳稳流沙的玻璃沙漏，上半与下半沙堆匀称，侧光把影子拉得柔和，琥珀金与暖棕",
         vzh_rev="沙漏歪斜、细沙卡在窄口洒了一桌，少女伸手去扶没扶稳，琥珀金变暗",
         ven_up="girl steadying a glass hourglass with both hands as sand flows evenly, balanced piles above and below, side light casting a soft shadow, amber gold and warm brown",
         ven_rev="hourglass tilted with sand stuck at the narrow neck and spilled across the table, girl reaching to steady it too late, darkened amber gold"),
)

# 补上分组名与牌组标识；字段形状与 TAROT_DECK 完全一致（element 留空，
# 让 llm_facts 的英文侧走 "Card group: <分类英文名>" 而不是编一个元素出来）。
ORACLE_DECK = [
    dict(c, deck="oracle", element="",
         suit_cn=ORACLE_GROUPS[c["suit"]][0], group_en=ORACLE_GROUPS[c["suit"]][1])
    for c in ORACLE_DEFS
]
ALL_CARDS = TAROT_DECK + ORACLE_DECK  # 114 张，顺序固定（种子派生依赖顺序，勿重排）


def tarot_deck(scope: str = "full") -> list:
    """按配置返回可用牌池（v1.11.11 起四种）。

    full   = 标准塔罗 78 张（旧默认值，保持兼容）
    major  = 22 张大阿卡纳
    oracle = 36 张星语神谕卡
    mixed  = 塔罗 78 + 神谕卡 36 = 114 张（新默认）
    未知值一律回落 full，配置写坏也不会抽不到牌。
    """
    s = str(scope or "full")
    if s == "major":
        return TAROT_MAJOR
    if s == "oracle":
        return ORACLE_DECK
    if s == "mixed":
        return ALL_CARDS
    return TAROT_DECK


def tarot_of(seed: bytes, scope: str = "full", deck: list | None = None) -> dict:
    """由种子确定今日牌（牌面、正逆位、按位解读与画面意象，纯函数可测）。

    v1.11.9 起正逆位不再只换个标签：关键词、解读、画面意象全部按位取。
    """
    cards = deck if deck is not None else tarot_deck(scope)
    card = cards[_sub_int(seed, "tarot", len(cards))]
    reversed_card = bool(_sub_int(seed, "tarot_rev", 2))
    tail = "_rev" if reversed_card else "_up"
    return {
        "name_cn": card["cn"],
        "name_en": card["en"],
        "suit": card["suit"],
        "suit_cn": card["suit_cn"],
        "element": card["element"],
        "keywords": card["kw" + tail],
        "interp": card["up" if not reversed_card else "rev"],
        "visual_zh": card["vzh" + tail],
        "visual_en": card["ven" + tail],
        "reversed": reversed_card,
        "label": "逆位" if reversed_card else "正位",
        # v1.11.11：牌种与分类英文名（塔罗牌缺省 tarot / ""），事实清单靠它
        # 决定写「今日塔罗」还是「今日星语神谕卡」
        "deck_kind": card.get("deck", "tarot"),
        "group_en": card.get("group_en", ""),
        "deck_size": len(cards),
    }


def complement_tarot(tarot: dict) -> dict:
    """旧 payload 兼容：按牌名反查，补齐画面意象等新增字段（只补不覆盖）。

    热更前抽过的签、以及 WebUI「重绘」读到的旧记录里只有六个旧字段；
    不补的话重绘出来的提示词又会退回「只有牌名」的老样子。
    """
    if not isinstance(tarot, dict):
        return {}
    out = dict(tarot)
    if (out.get("visual_zh") and out.get("visual_en") and out.get("suit")
            and out.get("deck_kind")):
        return out
    # v1.11.11：两套牌都要能反查（神谕卡的旧 payload 也要补得上画面意象）
    card = next(
        (c for c in ALL_CARDS
         if (out.get("name_cn") and c["cn"] == out["name_cn"])
         or (out.get("name_en") and c["en"] == out["name_en"])),
        None,
    )
    if card is None:
        out.setdefault("deck_kind", "tarot")
        return out
    tail = "_rev" if bool(out.get("reversed")) else "_up"
    for key, value in (
        ("visual_zh", card["vzh" + tail]),
        ("visual_en", card["ven" + tail]),
        ("suit", card["suit"]),
        ("suit_cn", card["suit_cn"]),
        ("element", card["element"]),
        ("deck_kind", card.get("deck", "tarot")),
        ("group_en", card.get("group_en", "")),
    ):
        if not out.get(key):
            out[key] = value
    return out
