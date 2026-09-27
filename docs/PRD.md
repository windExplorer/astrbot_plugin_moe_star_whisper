# 萌萌星语（astrbot_plugin_moe_star_whisper）需求分析 / PRD

> 状态：**待确认**（确认后冻结为开发依据）
> 仓库：`github.com/windExplorer/astrbot_plugin_moe_star_whisper`（已建，现为 helloworld 模板，master 分支）
> 本文档先放工作区 `docs/`，插件成形后移入仓库 `docs/`（沿 user_gateway 先例）。
> 撰写日期：2026-09-27。技术结论均已对照 `_Refs/AstrBot`（4.28.1）源码核实。

---

## 0. 决策记录

| # | 问题 | 结论 | 日期 |
| --- | --- | --- | --- |
| D1 | 主指令名 | ✅ `/运势`（别名 `/今日运势` `/星语` `/占卜`） | 2026-09-27 |
| D2 | 吉凶体系 | ✅ 日式六档：大吉/吉/中吉/小吉/凶/大凶，权重可配 | 2026-09-27 |
| D3 | LLM 增强文案 | ✅ 做成可选增强，默认关；无 LLM 自动回退本地模板 | 2026-09-27 |
| D4 | 首发范围 | ✅ 全家桶：M0-M7 全量完成后以 v1.0.0 首次公开发布；开发期按里程碑递增 v0.x | 2026-09-27 |
| D5 | 重复抽签 | ✅ 一天仅可抽一次，签**全局统一**（跨群/私聊同一张）；重复请求**直接回发已存卡片**（v3 修订：由「婉拒」改为「回发缓存卡」，零生成成本） | 2026-09-27 |
| D6 | 绘图联动 | ✅ 接 astrbot-comfyui-anima `comfyui_draw`（source 换 JSON 路径），工作流与提示词约束可配 | 2026-09-27 |
| D7 | 数据落库 | ✅ 抽签/档案/绘图任务全量落 SQLite，为统计功能（F24）预留口径 | 2026-09-27 |
| D8 | 道具经济 | ✅ 做：插件内**独立「星尘」**积分（不对接 user_gateway 额度——两者语义不同，留 ledger 流水可迁移）+ 四道具，明细见 §4 | 2026-09-27 |
| D9 | 卡面话语 | ✅ 卡面不止吉凶：签文/话语是卡面主体文字区（F6 升级为卡面主角） | 2026-09-27 |
| D10 | 身份快照 | ✅ 落库用户QQ号、昵称、头像、群号/群名（抽签时快照）；卡面头部展示 头像+昵称+**QQ号** | 2026-09-27 |
| D11 | 绘图=底图 | ✅ anima 出图不单独发送，作为**卡面底图**合卡发送；**尺寸随卡布透传**（width/height 参数）；底图一人一天一张（种子含用户）；成品卡按 QQ 号落盘 `cards/<qq>/<date>.png`，重复发送直接取盘 | 2026-09-27 |

---

## 1. 背景与目标

### 1.1 是什么

群聊娱乐向「今日运势」插件：每个用户每天抽一次专属运势，以**萌系淡彩图卡 + 文案**回复。
取名「萌萌星语」，走**占星/星语**主题人设：bot 扮演「星语者」，每天为群友解读星象。

### 1.2 要解决的问题（同类插件常见痛点）

- **刷运势**：随机数每次刷新结果都变 → 失去「命运感」。本插件核心采用**每日确定论**（见 §3.1）。
- **响应慢 / 依赖重**：不少同类插件强依赖 LLM 或 headless 浏览器。本插件默认**纯本地词库 + Pillow 渲染**，零 LLM 成本、零 playwright 依赖，LLM 只做可选增强。
- **千卡一面**：固定模板看两天就腻。通过**幸运色驱动卡面配色 + 当日多维组合**（吉凶 × 幸运色 × 星象相位 × 宜忌），同一模板每天都有不同观感；开启绘图联动（D11）后，AI 生成的底图更让每张卡独一无二。
- **数据丢失**：安装目录升级即清空。数据一律落 `StarTools.get_data_dir()`（`data/plugin_data/`），沿 model_panel v1.4.4 的成熟做法。

### 1.3 目标 / 非目标

**目标**
1. 一条指令出一张好看的当日运势卡，3 秒内回复。
2. 结果当日稳定：同一用户当天在任何时刻、任何群查询结果一致。
3. 有可持续玩的社交层：连续抽签 streak、群榜、PK。
4. 无 LLM 也能完整运行；有 LLM 时文案更灵动（可开关）。

**非目标（v1 明确不做）**
- 不做积分/货币系统（道具、改运卡涉及经济体系，复杂度大增，见 §4 P2 与开放问题 Q6）。
- 不做多语言界面（工作区约定：文案只做中文）。
- 不做与 AstrBot 内置「定时任务」面板的深度集成（见 §7.5 定时方案说明）。
- 不自己实现 ComfyUI 客户端——绘图一律联动 astrbot-comfyui-anima（见 §7.6；anima 对接文档明令禁止旁路实现）。

