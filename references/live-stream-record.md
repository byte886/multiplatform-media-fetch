# HLS 直播流录制 SOP

## 适用场景

需要录制/下载网页中的 **HLS (.m3u8) 直播流**：
- 在线课程直播（编号课堂、腾讯云直播等）
- YouTube 直播（HLS）
- 无 DRM 加密的 HLS 点播

**不适用**：SimpleAES/DRM 加密流（用 `tencent-vod-simpleaes.md`）、DASH（mpd）、WebRTC（Zoom/腾讯会议）。

> 各平台直播协议不同：CDP 抓流地址 + ffmpeg 录制的思路通用，但 HLS/FLV 要分流处理。
> FLV 流 ffmpeg 同样能录（`-i "http://xxx.flv" -c copy out.mp4`），CDP 提取时过滤 `.flv` 即可。

## 各平台直播协议对照

| 平台 | 直播协议 | 网页端可抓？ | 备注 |
|------|----------|-------------|------|
| 编号课堂/腾讯云直播 | HLS (m3u8) | ✅ | 直播无加密，回放 SimpleAES 加密 |
| YouTube | HLS (m3u8) | ✅ | 需代理，带签名 headers |
| 小红书 | HLS/FLV 混合 | ✅ | 回放是 m3u8，直播可能 FLV |
| B站直播 | HTTP-FLV | ✅ | 网页端 flv 地址，ffmpeg 直录 |
| 抖音直播 | HTTP-FLV | ✅ | 网页端 flv，需带签名 |
| 视频号 | HTTPS-FLV（网页预览） | ⚠️ | 微信生态封闭，网页端难抓；DLNA 投屏可截获 m3u8 |
| 快手 | HTTP-FLV | ✅ | 同抖音 |
| 淘宝直播 | HLS/FLV | ✅ | |
| Zoom/腾讯会议 | WebRTC | ❌ | 只能录屏（OBS） |

**经验法则**：打开 Chrome DevTools → Network → 过滤 `.m3u8` 或 `.flv` → 点播放 → 出现哪个就用哪个协议录。ffmpeg 两种都支持。

## 前置条件

1. Chrome 已开启远程调试（`chrome://inspect/#remote-debugging`）
2. 视频页面已在 Chrome 中打开并**点过播放**
3. ffmpeg 已安装
4. Node.js + puppeteer-core（`NODE_PATH=/tmp/node_modules`）

## 完整流程

### Step 1: 提取 m3u8 地址

```bash
export NODE_PATH="${NODE_PATH:-/tmp/node_modules}"
SKILL_DIR="$HOME/Doubao/skills/multiplatform-media-fetch"

node "$SKILL_DIR/scripts/cdp_extract_live_m3u8.js" "<url_substring>" --out /tmp/live_params.json
```

- `<url_substring>`：页面 URL 的任意子串（如 `live/914473`）
- 脚本自动触发播放、等待初始化、从 performance entries 提取 m3u8
- 输出 JSON 包含：`m3u8Url`、`encrypted`、`cookies`、`referer`、`userAgent`

### Step 2: 判断是否加密

检查输出 JSON 的 `encrypted` 字段：
- **false**（无 EXT-X-KEY）：直接用 ffmpeg 录制，继续 Step 3
- **true**（有 EXT-X-KEY）：流已加密，本 SOP 不适用，改用对应加密方案

### Step 3: 录制

```bash
# 简单录制（无需鉴权）
bash "$SKILL_DIR/scripts/record_live.sh" "<m3u8_url>" output.mp4

# 带鉴权头（需要 cookie/referer 时）
bash "$SKILL_DIR/scripts/record_live.sh" "<m3u8_url>" output.mp4 /tmp/live_params.json
```

脚本关键参数：
- `-live_start_index -3`：从最近 3 个分片开始（直播关键，避免从头录历史）
- `-reconnect 1 -reconnect_streamed 1`：断流自动重连
- `-c copy`：直接复制流不转码，零损失
- `-bsf:a aac_adtstoasc`：AAC 转 MP4 兼容格式

### Step 4: 验证

```bash
ffprobe -v error -show_entries stream=codec_type,codec_name,width,height \
  -of default=noprint_wrappers=1 output.mp4
```

应看到 video（h264）和 audio（aac）两个流。

## 常见问题

| 问题 | 原因 | 解决 |
|------|------|------|
| `未找到包含 xxx 的标签页` | Chrome 没打开页面 | `open -a "Google Chrome" <URL>` |
| `未找到 m3u8 请求` | 视频没点播放 | 在 Chrome 里点播放按钮，等画面出来后重试 |
| ffmpeg 403/401 | 需要鉴权 | 把 cdp_extract 输出的 JSON 作为第 3 个参数传入 |
| 录制文件无法播放 | 直播中断/ffmpeg 被 kill | 重新运行，-reconnect 会自动恢复 |
| 录到的是历史内容 | 没加 -live_start_index | 脚本已内置，确保用最新版 |
| m3u8 有 EXT-X-KEY | 流加密 | 改用 tencent-vod-simpleaes.md 流程 |

## 手动提取 m3u8（不通过 CDP）

如果 CDP 不可用，可以手动在 Chrome DevTools 里找：
1. F12 打开开发者工具 → Network 标签
2. 过滤框输入 `m3u8`
3. 点播放视频
4. 右键 m3u8 请求 → Copy → Copy link address
5. 如需鉴权，同时复制 Request Headers 里的 Cookie 和 Referer

## 与回放下载的区别

| | 直播录制 | 回放下载 |
|---|---|---|
| 流地址 | `liveplay-*.m3u8` | `vod.*.m3u8` |
| 加密 | 通常不加密 | SimpleAES 加密 |
| 播放器 | 无 sfePlayers，blob URL | window.sfePlayers 存在 |
| 下载方式 | ffmpeg 实时录制 | Python 下载分片+解密 |
| 脚本 | `record_live.sh` | `download_bianhao.sh` |
