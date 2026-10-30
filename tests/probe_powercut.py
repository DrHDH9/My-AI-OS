# -*- coding: utf-8 -*-
"""断电 / 磁盘满 两种「写不进去」的验证。

断电没法真拔电源，改成在写入的关键点上强行抛错，等价于进程在那一刻被杀：
  - 写完临时文件、还没来得及替换 → 原文件必须一字不动
  - 写到一半（临时文件只写了一半）→ 原文件同样必须完好
磁盘满用 ENOSPC(errno 28) 模拟，看是否给人话而不是 traceback。
"""
import errno
import importlib.util
import os
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
PY = sys.executable
n_pass = n_fail = 0


def ck(name, cond, detail=""):
    global n_pass, n_fail
    if cond:
        n_pass += 1
        print(f"[PASS] {name}")
    else:
        n_fail += 1
        print(f"[FAIL] {name}\n       {detail}")


def load_mem():
    spec = importlib.util.spec_from_file_location("mem_probe", ROOT / "mem.py")
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


mem = load_mem()
SANDBOX = HERE / ".tmp" / "powercut"
SANDBOX.mkdir(parents=True, exist_ok=True)

print("=" * 60)
print("断电：写到一半被杀，原文件会不会被截断")
print("=" * 60)

target = SANDBOX / "note.md"
target.write_text("原始内容：这一段必须完好", encoding="utf-8")

# 情形 1：临时文件已写完，替换前被杀
real_replace = os.replace


def boom(src, dst):
    raise OSError(errno.EIO, "模拟断电：替换前进程被杀")


os.replace = boom
try:
    mem.write_text_safe(target, "新内容：这段不该生效")
    replaced_blocked = False
except SystemExit:
    replaced_blocked = True
finally:
    os.replace = real_replace

ck("替换前被杀 → 目标文件保持原样",
   target.read_text(encoding="utf-8") == "原始内容：这一段必须完好",
   target.read_text(encoding="utf-8")[:60])
ck("替换失败时不留下 .writing 残骸",
   not list(SANDBOX.glob("*.writing")),
   str(list(SANDBOX.glob("*.writing"))))

# 情形 2：断电卡在写临时文件的中途 → 留下半截 .writing + 原文件
#
# 这是真实断电最可能的残留形态：临时文件写了一半，进程没了。
# 真正要验的不是「原文件」（它天然没被碰），而是这坨残骸会不会
# 把整库带崩 —— 比如被当成笔记收进去、或让 check 报错。
target.write_text("原始内容：这一段必须完好", encoding="utf-8")
half = SANDBOX / (target.name + ".writing")
half.write_text("---\ntopic: 半截\n", encoding="utf-8")   # 故意只写一半 frontmatter

ck("断电残留不覆盖原文件",
   target.read_text(encoding="utf-8") == "原始内容：这一段必须完好",
   target.read_text(encoding="utf-8")[:60])

# 情形 3：正常写一次，确认原子替换后没残留
half.unlink()
mem.write_text_safe(target, "正常的新内容")
ck("正常写入生效", target.read_text(encoding="utf-8") == "正常的新内容",
   target.read_text(encoding="utf-8")[:40])
ck("正常写入后无 .writing 残留",
   not list(SANDBOX.glob("*.writing")))

# 情形 4：带断电残骸的库，仍然可用
libpc = SANDBOX / "lib_pc"
(libpc / "notes").mkdir(parents=True, exist_ok=True)
for f in ("mem.py", "config.json"):
    (libpc / f).write_bytes((ROOT / f).read_bytes())
good = libpc / "notes" / "2026-10-20-决策-正常笔记.md"
good.write_text(
    "---\ntopic: 正常笔记\ntype: 决策\ndate: 2026-10-20\nrecorded: 2026-10-20T10:00:00+08:00\n"
    "scope: default\nsource: test\nvalid_from: 2026-10-20\nvalid_to: -\n"
    "invalid_reason: -\nsuperseded_by: -\nsupersedes: -\n---\n\n# 正常笔记\n\n## 结论\n这是一条完好的笔记。\n",
    encoding="utf-8")