---

## 2. 命名与人设

| 项 | 值 |
| --- | --- |
| 插件名（`metadata.yaml` name，须与目录一致） | `astrbot_plugin_moe_star_whisper` |
| 展示名 display_name | `萌萌星语` |
| 分类 category | `entertainment` |
| 版本起点 | `v0.1.0`（新插件自 v0.1.0 起计，沿 user_gateway / box 先例） |
| 人设 | 「星语者」：温柔、微傲娇的占星见习生，文案带少许emoji，不过度卖萌 |

---

## 3. 核心设计原则

### 3.1 每日确定论（灵魂机制）

运势不是即抽即随机，而是由**种子**确定性推导：

```
seed = SHA-256(f"{date}|{user_id}|{salt}")     # date 为插件时区的当日 YYYY-MM-DD
```

- seed 展开（分段切片）独立驱动每个维度：吉凶等级、六维星数、幸运物/色/数字、宜忌各一条、签文模板与填空、星象相位。
- 效果：**当天重复查询结果恒定**（跨时刻、跨群一致），次日自动换签。防刷、有「这就是你今天的命」的仪式感。
- `salt` 为配置项：改 salt = 全员重掷（运营留后手）。
- 首次抽签落库并把成品卡落盘（`cards/<qq>/<date>.png`，§6）；**当日重复请求（含跨群、私聊）直接回发盘上这张卡**——不重算、不重绘、不重新生成（D5 修订），运势本身仍一日一签，次日自动换签。

### 3.2 粒度：个人专属（推荐）

- 运势跟人走（user_id），在哪个群查都一样——避免「群A大吉群B大凶」的认知混乱。
- 「全群同一支公共签」作为独立功能（今日群签）放 P2，见 §6。

### 3.3 三个数字的学问

- 吉凶权重：`大凶 5% / 凶 10% / 小吉 15% / 中吉 25% / 吉 25% / 大吉 20%`（可配）。大吉占比略高于传统十取一，群里更欢乐；权重全部可配。
- 六维星数（1~5 ★）：恋爱 / 学业·工作 / 财运 / 健康 / 社交 / 摸鱼。
- 幸运指数（0~100）：由六维星数加权合成，用于榜单与 PK 的单一可比口径。

---

## 4. 功能清单

### P0 —— 核心抽签（MVP，对应 M1/M2）

| # | 功能 | 说明 |
| --- | --- | --- |
| F1 | `/运势` 主指令 | 输出当日运势卡（图）：身份头（头像+昵称+QQ号，D10）→ 吉凶大字 → 签文话语（D9）→ 六维 → 宜忌 → 幸运物区 → 落款；文本模式可配（`输出方式: 图卡/纯文本/两者`，纯文本兜底渲染失败场景） |
| F2 | 吉凶等级 | 大吉→大凶 六档（D2 确认后冻结），卡面大字 + 主题色随吉凶变化 |
| F3 | 六维星数 + 幸运指数 | ★★★☆☆ 样式；幸运指数 0~100 大数字 |
| F4 | 幸运物 / 幸运色 / 幸运数字 / 幸运方位 | 各一，从词库按种子抽取；**幸运色同时决定当日卡面配色**（每张卡观感不同） |
| F5 | 今日宜忌 | 宜×2 + 忌×2，萌化词库（宜：摸鱼、奶茶、早睡；忌：内卷、说大话、深夜emo…） |
| F6 | 签文话语（D9） | 本地模板池 + 槽位填充（模板 × 幸运物 × 星象相位组合），按吉凶分池；**卡面主体文字区**，2~3 句（吉凶点评 + 幸运物联动 + 一句祝语），不是配角 |
| F7 | 一日一签 | §3.1；签全局唯一（跨群/私聊一致），当日重复请求直接回发已存卡（D5 修订），次日自动换签 |
| F8 | 群开关 | `/运势开关`（管理员）：按群启用/停用；全局默认开 |
| F9 | 配置页 | `_conf_schema.json`（AstrBot 自动生成 WebUI 配置，源码 star_manager.py:212 已核实） |

### P1 —— 群玩法（对应 M3/M4）

