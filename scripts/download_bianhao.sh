#!/bin/bash
# download_bianhao.sh - 一键下载编号课堂/腾讯云 VOD SimpleAES 加密视频
#
# 用法:
#   ./download_bianhao.sh <url_substring> [output.mp4] [quality]
#
# 示例:
#   ./download_bianhao.sh "live/903960" "第一天.mp4"
#   ./download_bianhao.sh "live/903960" "第一天.mp4" 1080p
#
# quality: 720p(默认) 或 1080p
#
# 前置:
#   1. Chrome 已开启远程调试 (chrome://inspect/#remote-debugging 勾选)
#   2. 视频页面已在 Chrome 中打开并点过播放
#   3. node 有 puppeteer-core (NODE_PATH=/tmp/node_modules)
#   4. python3 有 pycryptodome, ffmpeg
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

URL_SUB="${1:?用法: $0 <url_substring> [output.mp4] [quality]}"
OUTPUT="${2:-}"
QUALITY="${3:-720p}"

# puppeteer-core 在 /tmp/node_modules
export NODE_PATH="${NODE_PATH:-/tmp/node_modules}"

PARAMS_FILE=$(mktemp -t tencent_vod_params.XXXXXX.json)
trap 'rm -f "$PARAMS_FILE"' EXIT

echo "=== Step 1: 从 Chrome 提取解密参数 (${QUALITY}) ==="
node "$SCRIPT_DIR/cdp_extract_tencent_vod.js" "$URL_SUB" --out "$PARAMS_FILE" --quality "$QUALITY"

echo ""
echo "=== Step 2: 下载并解密分片 ==="
if [ -n "$OUTPUT" ]; then
  python3 "$SCRIPT_DIR/download_tencent_vod.py" "$PARAMS_FILE" --output "$OUTPUT"
else
  python3 "$SCRIPT_DIR/download_tencent_vod.py" "$PARAMS_FILE"
fi

echo ""
echo "=== 完成 ==="
