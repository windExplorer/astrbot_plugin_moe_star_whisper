# 萌萌星语（astrbot_plugin_moe_star_whisper）

AstrBot 今日运势插件：每个用户每天一支专属「星语签」——AI 可选底图 + 萌系图卡 + 签文话语 + 萌化宜忌 + 星座与道具经济 + 运势日历。

## 特性

- **每日确定论**：运势由 `SHA-256(日期|用户|盐|nonce)` 确定性推导，一天一签、跨群/私聊全局一致；当天重复请求直接回发已存卡片，零生成成本。
- **签面内容**：吉凶六档（大吉→大凶，权重可配）、六维星数 + 幸运指数、幸运物/色/数字/方位、宜忌各两条、签文话语（点评 + 幸运物联动 + 祝语）。
- **萌系图卡**：Pillow 本地渲染，幸运色驱动卡面配色（每天不同观感），暗色主题可配；字体不打包、多级查找。
- **星尘上卡**：占卜结果图标注「今日星尘 +N ｜ 累计 M」；星尘钱包/道具商店/星语榜/PK/购买与使用结果/生日绑定/星座查询均以同风格提示卡展示（`仅文字` 模式回到文本）。
- **运势日历**：`/星语日历 [月份]` 渲染当月真实月历——每日吉凶（档位色）+ 幸运指数，未占卜画小点、今日金框，附本月占卜统计。
- **AI 星象底图**（可选）：安装 [astrbot-comfyui-anima](https://github.com/windExplorer/astrbot-comfyui-anima) 后，LLM 依当日运势生成英文标签提示词，anima 出图作为卡面底图；seed/尺寸透传，失败自动回退渐变底图。
- **LLM 星语**（可选，默认关）：当日首次抽签由 LLM 按运势事实清单改写签文，失败回退本地词库。
- **星座与彩蛋**：生日绑定（只存月日）、星座角标、生日必大吉+金环卡面、愚人节整活、节日词库池、周五摸鱼加成、连签徽章。
- **道具经济**：星尘积分（每签必得、越倒霉补偿越多）+ 换签卡/厄运护身符/幸运香烛/连签保护卡四道具；全流水落库，不可转账不可兑换。
- **群玩法**：`/星语榜`（日/周）、`/星语PK`、群开关、连签徽章。
- **数据全量落库**：SQLite 于 `data/plugin_data/astrbot_plugin_moe_star_whisper/star_whisper.db`（抽签/档案/绘图任务/星尘流水），为统计功能预留口径。
- **WebUI 控制台**（v1.9.0）：Vue3 + Naive UI + ECharts 面板（插件 Page `pages/console/`）——总览指标与趋势、抽签记录检索、六维/幸运物/星座统计、单用户档案与运势日历、参数配置分区读写、调试工具（重抽/重绘/重置）；另有单文件旧调试页 `pages/debug/` 可回退。

## 指令

| 指令 | 说明 |
| --- | --- |
| `/星语`（别名 `/运势` `/今日运势` `/占卜`） | 抽当日专属星语签 |
| `/星语日历 [月份]` | 当月运势日历（吉凶 + 分数，留空看本月） |
| `/星语帮助` | 查看全部指令（帮助图） |
| `/星语榜 [日\|周]` | 群内幸运指数排行 |
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

`_conf_schema.json` 全量键位（AstrBot 配置页自动生成）：时区、盐值、吉凶权重、输出方式、卡面主题/字体/尺寸、LLM 星语、每日推送（时间/开关）、anima 联动（工作流/提示词语言与形式/超时）、道具价格等。

## 字体说明（图卡）

不打包字体，按以下顺序查找：配置 `card_font_path` → `data/plugin_data/astrbot_plugin_moe_star_whisper/fonts/` → `data/fonts/` → 系统字体（Windows 微软雅黑 / Linux Noto CJK）。找不到可用字体时自动回退纯文本出签。

## 依赖

- AstrBot 4.28+
- `pillow`（图卡）
- `tzdata`（时区；缺省环境自动回退 UTC+8）
- anima 底图联动需另装 astrbot-comfyui-anima 并开启 `draw_enabled`

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