| # | 功能 | 说明 |
| --- | --- | --- |
| F10 | 连续抽签 streak | 连续天数记录；3/7/14/30 天徽章文案彩蛋；断签不惩罚（娱乐定位） |
| F11 | `/运势榜` | 今日群内幸运指数排行（按当日抽签记录）；`/运势榜 周` 看本周累计 |
| F12 | `/运势PK @某人` | 双方当日幸运指数对比，胜方专属嘲讽/彩虹屁文案（也是种子确定） |
| F13 | 星座绑定 | `/星语绑定 <生日MM-DD>` → 存星座；运势卡显示星座角标，签文拼入星座元素；`/星语 @某人` 查看他人星座（仅公开信息：星座+今日吉凶，不泄露生日） |
| F14 | 特殊日期彩蛋 | 用户生日（当天大吉 + 专属卡面描边）；4/1 全员「大吉（？）」整活签；春节/圣诞/元旦等节日词库池；周五摸鱼加成文案 |
| F15 | 暗色卡面 | 按消息环境或配置自动切暗色主题（Pillow 双主题） |
| F23 | 运势绘图（D6/D11） | anima 联动：LLM 依当日运势生成提示词 → `comfyui_draw` 出图（尺寸透传）→ **作为卡面底图**合卡发送（不单独发图），成品卡按 QQ 号落盘复用；失败静默回退幸运色默认底图，见 §7.6 |
| F22 | 道具经济（D8） | 独立「星尘」积分 + 四道具 + 商店/背包/补签/发放；明细见下方小节，数据见 §6，配置见 §8 |

#### 道具经济明细（F22/D8）

- **货币「星尘」**：本插件内部流通的娱乐积分，**不可转账、不可兑换**（无经济风险；口径决策 D8：不对接 user_gateway，其额度是「LLM 配额」语义）。来源：每日抽签基础 +10；吉凶修正（大吉 +20 / 吉 +15 / 中吉 +12 / 小吉 +10 / 凶 +14 / 大凶 +18——越倒霉补偿越多）；连续加成（streak≥3 每日 +2、≥7 +4、≥30 +6）。所有增减写 `ledger` 流水（§6）。
- **道具四件套**（价格为默认值，可在配置调整）：

| 道具 | 效果 | 使用时序 | 默认价 | 限制 |
| --- | --- | --- | --- | --- |
| 换签卡 | 当日重抽一次，新结果**覆盖**旧结果（重抽 nonce 派生新种子，完整重做一次卡：运势与 AI 底图都按新种子重新生成） | 抽签后 | 80 | 持有 ≤3，每日限用 1 张 |
| 厄运护身符 | 当日抽签若为 凶/大凶，保底升为 小吉 | 抽签前 | 50 | 持有 ≤3 |
| 连签保护卡 | 断签 3 天内 `/运势补签` 补回昨天（按昨日种子重算落库），streak 恢复 | 断签后 | 30 | 持有 ≤3 |
| 幸运香烛 | 当日幸运指数 +8（不影响吉凶档与词库抽取） | 抽签前 | 20 | 持有 ≤3 |

- **设计取舍**：换签采用**覆盖式而非新旧二选一**——「换卡换出大凶」是群里最好的节目效果，也保住一日一签的紧张感；护身符（事前保险）与换签卡（事后救济）形成事前/事后互补，避免同质道具堆叠。

### P2 —— 远期（按反馈决定做不做）

> 注：D4 确认「全家桶」首发后，F16 / F17 / F22 / F23 均已纳入首发范围（见 §9）；本节仅剩 F18-F21 与预留的 F24（统计，D7 只落库不出报表）。

| # | 功能 | 说明 |
| --- | --- | --- |
| F16 | LLM 星语 | 见 §7.4；对当日签文做个性化扩写（可开关、当日缓存、无 LLM 自动回退本地模板） |
| F17 | 每日群推送 | 早晨指定时间向开启的群推送「今日群签/星象日历」卡。AstrBot 无插件侧定时装饰器（见 §7.5），需插件自管 asyncio 定时循环 + `context.send_message` |
| F18 | 今日群签 | 全群共享一支公共签（seed 里放 group_id 不放 user_id），制造群话题 |
| F19 | `/塔罗` | 每日一张塔罗牌（正/逆位），与主运势独立 |
| F20 | `/运势月报` | 当月个人吉凶分布、最幸运一天、抽签坚持天数 |
| F21 | WebUI 词库管理面板 | Vue3+NaiveUI 管理宜忌/签文/幸运物词条（增删改、启停、权重），仅管理员 |
| F24 | 统计功能（预留） | 基于 D7 全量落库的后续统计（吉凶分布、绘图成功率、streak 榜、星尘收支…）；本期只存不算 |

---

## 5. 指令设计草案

| 指令 | 别名 | 权限 | 说明 |
| --- | --- | --- | --- |
| `/运势` | `/今日运势`、`/星语`、`/占卜` | 所有人 | 抽当日运势卡 |
| `/运势榜 [日\|周]` | - | 所有人 | 群内排行榜（仅群聊可用） |
| `/运势PK @用户` | - | 所有人 | 当日幸运指数对决 |
| `/星语绑定 <MM-DD>` | `/运势绑定` | 所有人 | 绑定生日→星座（仅存月日，不存年份） |
| `/运势开关 [on\|off]` | - | 群管理员 | 群级启停 |
| `/运势重载词库` | - | AstrBot 管理员 | 热更自定义词库（若做 F21 则保留，否则去掉） |

