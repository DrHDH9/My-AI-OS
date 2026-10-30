# -*- coding: utf-8 -*-
"""空值写法归一化：判定矩阵。

关键不是"能认 NULL"，而是"别把真失效也当活的"。
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
import mem

FIELDS = ("scope", "source", "valid_from", "valid_to",
          "invalid_reason", "superseded_by", "supersedes")

CASES = [
    # (valid_to, invalid_reason, 期望 live, 说明)
    ("-", "-", True, "本库规范写法"),
    ("NULL", "NULL", True, "YAML 大写 NULL（曾静默吞记忆）"),
    ("null", "null", True, "YAML 小写 null"),
    ("None", "None", True, "Python 风格 None"),
    ("none", "none", True, "小写 none"),
    ("~", "~", True, "YAML 波浪号"),
    ("", "", True, "空值"),
    ("无", "无", True, "中文「无」"),
    ("2026-10-01", "superseded", False, "真失效不能被放过"),
    ("2026-10-01", "wrong", False, "记错的"),
    ("2026-10-01", "retracted", False, "撤回的"),
    ("2026-10-01", "expired", False, "过期"),
]

ok = fail = 0
for vto, reason, want_live, desc in CASES:
    fm = {f: "-" for f in FIELDS}
    fm["valid_to"] = vto
    fm["invalid_reason"] = reason
    fm = mem.fm_defaults(dict(fm))
    got = mem.is_live(fm)
    norm = "-" if want_live else vto
    status = "PASS" if got == want_live else "FAIL"
    if got == want_live:
        ok += 1
    else:
        fail += 1
    print(f"[{status}] live={got!s:<5} 期望={want_live!s:<5} {desc}  "
          f"(valid_to {vto!r} → {fm['valid_to']!r}, reason {reason!r} → {fm['invalid_reason']!r})")

# 字段确实是空值的都得归一成 "-"，不是空值的不能被改
for f in FIELDS:
    fm = mem.fm_defaults({f: "NULL"})
    want = "default" if f == "scope" else "-"   # scope 空了要落回 default
    assert fm[f] == want, f"{f} 未归一：{fm[f]!r}"
fm = mem.fm_defaults({"topic": "NULL", "type": "NULL"})
assert fm["topic"] == "NULL", "topic 不该被当成空值归一"

print(f"\n{ok} 通过 / {fail} 失败")
sys.exit(1 if fail else 0)
