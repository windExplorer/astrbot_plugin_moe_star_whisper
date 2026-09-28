# 萌萌星语（astrbot_plugin_moe_star_whisper）

AstrBot 今日运势插件：每个用户每天一支专属「星语签」——AI 可选底图 + 萌系图卡 + 签文话语 + 萌化宜忌 + 星座与道具经济 + 运势日历。

## 特性

- **每日确定论**：运势由 `SHA-256(日期|用户|盐|nonce)` 确定性推导，一天一签、跨群/私聊全局一致；当天重复请求直接回发已存卡片，零生成成本。
- **签面内容**：吉凶六档（大吉→大凶，权重可配）、六维星数 + 幸运指数、幸运物/色/数字/方位、宜忌各两条、签文话语（点评 + 幸运物联动 + 祝语）。
- **萌系图卡**：Pillow 本地渲染，幸运色驱动卡面配色（每天不同观感），暗色主题可配；字体不打包、多级查找。
- **星尘上卡**：占卜结果图标注「今日星尘 +N ｜ 累计 M」；星尘钱包/道具商店/星语榜/PK/购买与使用结果/生日绑定/星座查询均以同风格提示卡展示（`仅文字` 模式回到文本）。
- **运势日历**：`/星语日历 [月份]` 渲染当月真实月历——每日吉凶（档位色）+ 幸运指数，未占卜画小点、今日金框，附本月占卜统计。
- **AI 星象底图**（可选）：安装[萌绘](https://github.com/windExplorer/astrbot-comfyui-anima)（`astrbot-comfyui-anima`）后，LLM 依当日运势生成英文标签提示词，萌绘出图作为卡面底图；seed/尺寸透传，失败自动回退渐变底图。
- **LLM 星语**（可选，默认关）：当日首次抽签由 LLM 按运势事实清单改写签文，失败回退本地词库。
- **星座与彩蛋**：生日绑定（只存月日）、星座角标、生日必大吉+金环卡面、愚人节整活、节日词库池、周五摸鱼加成、连签徽章。
- **道具经济**：星尘积分（每签必得、越倒霉补偿越多）+ 换签卡/厄运护身符/幸运香烛/连签保护卡四道具；全流水落库，不可转账不可兑换。
- **群玩法**：`/星语榜`（日/周，按**本群成员**统计——人在本群就上榜，哪怕今天是在别的群抽的签；取不到成员列表时回落「本群抽签」口径并在标题标明）、`/星语PK`、群开关、连签徽章。
- **数据全量落库**：SQLite 于 `data/plugin_data/astrbot_plugin_moe_star_whisper/star_whisper.db`（抽签/档案/绘图任务/星尘流水），为统计功能预留口径。
- **WebUI 控制台**（v1.9.0）：Vue3 + Naive UI + ECharts 面板（插件 Page `pages/console/`）——总览指标与趋势、抽签记录检索、**抽过签的用户列表（头像/QQ/昵称，点开看单用户档案与运势日历）**、六维/幸运物/星座统计、**群聊使用分布（占比 + 群活跃榜）**、参数配置分区读写、调试工具（重抽/重绘/重置）；另有单文件旧调试页 `pages/debug/` 可回退。
  > 群聊口径：每条记录 = 用户**当天第一次抽签所在的那个群**（一日一签 + 换群不再写新行），所以一人一天只计入一个群，不会重复计算；私聊单独统计。
  > 群名会随抽签一起入库（优先取事件自带群名，兜底调平台 API），历史记录没有群名时用「该群最近一次记录到的群名」回填，仍拿不到才显示群号。

## 指令

| 指令 | 说明 |
| --- | --- |
| `/星语`（别名 `/运势` `/今日运势` `/占卜`） | 抽当日专属星语签 |
| `/星语日历 [月份]` | 当月运势日历（吉凶 + 分数，留空看本月） |
| `/星语帮助` | 查看全部指令（帮助图） |
| `/星语榜 [日\|周]` | 群成员幸运指数排行（人在本群即可上榜，含今天在别群抽签的成员） |
| `/星语PK @某人` | 当日幸运指数对决 |
| `/星语绑定 <MM-DD>` | 绑定生日（解锁星座与生日彩蛋） |
| `/星座 [@某人]` | 查看星座与今日吉凶（不泄露生日） |
| `/星尘` | 星尘余额与背包 |
| `/星语商店` | 道具与价格 |
| `/星语购买 <名称> [数量]` | 购买道具 |
| `/星语使用 <名称>` | 使用换签卡/护身符/香烛 |
| `/星语补签` | 断签 3 天内消耗连签保护卡补回昨天 |
| `/星语开关 on\|off` | 群级启停（仅 AstrBot 管理员） |
| `/星语发放 @用户 <±n>` | 手动调整星尘（仅 AstrBot 管理员） |
| WebUI 控制台 | 仅管理员（插件 Page `pages/console/`）：总览 / 抽签记录 / 数据统计 / 用户查询 / 参数配置 / 调试工具 |
| WebUI 调试页（旧版） | 仅管理员（`pages/debug/`）：按 QQ 号查看状态 / 重抽 / 重绘 / 重置 |

> v1.8.4 起主指令统一「星语」前缀；旧的「运势」系指令名（`/运势` `/运势商店` `/运势PK` 等）全部保留为别名，老习惯不受影响。`/运势背包` 仍指向 `/星尘`。

## 配置

`_conf_schema.json` 全量键位（AstrBot 配置页自动生成）：时区、盐值、吉凶权重、输出方式、卡面主题/字体/尺寸、LLM 星语、每日推送（时间/开关）、萌绘联动（工作流/提示词语言与形式/超时）、道具价格等。

## 字体说明（图卡）

不打包字体，按以下顺序查找：配置 `card_font_path` → `data/plugin_data/astrbot_plugin_moe_star_whisper/fonts/` → `data/fonts/` → 系统字体（Windows 微软雅黑 / Linux Noto CJK）。支持 `ttf / otf / ttc / woff2`（woff2 需 Pillow 所带 FreeType 支持 brotli，读不了的候选会被自动跳过）。找不到可用字体时自动回退纯文本出签。

**字体风格**（配置 `card_font_style`）：

| 取值 | 效果 | 字体来源 |
| --- | --- | --- |
| `跟随默认` | 正文黑体 + 展示文字（吉凶/牌名/大数字）楷体 | 系统字体（现有观感） |
| `圆体` | 全卡统一圆体（标题/正文/名次/分数） | 在下方候选目录里按文件名挑 `*rounded*` 字体 |

字体来源只认两个位置（**不依赖任何其它插件**）：

1. **AstrBot 的公共字体目录 `data/fonts/`**（推荐——放这里所有插件都能用）；
2. 本插件数据目录的 `data/plugin_data/astrbot_plugin_moe_star_whisper/fonts/`。

选「圆体」时若这些目录里没有圆体（或该格式本机读不了），会**自动回落**默认字体并记一条日志，不会导致出卡失败。圆体推荐 [Resource Han Rounded](https://github.com/CyanoHao/Resource-Han-Rounded)（SIL OFL 1.1，文件名形如 `ResourceHanRoundedCN-Medium.woff2`）。

**两个配置的关系**：`card_font_path`（卡面字体）优先——填了就以它为准，留空时才看 `card_font_style`（卡面字体风格）。所以不用两个都配：常规需求只配后者（「圆体」）即可。

`card_font_path` 支持三种写法，写法 ① ② 都会在「插件 `fonts/` → AstrBot `data/fonts/`」里找：

| 写法 | 例子 |
| --- | --- |
| 字体名（最省事，模糊匹配，忽略大小写/空格/连字符） | `Resource Han Rounded`、`resourcehanrounded` |
| 文件名（忽略大小写） | `ResourceHanRoundedCN-Medium.woff2` |
| 文件路径（绝对路径最稳，相对路径按 AstrBot 进程工作目录解析） | `/AstrBot/data/fonts/ResourceHanRoundedCN-Medium.woff2` |

支持 `ttf` / `otf` / `ttc` / `woff2`。填了却解析不到时会**在日志里给出具体原因**（文件不存在 / 有匹配但本机读不了 / 候选目录里没有这个名字），然后回落到「卡面字体风格」自动选择。想用名字不含 `rounded` 的字体（例如 LXGW WenKai 霞鹜文楷），就填在这一项里。

## 依赖

- AstrBot 4.28+
- `pillow`（图卡）
- `tzdata`（时区；缺省环境自动回退 UTC+8）
- 萌绘（`astrbot-comfyui-anima`）底图联动需另装该插件并开启 `draw_enabled`

## 开发

```powershell
# 运行测试（核心模块无 astrbot 运行时依赖，直接跑；退出码即结论）
uv run --no-project python tests/test_lexicon.py
uv run --no-project python tests/test_fortune.py
uv run --no-project python tests/test_store.py
uv run --no-project --with pillow python tests/test_card.py
uv run --no-project python tests/test_main_structure.py

# 构建 WebUI 控制台（Vue3 + Naive UI + ECharts，产物 pages/console/；需 Node.js）
# build_zip.ps1 打包前会自动调用它，只有单独调前端时才需要手动跑
powershell -NoProfile -ExecutionPolicy Bypass -File .\build_webui.ps1

# 打包（产物在 dist/，同名版本已存在会拒绝打包）
powershell -NoProfile -ExecutionPolicy Bypass -File .\build_zip.ps1
```

设计文档见 `docs/PRD.md`（含全部决策记录 D1-D11 与 API 依据）。