主指令名 D1 确认后冻结；`/星语` 若不作主指令则保留为别名。所有指令在私聊同样可用（榜单/PK 除外）。

绘图联动（F23）无独立指令，跟随 `/运势` 自动进行，可在配置页开关。道具经济（F22）指令：

| 指令 | 别名 | 权限 | 说明 |
| --- | --- | --- | --- |
| `/星尘` | `/运势背包` | 所有人 | 查星尘余额与持有道具 |
| `/运势商店` | - | 所有人 | 道具与价格一览 |
| `/运势购买 <道具> [数量]` | - | 所有人 | 购买道具（星尘不足时提示差多少） |
| `/运势使用 <道具>` | - | 所有人 | 使用道具（换签卡 / 厄运护身符 / 幸运香烛） |
| `/运势补签` | - | 所有人 | 断签 3 天内消耗连签保护卡补签 |
| `/运势发放 @用户 <±n>` | - | AstrBot 管理员 | 手动调整星尘（必走流水） |

---

## 6. 数据模型（SQLite，落 `StarTools.get_data_dir`；D7：全量落库为统计预留）

库文件：`data/plugin_data/astrbot_plugin_moe_star_whisper/star_whisper.db`

```sql
-- 当日抽签结果（榜单依据；(user_id, date) 主键天然保证一日一签，D5：重复 INSERT 直接拒绝）
CREATE TABLE fortunes (
  user_id   TEXT NOT NULL,          -- QQ号（event.get_sender_id() 原值；形状约定见 §7.7）
  date      TEXT NOT NULL,          -- YYYY-MM-DD（插件时区）
  grade     TEXT NOT NULL,          -- 大吉/中吉/...
  score     INTEGER NOT NULL,       -- 幸运指数 0~100
  payload   TEXT NOT NULL,          -- 完整结果 JSON（六维/幸运物/宜忌/签文/卡面色…）
  nickname  TEXT,                   -- 抽签时昵称快照（D10）
  avatar    TEXT,                   -- 抽签时头像 URL 快照（D10；QQ 平台 qlogo 兜底）
  group_id  TEXT,                   -- 抽签所在群（可空 = 私聊，D10）
  group_name TEXT,                  -- 群名快照（可空）
  created_at TEXT NOT NULL,
  PRIMARY KEY (user_id, date)
);

-- 用户档案（streak 与星座）
CREATE TABLE profiles (
  user_id      TEXT PRIMARY KEY,
  birthday     TEXT,                -- MM-DD（可空；不存年份）
  constellation TEXT,               -- 白羊座…（绑定生日时推导）
  nickname     TEXT,                -- 最近一次昵称快照（D10，榜单/PK 展示用）
  avatar       TEXT,                -- 最近一次头像 URL 快照（D10）
  streak       INTEGER DEFAULT 0,
  last_draw_date TEXT,              -- 上次抽签日期（断签判定）
  max_streak   INTEGER DEFAULT 0
);

-- 绘图任务（D6/D7）：每次「今日星象图」生成的全链路记录，统计功能（F24）的数据源
CREATE TABLE draw_jobs (
  id          INTEGER PRIMARY KEY AUTOINCREMENT,
  user_id     TEXT NOT NULL,
  date        TEXT NOT NULL,        -- YYYY-MM-DD（插件时区；一人一天最多一条，D5）
  workflow    TEXT,                 -- 使用的工作流名（空 = anima 默认）
  prompt_lang TEXT,                 -- en / zh（D6 提示词语言约束）
  prompt_fmt  TEXT,                 -- tags / natural
  image_prompt TEXT NOT NULL,       -- LLM 生成的最终绘图提示词（原文落库）
  llm_prompt  TEXT,                 -- 送审的完整模板渲染结果（排障用）
  status      TEXT NOT NULL,        -- ok / timeout / error / skipped_no_anima
  error       TEXT,
  duration_ms INTEGER,
  image_path  TEXT,                 -- 成功时的本地路径（取 anima 返回 image_paths[0]，仅作追溯）
  card_path   TEXT,                 -- 我方成品卡落盘路径 cards/<qq>/<date>.png（当日复用依据）
  created_at  TEXT NOT NULL
);

-- 背包（D8）
CREATE TABLE items (
  user_id TEXT NOT NULL,
  item_id TEXT NOT NULL,            -- reroll / amulet / streak_guard / candle
  count   INTEGER NOT NULL DEFAULT 0,
  PRIMARY KEY (user_id, item_id)
);

-- 星尘流水（D8）：每一笔增减都有记录，统计（F24）与审计的依据
CREATE TABLE ledger (
  id         INTEGER PRIMARY KEY AUTOINCREMENT,
  user_id    TEXT NOT NULL,
  delta      INTEGER NOT NULL,      -- 正负皆可
  reason     TEXT NOT NULL,         -- draw / streak / buy / use / admin / festival
  ref_date   TEXT,                  -- 关联的抽签日期（可空）
  created_at TEXT NOT NULL
);
```

