#!/usr/bin/env python3
"""
智能关键帧抽取：
1. ffmpeg镜头边界检测自动分镜头
2. 每个镜头取中间帧
3. 拉普拉斯方差评分挑最清晰的帧
4. dHash去重
5. 输出：精选关键帧 + 每帧时间戳 + 清晰度评分
"""
import subprocess
import json
import os
import sys
from pathlib import Path

try:
    import cv2
    import numpy as np
except ImportError:
    print("需要opencv-python: pip install opencv-python", file=sys.stderr)
    sys.exit(1)


def get_video_info(video_path):
    """用ffprobe获取视频信息"""
    cmd = [
        "ffprobe", "-v", "quiet", "-print_format", "json",
        "-show_format", "-show_streams", video_path
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    info = json.loads(result.stdout)
    duration = float(info["format"]["duration"])
    video_stream = next(
        (s for s in info.get("streams", []) if s.get("codec_type") == "video"),
        info["streams"][0],
    )
    num, _, den = video_stream.get("r_frame_rate", "25/1").partition("/")
    den_f = float(den or 1)
    fps = float(num) / den_f if den_f else 25.0
    return duration, fps


def detect_scene_cuts(video_path, threshold=0.3):
    """
    用ffmpeg的select滤镜检测镜头切换点
    返回：每个镜头切换的时间点（秒）
    """
    cmd = [
        "ffmpeg", "-i", video_path,
        "-vf", f"select='gt(scene,{threshold})',showinfo",
        "-f", "null", "-"
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    cuts = []
    for line in result.stderr.split("\n"):
        if "pts_time" in line:
            try:
                t = float(line.split("pts_time:")[1].split()[0])
                cuts.append(t)
            except:
                pass
    return cuts


def laplacian_sharpness(frame):
    """拉普拉斯方差，越高越清晰"""
    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    return cv2.Laplacian(gray, cv2.CV_64F).var()


def dhash(frame, hash_size=8):
    """感知哈希用于去重"""
    resized = cv2.resize(frame, (hash_size + 1, hash_size))
    gray = cv2.cvtColor(resized, cv2.COLOR_BGR2GRAY)
    diff = gray[:, 1:] > gray[:, :-1]
    return sum([2 ** i for (i, v) in enumerate(diff.flatten()) if v])


def hamming_distance(h1, h2):
    return bin(h1 ^ h2).count("1")


def extract_keyframes(video_path, output_dir, max_frames=5, min_gap_sec=3):
    """
    主函数：抽取精选关键帧
    """
    video_path = Path(video_path)
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    duration, fps = get_video_info(str(video_path))
    print(f"视频时长: {duration:.1f}秒, 帧率: {fps:.1f}fps")

    # 1. 检测镜头切换
    cuts = detect_scene_cuts(str(video_path))
    cuts = [0.0] + cuts + [duration]
    print(f"检测到 {len(cuts)-1} 个镜头")

    # 2. 每个镜头取中间帧，计算清晰度
    cap = cv2.VideoCapture(str(video_path))
    candidates = []

    for i in range(len(cuts) - 1):
        start = cuts[i]
        end = cuts[i + 1]
        mid = (start + end) / 2

        # 跳到该帧
        cap.set(cv2.CAP_PROP_POS_MSEC, mid * 1000)
        ret, frame = cap.read()
        if not ret:
            continue

        sharpness = laplacian_sharpness(frame)
        h = dhash(frame)
        candidates.append({
            "time": mid,
            "frame": frame,
            "sharpness": sharpness,
            "hash": h,
            "shot_idx": i
        })

    cap.release()

    # 3. 按清晰度排序，去重，选top N
    candidates.sort(key=lambda x: x["sharpness"], reverse=True)

    selected = []
    for c in candidates:
        # 和已选的比，相似就跳过
        duplicate = False
        for s in selected:
            if hamming_distance(c["hash"], s["hash"]) < 10:
                duplicate = True
                break
        if not duplicate:
            selected.append(c)
        if len(selected) >= max_frames:
            break

    # 4. 按时间排序保存
    selected.sort(key=lambda x: x["time"])
    saved = []
    for i, s in enumerate(selected):
        fname = f"frame_{i+1:02d}_{s['time']:.1f}s.jpg"
        fpath = output_dir / fname
        cv2.imwrite(str(fpath), s["frame"], [cv2.IMWRITE_JPEG_QUALITY, 90])
        saved.append({
            "file": str(fpath),
            "time_sec": round(s["time"], 1),
            "sharpness": round(s["sharpness"], 1)
        })
        print(f"  保存: {fname} (清晰度: {s['sharpness']:.0f})")

    return saved


if __name__ == "__main__":
    if len(sys.argv) < 3:
        print("用法: python extract_keyframes.py <视频路径> <输出目录> [最多帧数]")
        sys.exit(1)

    video = sys.argv[1]
    outdir = sys.argv[2]
    maxf = int(sys.argv[3]) if len(sys.argv) > 3 else 5

    frames = extract_keyframes(video, outdir, max_frames=maxf)
    print(f"\n完成：共抽取 {len(frames)} 个关键帧")
