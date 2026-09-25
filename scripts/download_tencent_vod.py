#!/usr/bin/env python3
"""
download_tencent_vod.py

接收 cdp_extract_tencent_vod.js 输出的 JSON 参数，下载并解密腾讯云 VOD
SimpleAES 加密的 HLS 分片，用 ffmpeg 合并为 MP4。

用法:
  python3 download_tencent_vod.py <params.json> [--output output.mp4] [--workers 8]

参数:
  params.json  - cdp_extract_tencent_vod.js --out 输出的文件
  --output     - 输出 MP4 路径（默认当前目录）
  --workers    - 并发下载数（默认 8）
"""
import argparse, json, os, subprocess, sys, urllib.request, tempfile
from Crypto.Cipher import AES
from concurrent.futures import ThreadPoolExecutor


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('params', help='cdp_extract 输出的 JSON 文件')
    ap.add_argument('--output', '-o', help='输出 MP4 路径')
    ap.add_argument('--workers', '-j', type=int, default=8)
    ap.add_argument('--keep-segments', action='store_true', help='保留解密后的分片')
    args = ap.parse_args()

    with open(args.params) as f:
        p = json.load(f)

    if 'error' in p:
        print(f'参数错误: {p["error"]}', file=sys.stderr)
        sys.exit(1)

    # 计算 ContentKey
    overlay_key = bytes.fromhex(p['overlayKey'])
    overlay_iv = bytes.fromhex(p['overlayIv'])
    response_key = bytes.fromhex(p['responseKey'])
    content_key = AES.new(overlay_key, AES.MODE_CBC, overlay_iv).decrypt(response_key)
    m3u8_iv = bytes.fromhex(p['m3u8Iv'])

    print(f'ContentKey: {content_key.hex()}')
    print(f'分片数: {p["segmentCount"]}')

    # 输出路径
    if args.output:
        out_mp4 = args.output
    else:
        out_mp4 = os.path.join(os.getcwd(), 'tencent_vod_output.mp4')

    # 分片临时目录
    seg_dir = tempfile.mkdtemp(prefix='tencent_vod_segs_')
    cdn_base = p['cdnBase']
    segments = p['segments']

    def dl(idx_seg):
        idx, seg_path = idx_seg
        out_path = os.path.join(seg_dir, f'seg_{idx:05d}.ts')
        if os.path.exists(out_path) and os.path.getsize(out_path) > 1000:
            return idx, 'cached'
        try:
            req = urllib.request.Request(cdn_base + seg_path)
            with urllib.request.urlopen(req, timeout=30) as r:
                enc = r.read()
            dec = AES.new(content_key, AES.MODE_CBC, m3u8_iv).decrypt(enc)
            with open(out_path, 'wb') as f:
                f.write(dec)
            return idx, 'ok'
        except Exception as e:
            return idx, f'error: {e}'

    with ThreadPoolExecutor(max_workers=args.workers) as ex:
        results = list(ex.map(dl, enumerate(segments)))

    ok = sum(1 for r in results if r[1] in ('ok', 'cached'))
    fails = [r for r in results if r[1] not in ('ok', 'cached')]
    print(f'下载完成: {ok}/{len(segments)}, 失败: {len(fails)}')
    if fails:
        for f in fails[:10]:
            print(f'  FAIL seg {f[0]}: {f[1]}')

    if ok < len(segments):
        print('有分片下载失败，请重试', file=sys.stderr)
        sys.exit(1)

    # ffmpeg 合并
    concat_file = os.path.join(seg_dir, 'concat.txt')
    with open(concat_file, 'w') as f:
        for i in range(len(segments)):
            f.write(f"file '{seg_dir}/seg_{i:05d}.ts'\n")

    print('ffmpeg 合并中...')
    subprocess.run([
        'ffmpeg', '-y',
        '-f', 'concat', '-safe', '0',
        '-i', concat_file,
        '-c', 'copy',
        '-bsf:a', 'aac_adtstoasc',
        out_mp4
    ], check=True)

    size_mb = os.path.getsize(out_mp4) / 1024 / 1024
    print(f'完成: {out_mp4} ({size_mb:.0f} MB)')

    # 清理
    if not args.keep_segments:
        import shutil
        shutil.rmtree(seg_dir, ignore_errors=True)


if __name__ == '__main__':
    main()