- `fortunes.payload` 同时记录当日加成状态（护身符生效、香烛 +8、换签 reroll_count），保证统计口径一致。
- **成品卡自持落盘（D11）**：`data/plugin_data/astrbot_plugin_moe_star_whisper/cards/<qq>/<date>.png`（成品卡）与 `<date>_bg.png`（底图原件，换签对比/重合成用）——**不依赖 anima 的图库目录**（其可能被清理或迁移，防止日后取不到）；当日重复发送直接读盘，`draw_jobs.image_path` 仅作追溯。
- 不建词库表：内置词库走 Python/JSON 文件随包分发；自定义词库（F21）做之前都无需入库。
- 榜单/PK 直接 `SELECT` 当日 `fortunes`；月报按 `date` 前缀聚合；星尘收支按 `ledger.reason` 聚合。

---

## 7. 技术方案

### 7.1 模块划分（相对导入；新增顶层模块须同步 $includeList 与热重载列表）

```
main.py            # 入口：指令注册、initialize/terminate
fortune.py         # 核心：种子展开、吉凶、六维、指数合成（纯函数，可单测）
lexicon.py         # 词库加载：内置 JSON 池（宜忌/签文/幸运物/相位/节日）
card.py            # Pillow 渲染（淡彩萌系、幸运色换装、双主题）
store.py           # SQLite 读写（fortunes / profiles）
llm.py             # （F16）LLM 签文扩写，可选
data/lexicon/*.json# 内置词库数据文件
tests/             # 纯函数测试，直接 python tests/xxx 运行（沿 model_panel 惯例）
build_zip.ps1      # 打包（显式 $includeList + 顶层 .py 守卫，沿 box/user_gateway 模式）
```

### 7.2 已核实的 AstrBot 4.28.1 API 依据

| 用途 | API | 源码位置 |
| --- | --- | --- |
| 指令注册 | `@filter.command` / `@filter.command_group` | `astrbot/api/event/filter/__init__.py` |
| 管理员过滤 | `@filter.permission_type(PermissionType.ADMIN)` | 同上 |
| 取发送者/群 | `event.get_sender_id()` / `event.get_group_id()` | `astrbot/core/platform/astr_message_event.py` |
| 回复图卡 | `yield event.image_result(path)` | astr_message_event.py:408 |
| 回复文本 | `yield event.plain_result(text)` / `event.chain_result([...])` | astr_message_event.py:404/417 |
| 图片组件 | `Image.fromFileSystem / fromBytes` | `astrbot/core/message/components.py:501+` |
| 数据目录 | `StarTools.get_data_dir(name)` | `astrbot/core/star/star_tools.py:244` |
| 配置页 | `_conf_schema.json` 自动生成 | star_manager.py:212 |
| LLM 调用 | `context.get_using_provider()` → `provider.text_chat(...)` | star/context.py:482、provider/provider.py:100 |
| 主动推送 | `context.send_message(session, chain)` | star_tools.py:35（F17 用时核对签名） |
| HTML 渲染 | `self.html_render(tmpl, data)`（备选，弃用理由见 §7.3） | star/base.py:92 |

### 7.3 图卡渲染：选 Pillow，不选 html_render

- `html_render` 依赖 playwright/浏览器环境，部分用户部署跑不起来；Pillow 只要 `pillow` 依赖（requirements.txt 声明），覆盖面广、启动无浏览器开销。
- model_panel 的 `card_render.py` 已趟平：字体多级查找（配置路径 → `data/plugin_data/<名>/fonts/` → `data/fonts/` → 系统）+ **字体不打包**（全量中文字体 3~25MB 不现实）。本插件沿用同一策略，README 写清字体放置说明。
- 卡面设计基线（沿既有审美约定）：**淡彩萌系、白底为主、留白呼吸感，不过度花里胡哨**；幸运色做点缀色而非大色块。渲染样图先出、迭代确认后再进代码（沿「渲染预览、视觉迭代」流程）。
- **卡面信息层级（D9/D10，自上而下）**：①身份头——头像（圆角，当日缓存下载）+ 昵称 + **QQ号** + 日期；②吉凶大字（主题色随吉凶）；③**签文话语区**——卡面主体文字，2~3 句（吉凶点评 / 幸运物联动 / 祝语）；④六维星数 + 幸运指数；⑤宜忌；⑥幸运物/色/数字/方位；⑦落款。
- **底图合成（D11）**：尺寸对齐靠**透传**而非裁切——`comfyui_draw` 支持 `width/height`（签名已核实），直接传卡面画布尺寸（`card_width`×`card_height`，默认 1024×1536 竖版，可配），底图天生同尺寸；仅当个别工作流节点写死尺寸、覆盖不生效时才回退等比 cover 裁切。合成：Pillow 打开底图 → 叠半透明白/暗渐变遮罩保证文字对比度 → 绘制信息层 → 成品落盘。失败 → 幸运色渐变默认底图，静默降级。头像下载失败 → 占位头像兜底。

