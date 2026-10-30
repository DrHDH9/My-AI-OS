# -*- coding: utf-8 -*-
"""在指定记忆库上测量各命令耗时与内存，用于档位 4（8000 条）压测。

只读不改：rebuild 是唯一会写索引的命令，其余都是查询。
"""
import os
import subprocess
import sys
import time
from pathlib import Path

LIB = Path(sys.argv[1]).resolve()
PY = sys.executable
ENV = dict(os.environ, MYAIOS_ROOT=str(LIB), PYTHONIOENCODING="utf-8")

CMDS = [
    ("rebuild", ["rebuild"]),
    ("check", ["check"]),
    ("brief", ["brief", "--no-archive"]),
    ("search", ["search", "种子7000"]),
    ("search-无命中", ["search", "不存在的关键词xyz"]),
    ("why", ["why", "2026-10-17-经验-主题7996.md"]),
    ("tier --dry-run", ["tier", "--dry-run"]),
    ("tier", ["tier"]),
]

print(f"库：{LIB}")
print(f"笔记数：{len(list((LIB / 'notes').glob('*.md')))}")
print()
print(f"{'命令':<16}{'退出码':<8}{'耗时(s)':<10}输出特征")
print("-" * 66)
for tag, args in CMDS:
    t0 = time.time()
    p = subprocess.run([PY, str(LIB / "mem.py")] + args, env=ENV,
                       capture_output=True, text=True, encoding="utf-8",
                       errors="replace", timeout=1800)
    dt = time.time() - t0
    out = (p.stdout or "") + (p.stderr or "")
    # 只留一行特征，别把整篇简报打出来
    tail = out.strip().splitlines()[-1][:40] if out.strip() else "(无输出)"
    flag = "" if p.returncode == 0 else "  <<< 非零退出"
    print(f"{tag:<16}{p.returncode:<8}{dt:<10.2f}{tail}{flag}")
