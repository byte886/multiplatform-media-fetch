#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
以“得到文字并梳理成文章”为目标的默认获取流水线（一条命令决定下什么）：

  1) 字幕优先：探测手动/自动字幕，多种字幕里【中文优先】(简中>繁中>英文>其他，
     手动>自动)；命中则只下字幕、转 srt、并清洗成纯文本，不再下载音视频；
  2) 无字幕：平台有音轨就下【最小尺寸音频】（送 FunASR 转写，最省流量）；
  3) 连音轨都没有：才下【可 OCR 的视频】(默认 ≤720p、保证画面清晰)；
     —— 视频下载后【默认不做 OCR】，只在 manifest 标注需要时再走 OCR 技能；
  4) 全程写 fetch-manifest-<id>.json，记录走了哪条路、产物、语言、是否要转写/翻译。

非中文内容默认需要翻译成中文（manifest.need_translate=true）；文章梳理由 AI 完成，
方法见 references/article-pipeline.md。

用法：
    python3 fetch_for_article.py "<URL或BV号/抖音ID>" [-o downloads]
        [--force auto|subtitle|audio|video] [--ocr-quality 720]
        [--browser chrome] [--proxy http://127.0.0.1:7890] [--no-browser-cookies]
"""
import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import media_downloader as md  # noqa: E402  (导入即完成 yt-dlp 解释器自举)
from clean_subtitle import clean as clean_subtitle_raw  # noqa: E402

AUDIO_EXTS = (".m4a", ".mp3", ".webm", ".opus", ".wav", ".aac")
VIDEO_EXTS = (".mp4", ".mkv", ".webm")


def _has_audio(info) -> bool:
    return any(f.get("acodec") not in (None, "none")
               for f in (info.get("formats") or []))


def _is_zh(lang) -> bool:
    return bool(lang) and str(lang).lower().replace("_", "-").startswith("zh")


def _artifacts(out: Path, vid, exts):
    # 注意：文件名含字面 [id]，不能用 glob（[] 会被当成字符类通配符）
    tag = f"[{vid}]"
    return [str(p) for p in sorted(out.iterdir())
            if tag in p.name and p.suffix.lower() in exts]


def run(url, out_dir="downloads", force="auto", ocr_quality=720, netkw=None):
    netkw = netkw or {}
    out = Path(out_dir).expanduser()
    out.mkdir(parents=True, exist_ok=True)

    print("[1/决策] 解析视频信息（字幕/音轨/语言）...", flush=True)
    info, platform = md.probe_info(url, **netkw)
    if not info:
        sys.exit(
            "[决策] 视频信息解析失败（多为风控/cookie/代理问题），未下载任何内容。\n"
            "  · YouTube：检查代理（Clash 7890），被拦时加 --browser chrome；\n"
            "  · B站：412 风控，冷却几分钟、勿反复重试；\n"
            "  · 抖音：匿名票据被拒时加 --browser chrome 复用登录态。")
    vid = info.get("id")
    title, duration, info_lang = info.get("title"), info.get("duration"), info.get("language")
    pick = md.choose_subtitle(info)
    has_audio = _has_audio(info)
    print(f"   标题：{title}\n   时长：{duration}s｜平台：{platform}｜"
          f"报告语言：{info_lang}｜字幕：{pick['lang'] if pick else '无'}"
          f"｜含音轨：{has_audio}", flush=True)

    manifest = {
        "url": url, "platform": platform, "id": vid, "title": title,
        "duration_sec": duration, "reported_language": info_lang,
        "route": None, "artifacts": [], "need_transcribe": False,
        "need_translate": False, "subtitle": None, "next_steps": [],
    }

    # —— 路线 1：字幕（只下字幕、转 srt、清洗成稿，不下任何音视频）—— #
    if force == "auto" and pick:
        print("[2/决策] 命中字幕 → 只下字幕并清洗，不下载音视频", flush=True)
        got = md.download_subtitles(url, output_dir=out, **netkw)
        if got and got["files"]:
            pick = got["pick"]
            manifest["route"] = "subtitle"
            manifest["subtitle"] = pick
            for sp_str in got["files"]:
                sp = Path(sp_str)
                manifest["artifacts"].append(sp_str)
                try:
                    paras = clean_subtitle_raw(sp.read_text(encoding="utf-8", errors="ignore"))
                    cp = sp.with_name(sp.stem + ".clean.txt")
                    cp.write_text(
                        f"# {title}｜字幕清洗稿（{pick['lang']}，"
                        f"{'手动' if pick['kind'] == 'manual' else '自动'}）\n\n"
                        + "\n\n".join(paras) + "\n", encoding="utf-8")
                    manifest["artifacts"].append(str(cp))
                    print(f"   字幕清洗稿（{sum(len(x) for x in paras)} 字）：{cp}")
                except Exception as exc:
                    print(f"   [warn] 字幕清洗失败：{exc}")
            manifest["need_translate"] = not _is_zh(pick["lang"])
            manifest["next_steps"].append("直接基于字幕清洗稿梳理文章（无需转写）")
        else:
            # probe 看到但下载落空：落到音频兜底
            force = "audio"
            print("   [warn] 字幕下载落空，回退到音频路线", flush=True)

    # —— 路线 2：最小尺寸音频（送 FunASR 转写）—— #
    if manifest["route"] is None and force in ("auto", "audio") and (has_audio or force == "audio"):
        print("[2/决策] 无可用字幕 → 下载最小尺寸音频供转写", flush=True)
        md.download_audio(url, output_dir=out, smallest=True, **netkw)
        manifest["route"] = "audio"
        manifest["need_transcribe"] = True
        manifest["artifacts"] = _artifacts(out, vid, AUDIO_EXTS)
        manifest["next_steps"].append(
            "转写：python3 transcribe.py \"<音频路径>\" transcripts --lang auto（日语用 ja）")
        manifest["need_translate"] = (not _is_zh(info_lang)) if info_lang \
            else "转写后按文本语言判定，非中文默认译中文"

    # —— 路线 3：可 OCR 视频（默认不 OCR）—— #
    if manifest["route"] is None:
        print(f"[2/决策] 无字幕/无独立音轨 → 下载可 OCR 视频（≤{ocr_quality}p，默认不自动 OCR）", flush=True)
        md.download_video(url, output_dir=out, quality=ocr_quality, **netkw)
        manifest["route"] = "video-for-ocr"
        manifest["artifacts"] = _artifacts(out, vid, VIDEO_EXTS)
        manifest["next_steps"] = [
            "默认不做视频 OCR；确需画面文字时，再用 OCR/work-doc-extract 技能抽帧识别",
            "若该视频其实有声音，优先改走音频路线（--force audio），成本更低"]

    if manifest["need_translate"] is True:
        manifest["next_steps"].append("内容非中文：默认翻译成中文（见 transcribe-and-translate.md）")
    manifest["next_steps"].append(
        "识别作者角色（教学/新闻评论/测评/经验分享/访谈/宣传…），按对应结构梳理成中文文章（见 article-pipeline.md）")

    mpath = out / f"fetch-manifest-{vid}.json"
    mpath.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n[完成] 路线={manifest['route']}｜产物 {len(manifest['artifacts'])} 个；清单：{mpath}")
    for s in manifest["next_steps"]:
        print("   下一步 -", s)
    return manifest


def main():
    ap = argparse.ArgumentParser(description="以出文章为目标：字幕>小音频>可OCR视频 自动决策")
    ap.add_argument("url")
    ap.add_argument("-o", "--out", default="downloads")
    ap.add_argument("--force", choices=["auto", "subtitle", "audio", "video"], default="auto",
                    help="强制走某条路线，默认 auto 按优先级自动决策")
    ap.add_argument("--ocr-quality", type=int, default=720,
                    help="兜底视频清晰度上限，默认 720（保证 OCR 清晰又不过大）")
    ap.add_argument("--browser", default=None)
    ap.add_argument("--browser-profile", default=None)
    ap.add_argument("--proxy", default=None)
    ap.add_argument("--no-proxy", action="store_true")
    ap.add_argument("--no-browser-cookies", action="store_true")
    ap.add_argument("--cookies", dest="cookie_file", default=None)
    args = ap.parse_args()
    netkw = dict(proxy=args.proxy, no_proxy=args.no_proxy, browser=args.browser,
                 browser_profile=args.browser_profile,
                 no_browser_cookies=args.no_browser_cookies,
                 cookie_file=args.cookie_file)
    run(args.url, out_dir=args.out, force=args.force,
        ocr_quality=args.ocr_quality, netkw=netkw)


if __name__ == "__main__":
    main()