# 断电残骸：半截 frontmatter
(libpc / "notes" / "2026-10-21-决策-半截.md.writing").write_text(
    "---\ntopic: 半截\n", encoding="utf-8")

env2 = dict(os.environ, MYAIOS_ROOT=str(libpc), PYTHONIOENCODING="utf-8")


def run_pc(*args):
    q = subprocess.run([PY, str(libpc / "mem.py")] + list(args), env=env2,
                       capture_output=True, text=True, encoding="utf-8",
                       errors="replace", timeout=120)
    return q.returncode, (q.stdout or "") + (q.stderr or "")


rc, out = run_pc("check")
ck("有断电残骸时 check 不崩", rc == 0 and "Traceback" not in out, out[:400])
ck("残骸没被当成一条笔记收进去（活跃=1）",
   "活跃 1 ·" in out, out[:600])

rc, out = run_pc("brief", "--no-archive")
ck("有断电残骸时 brief 不崩", rc == 0 and "Traceback" not in out, out[:400])
ck("brief 里活跃记忆是 1 条", "活跃记忆 1 条" in out, out[-400:])

rc, out = run_pc("search", "完好的笔记")
ck("残骸不影响检索", rc == 0 and "正常笔记" in out, out[:400])

print()
print("=" * 60)
print("磁盘满：ENOSPC 是否给人话")
print("=" * 60)

lib = SANDBOX / "lib"
lib.mkdir(exist_ok=True)
(lib / "notes").mkdir(exist_ok=True)
(lib / "cold").mkdir(exist_ok=True)
(lib / "sum").mkdir(exist_ok=True)
for f in ("mem.py", "config.json"):
    (lib / f).write_bytes((ROOT / f).read_bytes())

# 用一个会抛 ENOSPC 的 sitecustomize 注入，模拟磁盘写满
inject = lib / "_no_space.py"
inject.write_text(
    "import builtins, errno, pathlib\n"
    "_open = builtins.open\n"
    "def open_fail(path, *a, **kw):\n"
    "    if str(path).endswith('.md') or str(path).endswith('.writing'):\n"
    "        raise OSError(errno.ENOSPC, 'No space left on device')\n"
    "    return _open(path, *a, **kw)\n"
    "builtins.open = open_fail\n"
    "_wt = pathlib.Path.write_text\n"
    "def wt(self, data, *a, **kw):\n"
    "    if str(self).endswith('.md') or str(self).endswith('.writing'):\n"
    "        raise OSError(errno.ENOSPC, 'No space left on device')\n"
    "    return _wt(self, data, *a, **kw)\n"
    "pathlib.Path.write_text = wt\n",
    encoding="utf-8",
)

env = dict(os.environ, MYAIOS_ROOT=str(lib), PYTHONIOENCODING="utf-8",
           PYTHONPATH=str(lib))
p = subprocess.run(
    [PY, "-c", "import _no_space, runpy, sys; "
     f"sys.argv=['mem.py','add','--type','事实','--topic','磁盘满','--title','t','--body','b']; "
     f"runpy.run_path(r'{lib / 'mem.py'}', run_name='__main__')"],
    env=env, capture_output=True, text=True, encoding="utf-8", errors="replace")
out = (p.stdout or "") + (p.stderr or "")
ck("磁盘满时退出码非 0", p.returncode != 0, f"rc={p.returncode} {out[:200]}")
ck("磁盘满时提示是「写不进去」而非 traceback",
   "写不进去" in out and "Traceback" not in out, out[:400])
ck("磁盘满时提示里点出「磁盘满了」", "磁盘满" in out, out[:400])

print()
print("=" * 60)
print(f"共 {n_pass + n_fail} 项，通过 {n_pass}，失败 {n_fail}")
print("=" * 60)

# 跑完自己收拾；删不掉不算失败。只删自己那一个子目录，
# 别碰 .tmp 下别的测试库（压测库就放在那儿）。
import shutil
shutil.rmtree(SANDBOX, ignore_errors=True)
try:
    (HERE / ".tmp").rmdir()   # 空了才删得掉，里面还有别的测试库就不动
except OSError:
    pass
sys.exit(1 if n_fail else 0)
