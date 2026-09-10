#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
本地 FunASR（SenseVoiceSmall + fsmn-vad）离线转写统一入口，可在任意窗口运行。
自动发现一个“装了 funasr 的 Python”并用它重入自身，无需手动激活某个项目的 venv。

发现顺序：
    1) 环境变量 FUNASR_PYTHON
    2) ~/Doubao/chats 下名为 transcription/venv 的虚拟环境
    3) PATH 上的 python3 / python（验证能 import funasr）

两种模式：
  整段（默认）：
    python3 transcribe.py <音视频> [输出目录] [--lang auto|zh|ja|en|ko|yue]
    产物：<输出目录>/<文件名>/transcript.md + transcript.json
  按章节精确分段：
    python3 transcribe.py <音视频> [输出目录] --chapters chapters.json [--lang zh]
    chapters.json = [{"start":0,"end":141,"title":"..."}, ...]（秒）
    产物：<输出目录>/<文件名>/chapters.json + chapters_raw.md

说明：
  - 内部固定 use_itn=True、VAD 单段≤30s、batch_size_s=60，不要改；
  - 日语内容建议显式 --lang ja（用 zh/auto 偶发误判）；
  - 依赖 ffmpeg/ffprobe 在 PATH；模型首次运行自动下载后可离线。
