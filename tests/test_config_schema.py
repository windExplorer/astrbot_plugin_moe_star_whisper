# -*- coding: utf-8 -*-
"""_conf_schema.json 守卫：类型必须是 AstrBotConfig._parse_schema 认识的，
object 类型必须带 items 子 schema（真机加载即崩的坑，本地拦截）。
类型清单核对自 _Refs/AstrBot astrbot/core/config/default.py 的 DEFAULT_VALUE_MAP。
退出码即结论。"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

FAILED = []


def check(cond, msg):
    if not cond:
        FAILED.append(msg)
        print(f"FAIL: {msg}")


def main() -> int:
    # 与 AstrBot 4.28.1 DEFAULT_VALUE_MAP 对齐
    KNOWN_TYPES = {"int", "float", "bool", "string", "text",
                   "list", "file", "object", "template_list", "dict"}

    schema_path = Path(__file__).resolve().parents[1] / "_conf_schema.json"
    schema = json.loads(schema_path.read_text(encoding="utf-8"))

    def walk(node: dict, path: str) -> None:
        for key, item in node.items():
            where = f"{path}{key}"
            check(isinstance(item, dict) and "type" in item,
                  f"{where}: 缺少 type 声明")
            if not isinstance(item, dict):
                continue
            t = item.get("type")
            check(t in KNOWN_TYPES,
                  f"{where}: 非法类型 {t!r}（合法：{sorted(KNOWN_TYPES)}）")
            # label 约定：description 是表单字段名（短），长说明放 hint
            desc = item.get("description")
            check(isinstance(desc, str) and 0 < len(desc) <= 40,
                  f"{where}: description 应为简短字段名（≤40 字），长说明请放 hint")
            # options 枚举：labels 必须是与 options 等长的数组
            # （labels 为字符串时是 i18n 键，不按逗号拆分——真机显示会退回英文值）
            if t == "string" and item.get("options"):
                labels = item.get("labels")
                check(isinstance(labels, list) and len(labels) == len(item["options"]),
                      f"{where}: options 的 labels 必须是等长数组（字符串是 i18n 键，不会按逗号拆分）")
            if t == "object":
                sub = item.get("items")
                check(isinstance(sub, dict) and bool(sub),
                      f"{where}: object 类型必须带非空 items 子 schema（否则真机 KeyError: items）")
                if isinstance(sub, dict):
                    walk(sub, where + ".")
            if t == "list":
                check("items" in item, f"{where}: list 类型建议带 items 元素模板")

    walk(schema, "")

    if FAILED:
        print(f"\n{len(FAILED)} 项失败")
        return 1
    print("\n_conf_schema.json 全部通过")
    return 0


if __name__ == "__main__":
    sys.exit(main())