### 7.4 LLM 星语（F16）设计要点

- 开关默认**关**（D3 确认后冻结）。开启后仅对「当日本用户**首次**抽签」调用一次 LLM 扩写签文，结果写进 `payload` 缓存，重复查询不再调用——成本可控。
- Prompt 携带：吉凶、六维、幸运物、宜忌（脱敏后的事实清单）→ 要求生成 60 字内第二人称签文；失败/超时静默回退本地模板，不阻塞出卡。
- 用 `context.get_using_provider()`（用户当前启用的 provider），不指定具体模型，避免与用户环境耦合。

### 7.5 定时说明（为什么 F17 要自管循环）

- AstrBot 源码 `astrbot/core/cron/manager.py` 是**面板级**定时任务（basic job 跑内部 handler、agent job 唤醒主 agent），**没有**插件侧 `@filter.scheduled` 装饰器，插件指令无法被内置 cron 直接触发。
- 因此 F17 的每日推送由插件自管：`asyncio.create_task` 循环（计算距下次触发时间的 sleep → 推送 → 重算），`terminate` 中取消。时区、推送时间、推送群列表均走配置。

### 7.6 anima 绘图联动（F23/D6，已对照 anima 对接文档与源码核实）

> 依据：`astrbot-comfyui-anima/docs/cross-plugin-draw-guide.md`（对接契约）、`docs/prompt-language-guide.md`（提示词语言规范），及 anima `main.py` 源码实测。

**调用契约（anima 官方推荐的方式 A）**：

```python
manager = self.context.get_llm_tool_manager()      # astrbot/core/star/context.py:381（已核实）
tool = manager.get_func("comfyui_draw")            # astrbot/core/agent/tool.py:194（已核实）
handler = getattr(tool, "handler", None) or tool
result = await handler(event, prompt=<LLM 生成的提示词>, source="我会永远陪着你", workflow=<配置>, seed=<运势子种子>)
```

1. **source 必传约定值**：anima 以 `source == SOURCE_COMPANION_PLUGIN`（main.py:620，值为 `"我会永远陪着你"`）**精确比对**判定「调用方自管发图」——命中才返回 JSON `{"image_paths": [...], "note": ...}`（main.py:14811 附近），由我方取路径落库并发图；不命中时 anima 自己把图发进聊天、我方拿不到路径。对接文档第 3/5 节明确任何宿主插件均可传此值取路径。
2. **工作流可配**：`draw_workflow` 填 anima 里的真实工作流名（管理员先用 anima 的 `/绘图工作流` 指令查名，再填入本插件配置）；留空走 anima 默认工作流。禁止传 `text2img` 之类语义值（对接文档「禁止事项」）。
3. **提示词约束（D6）**：按 anima `prompt-language-guide.md`——动漫工作流（`is_anima=true`）**必须英文 Danbooru 标签**、真人工作流**首选中文自然语言**。本插件配置 `draw_prompt_lang`（en/zh）+ `draw_prompt_format`（tags/natural），默认 `en + tags`（萌系运势图走动漫工作流）；约束写进 LLM 生成模板，并要求「只输出提示词本身、单行」。
4. **LLM 生成提示词**：`draw_llm_prompt` 模板可配（内置默认模板注入吉凶/六维/幸运色/宜忌/签文等当日事实 + 语言与格式约束）；用 `context.get_using_provider().text_chat()` 调用，失败/超时/空输出 → 跳过绘图，绝不阻塞运势卡。
5. **时序（D11：先绘后卡）**：绘图是卡面底图 ⇒ 先出图再合卡：LLM 提示词 → `comfyui_draw`（透传 `seed`＝运势子种子、`width/height`＝卡面画布尺寸——参数签名已核实，底图天生与卡布同尺寸，**不需要裁切**）→ 取 `image_paths[0]` → Pillow 叠遮罩与信息层合成成品卡 → 落盘 `cards/<qq>/<date>.png` → 发送。种子由 `date|user_id|salt` 派生 ⇒ **底图一人一天一张，绝不跨用户重复**；换签卡换 seed 即换图。`draw_timeout` 默认 120s（anima 单张实测约 20-25s）；生成只发生在当日首次抽签。
6. **降级矩阵（D11）**：anima 未安装 / `get_func` 返回 None / ComfyUI 超时或报错 → 落库 status（`skipped_no_anima` / `timeout` / `error`），**静默回退幸运色默认底图**，运势卡照常发送、体验不断（`draw_fail_hint` 可选附加一句提示，默认空=静默）。
7. **频率天然受限**：ComfyUI 生成只发生在当日首次抽签 ⇒ 每人每天最多 1 次生成请求；之后的重复请求（跨群/私聊）全部直接回发盘上成品卡，零生成成本，不冲击 anima 队列。