"""
import argparse
import glob
import json
import os
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

BOOT_FLAG = "_FUNASR_BOOTSTRAPPED"


def _can_import(py: str, module: str = "funasr") -> bool:
    try:
        r = subprocess.run([py, "-c", f"import {module}"],
                           capture_output=True, timeout=30)
        return r.returncode == 0
    except Exception:
        return False


def _candidate_funasr_pythons():
    cands = []
    env = os.environ.get("FUNASR_PYTHON")
    if env:
        cands.append(env)
    home = str(Path.home())
    # 只在 Doubao/chats 下按固定深度查找（避免递归遍历整个 home 导致卡死）
    for pat in (f"{home}/Doubao/chats/*/*/transcription/venv/bin/python",
                f"{home}/Doubao/chats/*/*/*/transcription/venv/bin/python",
                f"{home}/Doubao/chats/*/*/*/*/transcription/venv/bin/python"):
        cands.extend(sorted(glob.glob(pat)))
    for name in ("python3", "python"):
        p = shutil.which(name)
        if p:
            cands.append(p)
    return cands


def bootstrap_funasr():
    try:
        import funasr  # noqa: F401
        return
    except ImportError:
        pass
    if os.environ.get(BOOT_FLAG) == "1":
        sys.exit("当前解释器仍无法 import funasr，已停止自举。请用 FUNASR_PYTHON 指定正确环境。")
    seen = set()
    for py in _candidate_funasr_pythons():
        if not py or py in seen:
            continue
        seen.add(py)
        if not Path(py).exists() or not os.access(py, os.X_OK):
            continue
        if _can_import(py, "funasr"):
            print(f"[bootstrap] 改用带 FunASR 的解释器：{py}", flush=True)
            env = dict(os.environ, **{BOOT_FLAG: "1"})
            os.execve(py, [py, os.path.abspath(__file__), *sys.argv[1:]], env)
    sys.exit(
        "未找到 FunASR 环境。请二选一：\n"
        "  A) 设置环境变量 FUNASR_PYTHON 指向已装 funasr 的 venv python；\n"
        "  B) 新建环境：python3 -m venv venv && venv/bin/pip install "
        "'torch==2.2.2' 'numpy<2' 'funasr==1.4.3' modelscope\n"
        "     模型 iic/SenseVoiceSmall + fsmn-vad 首次运行自动下载，之后离线可用。"
    )


bootstrap_funasr()


# ----------------------------- 转写实现 ----------------------------- #
def _ffmpeg_to_wav(src: str, dst: str, start=None, end=None) -> bool:
    cmd = ["ffmpeg", "-y"]
    if start is not None:
        cmd += ["-ss", str(start)]
    if end is not None:
        cmd += ["-to", str(end)]
    cmd += ["-i", src, "-vn", "-acodec", "pcm_s16le", "-ar", "16000",
            "-ac", "1", dst]
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        print(f"[ERROR] ffmpeg: {r.stderr[-500:]}")
        return False
    return True


def _clean(text: str) -> str:
    text = re.sub(r"<\|[^|]+\|>", "", text)
    return re.sub(r"\s+", " ", text).strip()


def _split_paras(full: str, max_len: int = 500):
    sentences = re.split(r"(?<=[。？！?!])", full)
    paras, cur = [], ""
    for s in sentences:
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


def _mmss(sec) -> str:
    sec = int(float(sec))
    return f"{sec // 60:02d}:{sec % 60:02d}"


def _load_model():
    from funasr import AutoModel
    return AutoModel(model="iic/SenseVoiceSmall", vad_model="fsmn-vad",
                     vad_kwargs={"max_single_segment_time": 30000},
                     disable_update=True)


def run_whole(src: Path, out_dir: Path, lang: str):
    out_dir.mkdir(parents=True, exist_ok=True)
    md_path, json_path = out_dir / "transcript.md", out_dir / "transcript.json"
    if md_path.exists() and md_path.stat().st_size > 100:
        print("已存在转写结果，跳过")
        return
    wav = out_dir / "_audio16k.wav"
    print("[1/3] 提取 16k 单声道 wav ...", flush=True)
    if not _ffmpeg_to_wav(str(src), str(wav)):
        sys.exit(1)
    print(f"[2/3] 加载模型（language={lang}）...", flush=True)
    t0 = time.time()
    model = _load_model()
    print(f"模型加载 {time.time() - t0:.1f}s，开始转写 ...", flush=True)

    probe = subprocess.run(
        ["ffprobe", "-v", "quiet", "-show_entries", "format=duration",
         "-of", "default=noprint_wrappers=1:nokey=1", str(wav)],
        capture_output=True, text=True)
    total = float(probe.stdout.strip() or 0)

    t0 = time.time()
    res = model.generate(input=str(wav), language=lang, use_itn=True,
                         batch_size_s=60)
    elapsed = time.time() - t0
    segs = [_clean(i.get("text", "")) for i in res]
    segs = [s for s in segs if s]
    full = "。".join(segs) + "。"
    speed = total / elapsed if elapsed else 0
    print(f"转写完成: {elapsed:.1f}s, {speed:.1f}x实时, {len(segs)}段, {len(full)}字",
          flush=True)

    paras = _split_paras(full)
    with open(md_path, "w", encoding="utf-8") as f:
        f.write(f"# {src.stem}\n\n")
        f.write(f"> 自动转写 | 语言 {lang} | 时长 {total/3600:.2f} 小时 | "
                f"耗时 {elapsed/60:.1f} 分钟 | {speed:.1f}x 实时 | 约 {len(full)} 字\n\n")
        for i, p in enumerate(paras, 1):
            f.write(f"## 第{i}段\n\n{p}\n\n")
    json.dump({"language": lang, "duration": total, "elapsed": elapsed,
               "chars": len(full), "segments": segs},
              open(json_path, "w", encoding="utf-8"),
              ensure_ascii=False, indent=2)
    wav.unlink(missing_ok=True)
    print(f"[3/3] 已保存: {md_path}", flush=True)


def run_chapters(src: Path, out_dir: Path, chapters_path: str, lang: str):
    chapters = json.load(open(chapters_path, encoding="utf-8"))
    out_dir.mkdir(parents=True, exist_ok=True)
    json_path, md_path = out_dir / "chapters.json", out_dir / "chapters_raw.md"
    if json_path.exists():
        print("章节转写已存在，跳过")
        return
    print(f"[1/2] 加载模型（language={lang}，只加载一次）...", flush=True)
    model = _load_model()
    print(f"共 {len(chapters)} 章，开始逐章转写 ...", flush=True)
    results = []
    for i, ch in enumerate(chapters, 1):
        wav = out_dir / f"_ch{i:02d}.wav"
        if not _ffmpeg_to_wav(str(src), str(wav), ch["start"], ch["end"]):
            ch_text = ""
        else:
            t = time.time()
            res = model.generate(input=str(wav), language=lang, use_itn=True,
                                 batch_size_s=60)
            segs = [_clean(x.get("text", "")) for x in res]
            ch_text = "。".join(s for s in segs if s)
            wav.unlink(missing_ok=True)
            print(f"  [{i:02d}/{len(chapters)}] {_mmss(ch['start'])}-"
                  f"{_mmss(ch['end'])} {ch.get('title','')}  "
                  f"({time.time()-t:.1f}s, {len(ch_text)}字)", flush=True)
        results.append({**ch, "text": ch_text})
    json.dump({"language": lang, "source": src.name, "chapters": results},
              open(json_path, "w", encoding="utf-8"),
              ensure_ascii=False, indent=2)
    with open(md_path, "w", encoding="utf-8") as f:
        f.write(f"# {src.stem}｜章节原始转写\n\n")
        for i, r in enumerate(results, 1):
            f.write(f"## {i}. [{_mmss(r['start'])}-{_mmss(r['end'])}] "
                    f"{r.get('title','')}\n\n{r['text']}\n\n")
    print(f"[2/2] 完成: {json_path}", flush=True)


def main():
    ap = argparse.ArgumentParser(description="FunASR 本地离线转写（整段/按章节）")
    ap.add_argument("src", help="音频或视频文件")
    ap.add_argument("out_dir", nargs="?", default="transcripts", help="输出目录")
    ap.add_argument("--lang", default="auto",
                    choices=["auto", "zh", "ja", "en", "ko", "yue"],
                    help="语种；日语建议 ja，默认 auto")
    ap.add_argument("--chapters", default=None,
                    help="章节 JSON（含 start/end/title，秒），提供后按章节精确转写")
    args = ap.parse_args()

    src = Path(args.src).expanduser().resolve()
    if not src.exists():
        sys.exit(f"找不到输入文件：{src}")
    out_dir = Path(args.out_dir).expanduser() / src.stem
    if args.chapters:
        run_chapters(src, out_dir, args.chapters, args.lang)
    else:
        run_whole(src, out_dir, args.lang)


if __name__ == "__main__":
    main()
