#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
字幕清洗：srt/vtt/ttml -> 干净纯文本（供后续梳理成文章）。
- 去掉序号、时间轴、<c>/<i>/<00:..> 等标签与 HTML 实体；
- 消除 YouTube/B站自动字幕的“滚动累积”重复（相邻条目前缀叠加，只保留增量）；
- 按中文标点合并成可读段落（默认每段 <=500 字）。

用法：
    python3 clean_subtitle.py 输入.srt|输入.vtt [输出.txt] [--keep-time]
不指定输出时，在同目录生成 <名>.clean.txt。
"""
import argparse
import html
import re
import sys
from pathlib import Path

TIME_LINE = re.compile(r"-->|^[0-9]{2}:[0-9]{2}:[0-9]{2}")
TAG = re.compile(r"<[^>]+>")
INLINE_TIME = re.compile(r"<\s*\d+:\d+[\d:.,]*\s*>")


def strip_tags(line: str) -> str:
    line = INLINE_TIME.sub("", line)
    line = TAG.sub("", line)
    line = html.unescape(line)
    return line.replace("\u3000", " ").strip()


def iter_cue_texts(raw: str):
    """从 srt/vtt 文本里按时间轴块逐条取出 cue 文本。"""
    cues, buf, in_cue = [], [], False
    for line in raw.splitlines():
        if "-->" in line:
            in_cue = True
            buf = []
            continue
        if not line.strip():
            if in_cue and buf:
                cues.append(" ".join(buf).strip())
            in_cue, buf = False, []
            continue
        if in_cue:
            t = strip_tags(line)
            if t and not t.isdigit():
                buf.append(t)
    if in_cue and buf:
        cues.append(" ".join(buf).strip())
    return [c for c in cues if c]


def _lcp_len(a: str, b: str) -> int:
    n = min(len(a), len(b))
    i = 0
    while i < n and a[i] == b[i]:
        i += 1
    return i


def dedupe_scroll(cues):
    """自动字幕是滚动累积：后一条常包含前一条。只保留每条相对上一条的增量。"""
    out = []
    prev = ""
    for cur in cues:
        c = re.sub(r"\s+", "", cur)
        p = re.sub(r"\s+", "", prev)
        if p and (c.startswith(p) or c in p):
            # 当前条被上一条覆盖：纯滚动，取新增尾部
            inc = cur[len(cur) - (len(c) - len(p)):] if c.startswith(p) else ""
            inc = inc.strip()
            if inc:
                out.append(inc)
        elif p and len(p) >= 6:
            k = _lcp_len(c, p)
            # 高度前缀重叠才算滚动（阈值 60%），避免误删独立人工字幕
            if k >= int(len(p) * 0.6):
                tail = cur[k:].strip(" ，。、,.")
                if tail:
                    out.append(tail)
            else:
                out.append(cur)
        else:
            out.append(cur)
        prev = cur
    return out


def to_paragraphs(text: str, max_len: int = 500):
    parts = re.split(r"(?<=[。！？!?；;])", text)
    paras, cur = [], ""
    for s in parts:
        s = s.strip()
        if not s:
            continue
        if len(cur) + len(s) > max_len and cur:
            paras.append(cur)
            cur = s
        else:
            cur += s
    if cur:
        paras.append(cur)
    return paras


def clean(raw: str):
    cues = iter_cue_texts(raw)
    pieces = dedupe_scroll(cues)
    text = "".join(pieces)
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\s*([，。！？、；：])\s*", r"\1", text)
    return to_paragraphs(text)


def main():
    ap = argparse.ArgumentParser(description="字幕 srt/vtt 清洗为纯文本")
    ap.add_argument("input")
    ap.add_argument("output", nargs="?", default=None)
    ap.add_argument("--keep-time", action="store_true", help="（保留参数，默认不保留时间轴）")
    args = ap.parse_args()

    src = Path(args.input).expanduser()
    if not src.exists():
        sys.exit(f"找不到字幕文件：{src}")
    paras = clean(src.read_text(encoding="utf-8", errors="ignore"))
    body = "\n\n".join(paras)
    out = Path(args.output) if args.output else src.with_name(src.stem + ".clean.txt")
    header = f"# {src.stem}（字幕清洗稿，{len(body)} 字）\n\n"
    out.write_text(header + body + "\n", encoding="utf-8")
    print(f"[clean] {len(paras)} 段 / {len(body)} 字 -> {out}")


if __name__ == "__main__":
    main()
