#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
archive.py —— 把聊天原文归档进 F:\\My-AI-OS\\.raw\\

设计原则（照 Aukino 的 --archive 四条）：
  1. 不筛寒暄，一句都不删
  2. 长消息不砍
  3. 重复导入幂等（源没变就跳过）
  4. 不受保留窗影响（.raw 不参与 tier 淘汰，也不进 brief）

只剥机器注入的上下文（system-reminder、工具调用、推理过程），
剥掉的是"系统塞给 AI 的东西"，不是"人和 AI 说的话"。

用法：
  python archive.py                 归档全部
  python archive.py --only wb       只归档 WorkBuddy
  python archive.py --only dsh      只归档 DSH
  python archive.py --force         源没变也重导
  python archive.py --out r.txt     报告写文件（绕开控制台编码）
"""

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent
RAW = ROOT / ".raw"
CFG = ROOT / "config.json"

# ── 清洗 ─────────────────────────────────────────────────────────────

RE_SYSREM = re.compile(r"<system-reminder\b[^>]*>.*?</system-reminder>", re.S)
RE_USERQ = re.compile(r"</?user_query[^>]*>", re.I)
RE_TAG = re.compile(r"</?(?:user_info|current_time|craft_mode|identity_context)\b[^>]*>", re.I)


def clean_user(text):
    """剥掉机器注入的上下文，留下人真正说的话。"""
    if not text:
        return ""
    t = RE_SYSREM.sub("", text)
    t = RE_USERQ.sub("", t)
    t = RE_TAG.sub("", t)
    t = re.sub(r"\n{3,}", "\n\n", t)
    return t.strip()


def clean_assistant(text):
    return (text or "").strip()


# ── 通用 ─────────────────────────────────────────────────────────────

def load_cfg():
    try:
        return json.loads(CFG.read_text(encoding="utf-8"))
    except Exception:
        return {}


def find_node(cfg):
    """找一个能用的 node.exe。

    顺序是按"多大概率找得到"排的，不是按优先级：
    PATH 里能拿到的最常见（nvm / winget / scoop / 官方安装器都可能落在那），
    其次是 WorkBuddy 自带的（版本号子目录，所以用通配而不是写死）。
    以前这里写死了一个 C:\\Users\\<某个人>\\...\\22.22.2-6\\node.exe，
    换台机器必然找不到 → 归档功能静默失效。
    """
    cands = []
    n = (cfg.get("archive") or {}).get("node")
    if n:
        cands.append(n)

    w = shutil.which("node")
    if w:
        cands.append(w)

    home = Path.home()
    cands += [
        r"C:\Program Files\nodejs\node.exe",
        r"C:\Program Files (x86)\nodejs\node.exe",
        str(home / "AppData" / "Local" / "Programs" / "nodejs" / "node.exe"),
    ]

    # WorkBuddy 内置的：<home>\.workbuddy\binaries\node\versions\<版本>\node.exe
    base = home / ".workbuddy" / "binaries" / "node" / "versions"
    if base.is_dir():
        try:
            for p in sorted(base.iterdir(), reverse=True):
                cands.append(str(p / "node.exe"))
        except OSError:
            pass

    for c in cands:
        if c and Path(c).exists():
            return c
    return None


def ts2dt(ms):
    try:
        return datetime.fromtimestamp(ms / 1000.0)
    except Exception:
        return None


def render(turns, meta):
    """turns: [(datetime|None, 'me'|'ai', text)]"""
    L = []
    L.append("---")
    for k in ("session", "platform", "project", "start", "end", "turns", "model",
              "source_bytes", "source_mtime", "archived"):
        v = meta.get(k, "")
        L.append("%s: %s" % (k, v if v is not None else ""))
    L.append("---")
    L.append("")
    L.append("# 对话原文 · %s · %s" % (meta.get("platform"), meta.get("project") or meta.get("session")))
    L.append("")
    L.append("> 原文归档。不进简报、不参与淘汰、不注入上下文。")
    L.append("> 检索：`mem.py search --raw <关键词>`")
    L.append("")

    last_day = None
    for dt, who, text in turns:
        if dt is not None:
            d = dt.strftime("%Y-%m-%d")
            if d != last_day:
                last_day = d
                L.append("")
                L.append("## —— %s ——" % d)
                L.append("")
            stamp = dt.strftime("%H:%M")
        else:
            stamp = "--:--"
        L.append("### %s %s" % (stamp, "我" if who == "me" else "AI"))
        L.append("")
        L.append(text)
        L.append("")
    return "\n".join(L)


def target_path(platform, project, sid, start_dt):
    d = (start_dt or datetime.now()).strftime("%Y-%m-%d")
    month = d[:7].replace("-", "-")
    slug = re.sub(r"[^0-9A-Za-z\u4e00-\u9fa5_-]+", "_", project or "session")[:40]
    name = "%s-%s-%s-%s.md" % (d, platform, slug, (sid or "x")[:8])
    p = RAW / month / name
    p.parent.mkdir(parents=True, exist_ok=True)
    return p


def is_fresh(p, src_bytes, src_mtime):
    if not p.exists():
        return False
    try:
        head = p.read_text(encoding="utf-8", errors="replace")[:800]
    except Exception:
        return False
    return ("source_bytes: %d" % src_bytes) in head and ("source_mtime: %d" % src_mtime) in head


# ── WorkBuddy ────────────────────────────────────────────────────────

WB_PROJECTS = Path(os.environ.get("USERPROFILE") or Path.home()) / ".workbuddy" / "projects"


def parse_wb(p):
    turns = []
    model = ""
    first_ts = last_ts = None
    with open(p, "r", encoding="utf-8", errors="replace") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                o = json.loads(line)
            except Exception:
                continue
            t = o.get("type")
            if t in ("reasoning", "function_call"):
                if not model:
                    pd = o.get("providerData") or {}
                    model = pd.get("model") or pd.get("requestModelId") or ""
                continue
            if t != "message":
                continue
            role = o.get("role")
            blocks = o.get("content") or []
            text = "".join(b.get("text", "") for b in blocks if isinstance(b, dict))
            text = clean_user(text) if role == "user" else clean_assistant(text)
            if not text:
                continue
            dt = ts2dt(o.get("timestamp") or 0)
            if dt:
                first_ts = first_ts or dt
                last_ts = dt
            turns.append((dt, "me" if role == "user" else "ai", text))
    return turns, model, first_ts, last_ts


def archive_wb(cfg, force, o):
    node_unused = None
    if not WB_PROJECTS.exists():
        o.append("[wb] 找不到目录 %s" % WB_PROJECTS)
        return
    files = sorted(WB_PROJECTS.rglob("*.jsonl"))
    o.append("[wb] 发现 %d 个会话文件" % len(files))
    for src in files:
        proj = src.parent.name
        sid = src.stem
        try:
            st = src.stat()
        except Exception:
            continue
        if st.st_size < 200:
            continue
        # 先粗判目标路径需要 start 时间，解析一次即得
        turns, model, first_ts, last_ts = parse_wb(src)
        if not turns:
            o.append("  - 跳过（无对话）%s" % sid[:8])
            continue
        dst = target_path("workbuddy", proj, sid, first_ts)
        if not force and is_fresh(dst, st.st_size, int(st.st_mtime)):
            o.append("  = 未变 %s" % dst.name)
            continue
        meta = {
            "session": sid,
            "platform": "workbuddy",
            "project": proj,
            "start": first_ts.strftime("%Y-%m-%dT%H:%M:%S%z") if first_ts else "",
            "end": last_ts.strftime("%Y-%m-%dT%H:%M:%S%z") if last_ts else "",
            "turns": len(turns),
            "model": model,
            "source_bytes": st.st_size,
            "source_mtime": int(st.st_mtime),
            "archived": datetime.now().strftime("%Y-%m-%dT%H:%M:%S%z"),
        }
        dst.write_text(render(turns, meta), encoding="utf-8")
        o.append("  + %s（%d 轮，%.1f KB）" % (dst.name, len(turns), dst.stat().st_size / 1024))


# ── DSH ──────────────────────────────────────────────────────────────

DSH_SESS = Path(r"F:\DSH\sessions")


def dsh_to_jsonl(node, src, tmp):
    tool = ROOT / ".tools" / "zstd2jsonl.js"
    r = subprocess.run([node, str(tool), str(src), str(tmp)],
                       capture_output=True, text=True, encoding="utf-8", errors="replace")
    if r.returncode != 0:
        return False, (r.stderr or r.stdout or "")[:300]
    return True, (r.stdout or "").strip()


def parse_dsh(jsonl_path):
    turns = []
    model = ""
    first_ts = last_ts = None
    cwd = ""
    with open(jsonl_path, "r", encoding="utf-8", errors="replace") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                o = json.loads(line)
            except Exception:
                continue
            t = o.get("type")
            if t == "session":
                cwd = o.get("cwd") or ""
                continue
            if t == "request/context" and not model:
                d = o.get("data") or {}
                model = d.get("model") or ""
                continue
            dt = ts2dt(o.get("time") or 0)
            if t == "user/message":
                d = o.get("data") or {}
                txt = "".join(b.get("text", "") for b in (d.get("content") or []) if isinstance(b, dict))
                txt = clean_user(txt)
                if not txt:
                    continue
                turns.append((dt, "me", txt))
                first_ts = first_ts or dt
                last_ts = dt
            elif t == "assistant/message":
                d = o.get("data") or {}
                msg = d.get("message") or {}
                if not model:
                    src = msg.get("source") or {}
                    model = src.get("model") or ""
                parts = [b.get("text", "") for b in (msg.get("content") or [])
                         if isinstance(b, dict) and b.get("type") == "text"]
                txt = clean_assistant("\n".join(p for p in parts if p))
                if not txt:
                    continue
                turns.append((dt, "ai", txt))
                first_ts = first_ts or dt
                last_ts = dt
    proj = Path(cwd).name if cwd else ""
    return turns, model, first_ts, last_ts, proj


def archive_dsh(cfg, force, o):
    if not DSH_SESS.exists():
        o.append("[dsh] 找不到目录 %s" % DSH_SESS)
        return
    node = find_node(cfg)
    files = sorted(DSH_SESS.rglob("session*.zstd"))
    # 同一会话目录里可能同时有旧格式 session.jsonl.zstd 和新格式 session.v4.jsonl.zstd，
    # 它们是同一个会话的两份快照，只取 v4（新格式更全），否则会互相覆盖
    groups = {}
    for f in files:
        groups.setdefault(f.parent, []).append(f)
    picked = []
    for d, fs in groups.items():
        v4 = [x for x in fs if ".v4." in x.name]
        picked.append(v4[0] if v4 else fs[0])
    files = sorted(picked)
    o.append("[dsh] 发现 %d 个会话（%d 个文件），node=%s" % (len(files), len(groups) and sum(len(v) for v in groups.values()), "有" if node else "无"))
    if not node:
        o.append("  ! 没有 node，DSH 侧跳过（Python 3.13 标准库不支持 zstd）")
        return
    tmp = ROOT / ".meta" / "_tmp_dsh.jsonl"
    tmp.parent.mkdir(parents=True, exist_ok=True)
    for src in files:
        sid = src.parent.name if src.parent.name.startswith("session-") else src.stem
        try:
            st = src.stat()
        except Exception:
            continue
        ok, info = dsh_to_jsonl(node, src, tmp)
        if not ok:
            o.append("  ! 解压失败 %s：%s" % (sid[:16], info))
            continue
        turns, model, first_ts, last_ts, proj = parse_dsh(tmp)
        if not turns:
            o.append("  - 跳过（无对话）%s" % sid[:16])
            continue
        dst = target_path("dsh", proj or sid, sid.replace("session-", ""), first_ts)
        if not force and is_fresh(dst, st.st_size, int(st.st_mtime)):
            o.append("  = 未变 %s" % dst.name)
            continue
        meta = {
            "session": sid,
            "platform": "dsh",
            "project": proj,
            "start": first_ts.strftime("%Y-%m-%dT%H:%M:%S%z") if first_ts else "",
            "end": last_ts.strftime("%Y-%m-%dT%H:%M:%S%z") if last_ts else "",
            "turns": len(turns),
            "model": model,
            "source_bytes": st.st_size,
            "source_mtime": int(st.st_mtime),
            "archived": datetime.now().strftime("%Y-%m-%dT%H:%M:%S%z"),
        }
        dst.write_text(render(turns, meta), encoding="utf-8")
        o.append("  + %s（%d 轮）" % (dst.name, len(turns)))
    try:
        tmp.unlink()
    except Exception:
        pass


# ── main ─────────────────────────────────────────────────────────────

def main():
    ap = argparse.ArgumentParser(description="把聊天原文归档进 .raw/")
    ap.add_argument("--only", choices=["wb", "dsh"], help="只归档一边")
    ap.add_argument("--force", action="store_true", help="源没变也重导")
    ap.add_argument("--out", help="报告写进这个文件")
    a = ap.parse_args()

    cfg = load_cfg()
    o = []
    o.append("# 归档报告 · %s" % datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
    o.append("")
    if a.only in (None, "wb"):
        archive_wb(cfg, a.force, o)
        o.append("")
    if a.only in (None, "dsh"):
        archive_dsh(cfg, a.force, o)
        o.append("")

    n = len(list(RAW.rglob("*.md")))
    total = sum(p.stat().st_size for p in RAW.rglob("*.md"))
    o.append("---")
    o.append(".raw 现有 %d 个文件，共 %.2f MB" % (n, total / 1024 / 1024))

    text = "\n".join(o)
    if a.out:
        Path(a.out).write_text(text, encoding="utf-8")
    else:
        try:
            print(text)
        except Exception:
            print("（控制台编码不支持，请用 --out 写文件）")


if __name__ == "__main__":
    main()
