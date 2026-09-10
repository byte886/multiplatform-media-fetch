#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
多链接 / 同系列批量取稿（"一次给多个链接、需要梳理与组织"场景的默认入口）。

当用户一次给多个 URL（常见于同一作者 / 同一系列分 P 讲解 / 强相关的几条视频），
本脚本一次完成：
  1) 批量探查元信息：标题、作者、频道、上传日期、时长、报告语言、是否有字幕、章节，
     先形成一张"系列总览"，不盲目下载音视频；
  2) 每条【字幕优先】：有字幕就只下字幕（复用 media_downloader.download_subtitles，
     中文优先、手动优先于自动），并按视频自带 chapters 把字幕组织成"按章节"的文字稿；
     没有章节则退化为整篇清洗分段（复用 clean_subtitle 的去滚动重复/分段逻辑）；
  3) 无字幕的条目标注 route=needs-fetch_for_article，默认【不】自动下音视频
     （批量场景避免一上来拉一堆大文件）；加 --with-audio 才委托 fetch_for_article 走
     "最小音频转写 / 可 OCR 视频"的单条流水线；
  4) 产出 series-overview.md（人读）与 series-overview.json（机读）：按上传日期排序、
     同作者检测、建议阅读顺序。

注意分工：
  · 单条视频的"字幕 > 最小音频 > 可 OCR 视频"自动决策仍用 fetch_for_article.py；
  · 本脚本只额外提供"批量探查 + 字幕按章节切分 + 系列总览"，不重复下载/转写实现；
  · 取到文字之后如何"合一篇还是拆多篇、理主线、与已有知识库重新编排"，是 AI 的工作，
    方法见 references/series-synthesis.md。

