# 编号课堂 / 腾讯云 VOD SimpleAES 加密视频下载 SOP

## 适用场景

编号课堂（bianhaoclass.com / study1.bianhaoclass.com）等使用腾讯云 VOD + tcplayer + hls.js 私有加密（SimpleAES）的站点。特征：
- 播放页 URL 包含 `live/<数字>` 或 `shop/<shop_code>/live/<id>`
- CDN 域名 `vod.tenclass.net.cn` 或 `*.myqcloud.com`
- m3u8 文件名含 `voddrm.token.` 前缀
- EXT-X-KEY URI 指向 `drm.vodplayvideo.net/getlicense`

## 关键约束（必须遵守）

- **用外部 Google Chrome，不要用豆包内置浏览器**。CDP 连接的是用户日常 Chrome，复用其登录态。
- **不要让用户"接管浏览器"或"在内置浏览器登录"**。需要登录时，用 `open -a "Google Chrome" <URL>` 打开外部 Chrome，让用户扫码登录。
- **不要启动新的 Chrome 实例**。连接的是用户已经开着的 Chrome（通过 DevToolsActivePort）。
- **不需要放完视频**。点一下播放让 hls 初始化即可。

## 前置条件

1. **Chrome 远程调试已开启**：`chrome://inspect/#remote-debugging` 对当前 profile 勾选一次（持久化）。
2. **依赖**：
   - Node.js + puppeteer-core：`cd /tmp && npm install puppeteer-core`
   - Python3 + pycryptodome：`pip3 install pycryptodome`
   - ffmpeg
   - macOS「辅助功能」权限（自动点授权弹窗）
3. **会计知识库 connect_browser.js** 路径：`~/Desktop/accounting-kb/code/scripts/cdp/connect_browser.js`（弹窗自动处理已封装）

## 完整操作流程

### Step 0: 从用户消息提取 live ID

从 URL 中提取 `live/<数字>` 部分，例如 `live/912663`。短链接（如 `https://s.bianhaoclass.com/xxxx`）先 `curl -sL -o /dev/null -w '%{url_effective}' <短链接>` 跟随重定向拿到完整 URL。

### Step 1: 先尝试直接提取参数（不要先问用户）

```bash
SKILL_DIR="$HOME/Doubao/skills/multiplatform-media-fetch"
export NODE_PATH="${NODE_PATH:-/tmp/node_modules}"
node "$SKILL_DIR/scripts/cdp_extract_tencent_vod.js" "live/903960" --out /tmp/bianhao_params.json
```

根据结果分流：
- **成功**（输出 JSON 含 overlayKey、segmentCount）：跳到 Step 3 直接下载。
- **`未找到包含 "live/xxx" 的标签页`**：Chrome 没打开视频页，执行 Step 2a。
- **`no hls instance found`**：页面打开了但没点播放，执行 Step 2b。
- **连接超时/弹窗问题**：重试一次；仍失败则提示用户手动点 Chrome 的"允许"弹窗后重试。

### Step 2a: Chrome 没打开视频页

```bash
open -a "Google Chrome" "https://study1.bianhaoclass.com/shop/nw71a3d521a00018/live/903960?play_back=1"
```

告诉用户："外部 Chrome 已打开视频页。如果需要登录请微信扫码，登录后点一下视频播放按钮，完成后告诉我。" 等待用户确认后重新跑 Step 1。

### Step 2b: 页面打开了但没点播放

告诉用户："页面已打开，请在外部 Chrome 里点一下视频播放按钮，等画面出来即可（不需要放完）。" 等待用户确认后重新跑 Step 1。

### Step 3: 一键下载

```bash
SKILL_DIR="$HOME/Doubao/skills/multiplatform-media-fetch"
export NODE_PATH="${NODE_PATH:-/tmp/node_modules}"
bash "$SKILL_DIR/scripts/download_bianhao.sh" "live/912663" "/output/path/视频.mp4"
```

脚本自动完成：
1. CDP 连接外部 Chrome（自动点"要允许远程调试吗"弹窗）
2. 从 hls.config 读取 overlayKey/overlayIv
3. fetch m3u8 和 license key
4. Python 计算 ContentKey，8 线程并发下载解密分片
5. ffmpeg 合并为 MP4

## 技术实现

- **CDP 连接**：复用会计知识库 `connectDailyChrome`（puppeteer-core），内置：
  - 后台 800ms 串行点授权弹窗（AXPress，跨进程锁，点中后还焦）
  - 偶发 403 自动退避重试 3 次
  - `handleDevToolsAsPage: true` 兼容 Chrome 144+
- **解密原理**：tcplayer 客户端随机生成 overlayKey/overlayIv，license endpoint 返回用其加密的 ContentKey 密文。本地 `AES-128-CBC-decrypt(responseKey, overlayKey, overlayIv)` 得到 ContentKey，再用 ContentKey + m3u8 IV 解密分片。

## 故障排查

| 问题 | 原因 | 解决 |
|------|------|------|
| `未找到包含 "live/xxx" 的标签页` | Chrome 里没打开视频页 | `open -a "Google Chrome" <视频URL>` |
| 页面跳转到登录页 | 登录态过期 | 让用户在外部 Chrome 微信扫码登录 |
| `no hls instance found` | tcplayer 未初始化 | 让用户点播放按钮看到画面后重试 |
| `连接日常 Chrome 失败` | 弹窗没点掉/CDP 未就绪 | 手动点一下 Chrome 的"允许"弹窗，重跑 |
| 分片下载失败率高 | CDN 限流 | 脚本默认 8 线程，可改 `--workers 4` |
| 解密后首字节非 0x47 | overlayKey/responseKey 不匹配 | 页面 reload 过，重新点播放后再提取 |
| `Cannot find module 'puppeteer-core'` | Node 依赖缺失 | `cd /tmp && npm install puppeteer-core` |

## 注意事项

- **overlayKey 每次页面加载都变**：提取参数后立即下载，不要间隔太久；页面 reload 后需重新点播放再提取。
- **输出 1080p**：自动选 `_2.m3u8`。
- **收尾用 disconnect 不用 close**：不要关闭用户的 Chrome 窗口。