### 7.7 关键实现约束

1. **时区**：默认 `Asia/Shanghai`（可配），`date` 以插件时区计算；跨零点边界由 date 字符串天然隔离。所有「今天」的判定必须走同一工具函数，禁止散落 `datetime.now()`。
2. **user_id 形状**：直接用 `event.get_sender_id()` 原值；如做跨平台统一再拼平台前缀（届时参考 stealer/companion 的处理，v1 先用原值，开放问题清单里不单独列）。
3. **种子展开**：从 SHA-256 摘要切片出各维度独立子种子，禁止复用全局 `random` 实例（进程重启后状态会漂移，破坏确定论）。
4. **测试**：`fortune.py` 全纯函数（seed 进、结果字典出），测试文件直接断言「同 seed 同结果」「日期变结果变」「权重分布合理」（抽样 10 万次卡方粗检）等，无需 astrbot 运行时。
5. **打包**：`build_zip.ps1` 显式 `$includeList` + 顶层 `.py` 与磁盘比对守卫（沿 box / user_gateway 模式，漏列直接报错终止）；词库 JSON 目录整体进包；`data/`、`tests/`、`dist/` 不进包。
6. **发布纪律**：按工作区 AGENTS.md——先升版本写 CHANGELOG 再打包、中文提交走文件法 `git commit -F`、`dist/` 只增不删。

---

## 8. 配置项草案（`_conf_schema.json`）

| 键 | 类型 | 默认 | 说明 |
| --- | --- | --- | --- |
| `timezone` | string | `Asia/Shanghai` | 「今天」的时区 |
| `salt` | string | 随机生成 | 种子盐值，改动即全员重掷 |
| `grade_weights` | dict | 见 §3.3 | 各吉凶档权重 |
| `output_mode` | enum | `图卡` | 图卡 / 纯文本 / 图卡+文本 |
| `card_theme` | enum | `auto` | auto / light / dark |
| `card_font_path` | string | 空 | 字体优先路径（空则走多级查找） |
| `fortune_signer` | string | `星语者` | 卡片落款人设名 |
| `llm_enabled` | bool | false | F16 开关 |
| `llm_prompt_persona` | string | 内置 | F16 人设 prompt |
| `daily_push_enabled` | bool | false | F17 开关 |
| `daily_push_time` | string | `08:00` | F17 推送时刻 |
| `disabled_groups` | list | 空 | 默认停用的群（配合 `/运势开关`） |
| `draw_enabled` | bool | false | F23 绘图联动总开关（需安装 astrbot-comfyui-anima） |
| `draw_workflow` | string | 空 | anima 工作流名（空 = anima 默认；用 anima `/绘图工作流` 查名后填） |
| `draw_prompt_lang` | enum | `en` | 绘图提示词语言（en=动漫标签 / zh=真人自然语言，D6） |
| `draw_prompt_format` | enum | `tags` | 提示词形式（tags=英文标签 / natural=自然语言） |
| `draw_llm_prompt` | text | 内置 | 生成绘图提示词的 LLM 模板（注入当日运势事实与语言/格式约束） |
| `draw_negative_prompt` | string | 空 | 附加负向提示词（透传 anima） |
| `draw_timeout` | int | 120 | 等待出图上限（秒） |
| `card_width` | int | 1024 | 卡面画布宽（同时透传给 anima 作为出图宽） |
| `card_height` | int | 1536 | 卡面画布高（同时透传给 anima 作为出图高） |
| `draw_fail_hint` | string | 空（静默） | 底图生成失败回退默认底图时附加的一句提示（D11，默认静默） |
| `economy_enabled` | bool | true | 道具经济（F22）总开关 |
| `item_prices` | dict | 见 §4 明细 | 各道具价格（reroll / amulet / streak_guard / candle） |
| `draw_reward_base` | int | 10 | 每日抽签基础星尘 |
| `item_hold_cap` | int | 3 | 单道具持有上限 |

---

## 9. 里程碑（版本号按 §2 起点，Z 递增规则沿 AGENTS.md 第三节）

> D4 已确认首发为**全家桶**：M0-M7 全部完成后以 **v1.0.0** 作为首次公开发布；
> 开发期按里程碑递增 v0.x 小版本（每个 M 一个可用版本，便于自测与回退）。