用法：
    python3 batch_fetch.py "<url1>" "<url2>" ... [-o series-fetch]
        [--no-chapters] [--with-audio]
        [--proxy http://127.0.0.1:7890 | --no-proxy]
        [--browser chrome] [--browser-profile "Profile 1"] [--cookies c.txt] [--no-browser-cookies]
"""
import argparse
import html
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import media_downloader as md  # noqa: E402  (导入即完成 yt-dlp 解释器自举)
import clean_subtitle as cs  # noqa: E402

CUE_TIME = re.compile(r"(?:(\d+):)?(\d{2}):(\d{2})[,.](\d{3})\s*-->")


def _fmt_dur(sec):
    try:
        sec = int(sec)
        return f"{sec // 60}:{sec % 60:02d}"
    except (TypeError, ValueError):
        return "-"


def _fmt_date(d):
    if d and len(str(d)) == 8:
        return f"{str(d)[:4]}-{str(d)[4:6]}-{str(d)[6:]}"
    return str(d or "-")


def parse_timed_cues(raw):
    """从 srt/vtt 解析出 [(起始秒, 文本)]，去标签；兼容 srt 逗号与 vtt 点号时间。"""
    cues, buf, start, in_cue = [], [], None, False
    for line in raw.splitlines():
        mt = CUE_TIME.search(line)
        if mt:
            in_cue, buf = True, []
            h, m, s, _ms = mt.groups()
            start = (int(h or 0) * 3600 + int(m) * 60 + int(s))
            continue
        if not line.strip():
            if in_cue and buf:
                cues.append((start, " ".join(buf).strip()))
            in_cue, buf, start = False, [], None
            continue
        if in_cue:
            t = cs.strip_tags(line)
            if t and not t.isdigit() and not t.startswith(("WEBVTT", "Kind:", "Language:")):
                buf.append(t)
    if in_cue and buf:
        cues.append((start, " ".join(buf).strip()))
    return [(t, x) for t, x in cues if x]


def dedupe_cues(cues):
    """与 clean_subtitle.dedupe_scroll 同规则的"带时间"版本：消除自动字幕滚动累积，
    人工字幕无滚动、基本原样保留。返回 [(起始秒, 文本)]。"""
    out, prev = [], ""
    for t, cur in cues:
        c, p = re.sub(r"\s+", "", cur), re.sub(r"\s+", "", prev)
        if p and (c.startswith(p) or c in p):
            inc = cur[len(cur) - (len(c) - len(p)):].strip() if c.startswith(p) else ""
            if inc:
                out.append((t, inc))
        elif p and len(p) >= 6:
            n = min(len(c), len(p))
            k = 0
            while k < n and c[k] == p[k]:
                k += 1
            if k >= int(len(p) * 0.6):
                tail = cur[k:].strip(" ，。、,.")
                if tail:
                    out.append((t, tail))
            else:
                out.append((t, cur))
        else:
            out.append((t, cur))
        prev = cur
    return out


def bucket_by_chapters(cues, chapters, dur):
    """把带时间 cue 按章节时间窗分桶；返回 [[(t,txt),...],...]，落不进任何章的并入最近上一章。"""
    buckets = [[] for _ in chapters]
    last = 0
    for t, txt in cues:
        idx = -1
        for i, c in enumerate(chapters):
            if t >= c.get("start_time", 0) and t < c.get("end_time", (dur or 10 ** 9) + 1):
                idx = i
                break
        if idx < 0:  # 容错：边界外（如片尾）归入最后/最近一章
            idx = last if buckets else 0
        buckets[idx].append((t, txt))
        last = idx
    return buckets


def build_chaptered_md(info, sub_path, use_chapters):
    cues = dedupe_cues(parse_timed_cues(Path(sub_path).read_text(encoding="utf-8", errors="ignore")))
    chapters = info.get("chapters") or []
    title, dur = info.get("title"), info.get("duration")
    n_chars = sum(len(x) for _, x in cues)
    head = [f"# {title}", "",
            f"- 视频ID：{info.get('id')}｜UP：{info.get('uploader')}｜上传：{_fmt_date(info.get('upload_date'))}"
            f"｜时长：{_fmt_dur(dur)}｜字幕 {n_chars} 字、{len(cues)} 句", ""]
    if use_chapters and chapters:
        buckets = bucket_by_chapters(cues, chapters, dur)
        for i, c in enumerate(chapters):
            a, b = _fmt_dur(c.get("start_time")), _fmt_dur(c.get("end_time"))
            text = "".join(x for _, x in buckets[i])
            paras = cs.to_paragraphs(text)
            head += [f"## {i + 1}. {c.get('title')}（{a}-{b}）", ""] + paras + [""]
    else:
        head += ["## 全文", ""] + cs.to_paragraphs("".join(x for _, x in cues)) + [""]
    return "\n".join(head), n_chars, len(chapters)


def run(urls, out_dir="series-fetch", use_chapters=True, with_audio=False, netkw=None):
    netkw = netkw or {}
    out = Path(out_dir).expanduser()
    (out / "subs").mkdir(parents=True, exist_ok=True)
    (out / "transcripts").mkdir(parents=True, exist_ok=True)
    rows = []
    for n, url in enumerate(urls, 1):
        print(f"\n[{n}/{len(urls)}] 探查：{url}", flush=True)
        try:
            info, platform = md.probe_info(url, **netkw)
        except Exception as exc:  # 单条失败不拖垮整批
            rows.append({"url": url, "error": str(exc)[:200]})
            print(f"  [error] 探查失败：{exc}")
            continue
        pick = md.choose_subtitle(info)
        row = {
            "url": url, "platform": platform, "id": info.get("id"),
            "title": info.get("title"), "uploader": info.get("uploader"),
            "channel_id": info.get("channel_id"), "upload_date": info.get("upload_date"),
            "duration_sec": info.get("duration"), "reported_language": info.get("language"),
            "n_chapters": len(info.get("chapters") or []),
            "subtitle": (pick or {}).get("lang") if pick else None,
            "subtitle_kind": (pick or {}).get("kind") if pick else None,
            "route": None, "artifact": None, "chars": 0,
        }
        if pick:  # 路线 1：只下字幕并按章节切分
            got = md.download_subtitles(url, output_dir=out / "subs", **netkw)
            if got and got["files"]:
                md_text, n_chars, _ = build_chaptered_md(info, got["files"][0], use_chapters)
                tp = out / "transcripts" / f"{info.get('id')}.md"
                tp.write_text(md_text, encoding="utf-8")
                row.update(route="subtitle", artifact=str(tp), chars=n_chars)
                print(f"  ✓ 字幕稿（{n_chars} 字、{row['n_chapters']} 章）：{tp.name}")
            else:
                row["route"] = "needs-fetch_for_article"
        else:  # 无字幕
            if with_audio:
                import fetch_for_article as fa  # 委托单条流水线，避免重复实现
                m = fa.run(url, out_dir=str(out / "single"), netkw=netkw)
                row.update(route=f"delegated:{m.get('route')}", artifact=";".join(m.get("artifacts", [])))
            else:
                row["route"] = "needs-fetch_for_article"
                print("  · 无字幕：默认不下音视频；需要时跑 "
                      f"fetch_for_article.py \"{url}\"，或本脚本加 --with-audio")
        rows.append(row)

    # —— 系列总览（按上传日期排序；同作者检测）——
    ok = [r for r in rows if "id" in r]
    ok.sort(key=lambda r: r.get("upload_date") or "9999")
    channels = {r.get("channel_id") for r in ok if r.get("channel_id")}
    same_author = len(channels) == 1
    L = ["# 系列取稿总览", "",
         f"- 条目：{len(ok)}/{len(rows)} 成功｜同一作者：{'是（' + (next(iter(channels)) or '') + '）' if same_author else '否（' + '、'.join(sorted(filter(None, channels))) + '）'}",
         f"- 建议阅读顺序：默认按上传日期从早到晚（系列通常按依赖递进讲解）；若作者另有编号以作者编号为准。",
         "", "| # | 上传 | 时长 | UP | 标题 | 语言 | 路线 | 章 | 字数 |",
         "|---|---|---|---|---|---|---|---|---|"]
    for i, r in enumerate(ok, 1):
        L.append("| {i} | {d} | {t} | {u} | {ti} | {lg} | {rt} | {nc} | {c} |".format(
            i=i, d=_fmt_date(r["upload_date"]), t=_fmt_dur(r["duration_sec"]),
            u=r.get("uploader"), ti=r.get("title"), lg=r.get("reported_language") or "-",
            rt=r.get("route"), nc=r.get("n_chapters"), c=r.get("chars") or "-"))
    needs = [r for r in ok if str(r.get("route", "")).startswith("needs")]
    if needs:
        L += ["", "## 需另行走音频/视频取稿的条目", ""]
        for r in needs:
            L.append(f"- {r.get('title')}（{r['url']}）：无字幕，跑 `fetch_for_article.py \"{r['url']}\"`")
    (out / "series-overview.md").write_text("\n".join(L) + "\n", encoding="utf-8")
    (out / "series-overview.json").write_text(
        json.dumps({"same_author": same_author, "channels": sorted(filter(None, channels)),
                    "items_sorted_by_date": ok, "errors": [r for r in rows if "error" in r]},
                   ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n[总览] 同一作者={same_author}｜成功 {len(ok)}｜总览：{out / 'series-overview.md'}")
    return ok


def main():
    ap = argparse.ArgumentParser(description="多链接/同系列批量取稿：批量探查 + 字幕按章节切分 + 系列总览")
    ap.add_argument("urls", nargs="+")
    ap.add_argument("-o", "--out", default="series-fetch")
    ap.add_argument("--no-chapters", action="store_true", help="不按章节切分，整篇清洗分段")
    ap.add_argument("--with-audio", action="store_true",
                    help="对无字幕条目自动委托 fetch_for_article 下最小音频转写（默认关闭，先看总览）")
    ap.add_argument("--proxy", default=None)
    ap.add_argument("--no-proxy", action="store_true")
    ap.add_argument("--browser", default=None)
    ap.add_argument("--browser-profile", default=None)
    ap.add_argument("--cookies", dest="cookie_file", default=None)
    ap.add_argument("--no-browser-cookies", action="store_true")
    a = ap.parse_args()
    netkw = dict(proxy=a.proxy, no_proxy=a.no_proxy, browser=a.browser,
                 browser_profile=a.browser_profile, cookie_file=a.cookie_file,
                 no_browser_cookies=a.no_browser_cookies)
    run(a.urls, out_dir=a.out, use_chapters=not a.no_chapters,
        with_audio=a.with_audio, netkw=netkw)


if __name__ == "__main__":
    main()
