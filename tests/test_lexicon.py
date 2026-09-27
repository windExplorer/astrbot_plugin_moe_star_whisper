# -*- coding: utf-8 -*-
"""lexicon.validate_lexicon 负例测试：坏词库必须在加载期报错。退出码即结论。"""
import copy
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import lexicon  # noqa: E402

FAILED = []


def check(cond, msg):
    if not cond:
        FAILED.append(msg)
        print(f"FAIL: {msg}")


def main() -> int:
    base = lexicon.load_lexicon()  # 内置词库必须通过深度校验
    lexicon.validate_lexicon(base)

    def broken(mutate):
        data = copy.deepcopy(base)
        mutate(data)
        return data

    cases = [
        ("缺字段", lambda d: d.pop("yi")),
        ("宜池只剩一条", lambda d: d.__setitem__("yi", d["yi"][:1])),
        ("忌池被清空", lambda d: d.__setitem__("ji", [])),
        ("点评缺大凶档", lambda d: d["comments"].pop("大凶")),
        ("祝语档位为空", lambda d: d["wishes"].__setitem__("吉", [])),
        ("幸运色缺 hex", lambda d: d["lucky_colors"][0].pop("hex")),
        ("grades 为空", lambda d: d.__setitem__("grades", [])),
        ("月相缺 text", lambda d: d["phases"][0].pop("text")),
        ("缺 pk 池", lambda d: d.pop("pk")),
        ("pk.tie 为空", lambda d: d["pk"].__setitem__("tie", [])),
    ]
    for name, mutate in cases:
        try:
            lexicon.validate_lexicon(broken(mutate))
            check(False, f"坏词库未被拦截: {name}")
        except ValueError:
            pass

    if FAILED:
        print(f"\n{len(FAILED)} 项失败")
        return 1
    print("\nlexicon.py 全部通过")
    return 0


if __name__ == "__main__":
    sys.exit(main())