| 里程碑 | 内容 | 版本 |
| --- | --- | --- |
| M0 骨架 | 重写 helloworld 模板：metadata/display_name/README/目录结构/词库雏形 | v0.1.0 |
| M1 核心抽签 | fortune.py 种子机制 + 吉凶 + 六维 + 宜忌 + 签文，纯文本回复，落库（一日一签，D5） | v0.2.0 |
| M2 图卡 | card.py Pillow 渲染 + 幸运色换装 + 字体多级查找 + 渲染失败文本兜底 | v0.3.0 |
| M3 群玩法 | streak + `/运势榜` + `/运势PK` + `/运势开关` | v0.4.0 |
| M4 星座与彩蛋 | 星座绑定 + 生日/节日/愚人节彩蛋 + 暗色主题 | v0.5.0 |
| M5 增强 | F16 LLM 星语（可选）+ F17 每日推送 | v0.6.0 |
| M6 绘图联动 | F23 anima 底图（LLM 提示词 + comfyui_draw + 先绘后合卡 + 降级）+ draw_jobs 落库 | v0.7.0 |
| M7 道具经济 | F22 星尘 + 四道具 + 商店/背包/补签/发放 + items/ledger 落库 | v0.8.0 |
| M6+ 远期 | F18~F22 按反馈排期 | - |

发布前 Checklist 按 AGENTS.md 第九节执行（含 `python tests/xxx` 全绿、zip 结构 `tar -tf` 核对等）。

---

## 10. 风险与对策

| 风险 | 对策 |
| --- | --- |
| 「确定论」被预言（用户发现可预测） | salt 私密配置；seed 不暴露原文；签文池足够大（≥200 条模板）避免当日撞词 |
| Pillow 渲染在用户环境缺字体 | 多级查找 + 渲染失败自动降级纯文本（F1 兜底），绝不吞错不回 |
| 词库娱乐内容尺度 | 全部自写萌化词库，不搬运黄历/命理站点内容（版权+尺度双保险）；宜忌池避免真实医疗/投资建议式表述（「宜大额投资」这类不做） |
| 榜单引发攀比不适 | 榜单默认展示昵称+指数，不展示吉凶文字；`/运势开关` 可整群关闭 |
| 群成员量大的群 SELECT 压力 | `fortunes` 主键 (user_id, date)，榜单按 date 索引查询，量级可控；单群单日抽签数本身有限 |
| 热更新后词库/渲染不生效 | main.py 建 `importlib.reload` 热重载列表（按依赖序：lexicon → fortune → card → store → main 自身不 reload）；新增模块同步清单与打包 `$includeList` |
| anima 未安装 / 版本变更致联动失效 | `get_func` 判空 + 超时与异常全面兜底，绘图失败不影响运势卡；契约以 anima 对接文档为准，anima 升级后回归 |
| 经济通胀 / 囤积破坏循环 | 持有上限 + 无转账无兑换 + 价格集中可配；F24 统计上线后按真实收支数据再调数值 |
| 头像/昵称获取失败或平台字段不一致 | 昵称用 `event.get_sender_name()`（源码已核实）；头像 QQ 平台用 qlogo 标准地址兜底、下载失败用占位头像；具体字段实现时在 aiocqhttp 适配器确认 |

---

## 11. 开放问题

> 全部有结论：Q1-Q4 与 Q6 于 2026-09-27 拍板（见 §0 决策记录 D1-D4、D8）；Q5 结论：**参考图有用但非必须**——给一张能把「淡彩 / 白底 / 留白」的口味对齐到像素、显著减少首轮返工；不给则先渲染 2~3 版预览卡供挑选（本就是渲染预览、视觉迭代的工作流）。以下留档备查。

- **Q1 主指令**：`/运势`（建议）还是 `/星语`？别名怎么留？
- **Q2 吉凶体系**：日式「大吉→大凶」（建议，二次元群体辨识度高）？中式「上上签→下下签」？还是五星级？影响卡面主视觉与词库分池。
- **Q3 LLM 星语**：做不做？默认开还是关？（涉及用户 token 成本）
- **Q4 首发范围**：按 M0→M2（核心+图卡）先发首版，还是一口气到 M3（含群玩法）？
- **Q5 卡面画风**：是否给一张参考图/既有 model_panel 卡片的风格延用即可？
- **Q6 道具经济（F22）**：v1 不做，是否长期不做？若做，与 user_gateway 额度体系是否合并为一个「积分」口径？（影响两插件数据模型，需早决策）

---

## 12. 参考

- AstrBot 插件开发文档：https://docs.astrbot.app/dev/star/plugin-new.html
- 源码依据均标注于 §7.2，以 `_Refs/AstrBot`（4.28.1）为准
- 工程约定：本工作区 `AGENTS.md`（版本/打包/提交/配置同步/热重载等）
- 实现经验复用：model_panel `card_render.py`（Pillow 卡片与字体查找）、`store.py`（plugin_data 落库）、box（$includeList 守卫打包）、user_gateway（PRD 流程与 WebUI bridge 约束，F21 时适用）
- anima 绘图联动契约：`astrbot-comfyui-anima/docs/cross-plugin-draw-guide.md`（调用方式与 source 约定）、`docs/prompt-language-guide.md`（提示词语言/格式规范）
