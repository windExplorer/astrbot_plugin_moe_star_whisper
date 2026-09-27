# 更新日志

> 倒序（最新在上）。版本唯一来源为 `metadata.yaml` 的 `version`，条目号与其严格一致。

## v0.2.1 (2026-09-27)

M1 代码审查修复：

- **词库深度校验**：原实现只查顶层键存在——池被清空/档位缺失要到用户抽签时才以 ZeroDivisionError/KeyError 炸掉。抽出 `validate_lexicon()`（池非空、宜忌池 ≥2、点评/祝语覆盖六档、lucky_colors 含 name/hex、phases 含 name/text），加载期即拦截；新增 `tests/test_lexicon.py` 8 组负例。
- **榜单索引**：`list_day` 按 date 查询但主键 (user_id, date) 帮不上忙，补 `idx_fortunes_date` 索引（M3 榜单/PK 的前置准备）。

## v0.2.0 (2026-09-27)

M1 核心抽签：从骨架到可用的纯文本出签。

- **确定性种子**：`seed = SHA-256(日期|用户|盐|nonce)` 派生全部维度（hashlib，无全局随机），同一天同一人跨时刻/跨群结果恒定；`nonce` 供换签卡（M7）重掷。
- **一日一签（D5）**：`(user_id, date)` 主键保证；当日重复请求直接回发已存记录（卡文件优先，其次文本），不重算不重绘。
- **签面内容**：六档吉凶（权重可配）、六维星数（按档位区间取值）、幸运指数（六维合成）、幸运物/色/数字/方位、宜忌各两条（池内不重复）、签文 = 点评 + 幸运物联动句 + 祝语。
- **连续抽签 streak**：首日 1 → 同日幂等 → 次日 +1 → 断签回 1，随签落库并在文案展示（≥2 天）。
- **身份快照（D10）**：昵称/头像/群号随签入库；QQ 平台头像用 qlogo 标准地址。
- **健壮性**：时区非法/无 tzdata 环境两级回退（Asia/Shanghai → 固定 UTC+8）；卡渲染缺失/失败回退纯文本；词库缺键在加载期即报错。
- **测试**：`tests/test_fortune.py`（确定性/分布/词库来源/道具钩子/日期工具）与 `tests/test_store.py`（一日一签/streak 序列/档案 upsert），`uv run --no-project python tests/xxx.py` 直接运行，退出码即结论。

## v0.1.0 (2026-09-27)

- 项目骨架：确定插件定位「萌萌星语 · 每日运势签」，落盘目录规划（`fortune.py` 核心 / `lexicon.py` 词库 / `store.py` 存储 / `card.py` 图卡）。
- 内置词库数据雏形 `data/lexicon/fortune_lexicon.json`：吉凶点评与祝语（六档各池）、幸运物 / 幸运色（含 hex）/ 幸运方位、萌化宜忌、八相月相。
- 打包脚本 `build_zip.ps1`：显式 includeList + 顶层 `.py` 守卫（漏列直接报错），.NET `System.IO.Compression` 手工写条目、正斜杠、套一层插件目录。
- 本版本仅骨架，无功能实现，未打包。
