# 更新日志

> 倒序（最新在上）。版本唯一来源为 `metadata.yaml` 的 `version`，条目号与其严格一致。

## v0.1.0 (2026-09-27)

- 项目骨架：确定插件定位「萌萌星语 · 每日运势签」，落盘目录规划（`fortune.py` 核心 / `lexicon.py` 词库 / `store.py` 存储 / `card.py` 图卡）。
- 内置词库数据雏形 `data/lexicon/fortune_lexicon.json`：吉凶点评与祝语（六档各池）、幸运物 / 幸运色（含 hex）/ 幸运方位、萌化宜忌、八相月相。
- 打包脚本 `build_zip.ps1`：显式 includeList + 顶层 `.py` 守卫（漏列直接报错），.NET `System.IO.Compression` 手工写条目、正斜杠、套一层插件目录。
- 本版本仅骨架，无功能实现，未打包。
