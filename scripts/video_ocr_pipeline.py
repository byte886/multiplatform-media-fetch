#!/usr/bin/env python3
"""
video_ocr_pipeline.py — 视频屏幕文字系统提取流水线

定时抽帧 → dHash 感知哈希去重 → 批量 OCR → 带时间戳输出 Markdown

用法:
  python3 video_ocr_pipeline.py <video.mp4> [--out out.md] [--interval 10] [--hash-threshold 15]

流程:
  1. ffmpeg 每 N 秒抽一帧（默认 10s），缩放到 1280 宽
  2. PIL + imagehash 计算 dHash，汉明距离 < threshold 的相邻帧去重
  3. 对去重后的唯一帧，调用 macOS Vision OCR（ocr_vision.swift）
  4. 输出带 [XXs] 时间戳的 Markdown，方便 grep 定位

依赖:
  - ffmpeg
  - Python: Pillow, imagehash (pip install imagehash)
  - macOS: swift + work-doc-extract/scripts/ocr_vision.swift
"""

import argparse
import os
import subprocess
import sys
import tempfile
from pathlib import Path


def extract_frames(video: Path, outdir: Path, interval: int):
    """Step 1: ffmpeg extract one frame every interval seconds."""
    outdir.mkdir(parents=True, exist_ok=True)
    pattern = str(outdir / "f_%04d.jpg")
    cmd = [
        "ffmpeg", "-y", "-i", str(video),
        "-vf", f"fps=1/{interval},scale=1280:-1",
        "-q:v", "3", pattern
    ]
    print(f"[1/4] Extracting frames every {interval}s ...")
    subprocess.run(cmd, check=True, capture_output=True)
    frames = sorted(outdir.glob("f_*.jpg"))
    print(f"      → {len(frames)} frames")
    return frames


def dedup_frames(frames: list, threshold: int):
    """Step 2: dHash dedup. Keep frame if hamming distance from last kept > threshold."""
    from PIL import Image
    import imagehash

    print(f"[2/4] Deduping (dHash threshold={threshold}) ...")
    kept = []
    last_hash = None
    for f in frames:
        img = Image.open(f)
        h = imagehash.dhash(img, hash_size=16)
        if last_hash is None or (h - last_hash) > threshold:
            kept.append(f)
            last_hash = h
    print(f"      → {len(kept)} unique frames (from {len(frames)})")
    return kept


def ocr_frame(img_path: Path, vision_script: Path) -> str:
    """OCR a single frame using macOS Vision."""
    try:
        r = subprocess.run(
            ["swift", str(vision_script), str(img_path)],
            capture_output=True, text=True, timeout=30
        )
        return r.stdout.strip()
    except Exception as e:
        return f"[OCR error: {e}]"


def batch_ocr(kept: list, interval: int, vision_script: Path):
    """Step 3: OCR all unique frames with macOS Vision."""
    print(f"[3/4] Batch OCR {len(kept)} frames ...")
    results = []
    total = len(kept)
    for i, f in enumerate(kept):
        # frame number → seconds
        stem = f.stem  # f_0001
        num = int(stem.split("_")[1])
        seconds = num * interval
        text = ocr_frame(f, vision_script)
        results.append((seconds, f.name, text))
        if (i + 1) % 50 == 0:
            print(f"      Progress: {i+1}/{total}")
    return results


def write_markdown(results: list, outfile: Path, video: Path, interval: int):
    """Step 4: Write timestamped Markdown."""
    print(f"[4/4] Writing {outfile} ...")
    with open(outfile, "w") as f:
        f.write(f"# Video OCR: {video.name}\n\n")
        f.write(f"- Source: `{video}`\n")
        f.write(f"- Frame interval: {interval}s\n")
        f.write(f"- Unique frames: {len(results)}\n")
        f.write(f"- Engine: macOS Vision OCR\n\n---\n\n")
        for seconds, fname, text in results:
            f.write(f"## [{seconds//60:02d}:{seconds%60:02d}] ({seconds}s) — {fname}\n\n")
            f.write(text + "\n\n")
    print(f"      Done: {outfile}")


def main():
    ap = argparse.ArgumentParser(description="Video screen text OCR pipeline")
    ap.add_argument("video", help="Input video file")
    ap.add_argument("--out", "-o", help="Output markdown file")
    ap.add_argument("--interval", type=int, default=10, help="Frame interval in seconds (default 10)")
    ap.add_argument("--hash-threshold", type=int, default=15, help="dHash hamming distance threshold (default 15)")
    args = ap.parse_args()

    video = Path(args.video).resolve()
    if not video.exists():
        print(f"Error: {video} not found", file=sys.stderr)
        sys.exit(1)

    outfile = Path(args.out) if args.out else video.parent / f"{video.stem}_ocr.md"

    # Find vision OCR script
    vision_script = Path.home() / "Doubao/skills/work-doc-extract/scripts/ocr_vision.swift"
    if not vision_script.exists():
        print(f"Error: vision OCR script not found at {vision_script}", file=sys.stderr)
        sys.exit(1)

    # Temp dir for frames
    tmpdir = Path(tempfile.mkdtemp(prefix="video_ocr_"))
    framedir = tmpdir / "frames"

    # Run pipeline
    frames = extract_frames(video, framedir, args.interval)
    kept = dedup_frames(frames, args.hash_threshold)
    results = batch_ocr(kept, args.interval, vision_script)
    write_markdown(results, outfile, video, args.interval)

    print(f"\nDone. Output: {outfile}")
    print(f"Tip: grep keywords in output to find relevant timestamps, then view frames manually.")


if __name__ == "__main__":
    main()
