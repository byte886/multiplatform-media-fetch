#!/bin/bash
# record_live.sh - 录制 HLS 直播/点播流（通用版）
#
# 用法:
#   ./record_live.sh <m3u8_url> [output.mp4] [headers_json]
#
# 示例:
#   # 简单录制
#   ./record_live.sh "https://example.com/live.m3u8" output.mp4
#
#   # 带鉴权头（从 cdp_extract_live_m3u8.js 输出的 cookies/referer）
#   ./record_live.sh "https://example.com/live.m3u8" output.mp4 '{"cookies":"session=xxx","referer":"https://example.com/"}'
#
# 说明:
#   - 自动重连，断流后恢复
#   - -c copy 直接复制流，零损失不转码
#   - -live_start_index -3 从最近分片开始（直播关键，避免从头录）
#   - 加密流（EXT-X-KEY）不适用此脚本，需用 download_tencent_vod.py
set -euo pipefail

M3U8_URL="${1:?用法: $0 <m3u8_url> [output.mp4] [headers_json]}"
OUTPUT="${2:-live_recording.mp4}"
HEADERS_JSON="${3:-}"

# 构建 headers 参数
HEADERS_ARGS=""
if [ -n "$HEADERS_JSON" ]; then
  COOKIES=$(echo "$HEADERS_JSON" | python3 -c "import sys,json; print(json.load(sys.stdin).get('cookies',''))" 2>/dev/null || echo "")
  REFERER=$(echo "$HEADERS_JSON" | python3 -c "import sys,json; print(json.load(sys.stdin).get('referer',''))" 2>/dev/null || echo "")
  USER_AGENT=$(echo "$HEADERS_JSON" | python3 -c "import sys,json; print(json.load(sys.stdin).get('userAgent',''))" 2>/dev/null || echo "")

  HEADER_STR=""
  [ -n "$COOKIES" ] && HEADER_STR="Cookie: $COOKIES\r\n"
  [ -n "$REFERER" ] && HEADER_STR="${HEADER_STR}Referer: $REFERER\r\n"
  [ -n "$USER_AGENT" ] && HEADER_STR="${HEADER_STR}User-Agent: $USER_AGENT\r\n"

  if [ -n "$HEADER_STR" ]; then
    HEADERS_ARGS="-headers '${HEADER_STR}'"
  fi
fi

echo "=== 录制 HLS 流 ==="
echo "URL: $M3U8_URL"
echo "输出: $OUTPUT"
echo ""

# 用 eval 处理 headers 参数（含特殊字符）
CMD="ffmpeg -y \
  -loglevel warning \
  -live_start_index -3 \
  -reconnect 1 \
  -reconnect_streamed 1 \
  -reconnect_delay_max 5 \
  -rw_timeout 15000000 \
  -i '${M3U8_URL}' \
  ${HEADERS_ARGS} \
  -c copy \
  -bsf:a aac_adtstoasc \
  -f mp4 \
  '${OUTPUT}'"

eval "$CMD"

echo ""
echo "=== 录制结束: $OUTPUT ==="
