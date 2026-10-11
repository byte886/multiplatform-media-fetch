# 抖音视频原片下载（浏览器直读 douyinvod 合一流 · yt-dlp 被风控时）

> 2026-10-11 实测沉淀。目标是拿到**视频原片 mp4**（供抽帧 / 视频分析 / 本地归档 / 转写），不是只读文稿。

## 什么时候用

- 需要视频**原片**，而 yt-dlp 抖音链路（匿名 ttwid、`--browser chrome`）已被风控拒绝（报 `Fresh cookies (not necessarily logged in) are needed` / 403）。
- 只要文字稿、不要原片时，优先走更轻的 [`douyin-browser-extract.md`](douyin-browser-extract.md)（官方"章节要点"等效字幕 + 关键帧 OCR），不必下载。
- 要先拿到一批收藏链接清单，走 [`douyin-favorites-extract.md`](douyin-favorites-extract.md)；本篇负责"拿到单条 vid 后把原片下下来"。

## 关键事实（2026-10-11 实测，macOS · bu 浏览器 · 已登录态）

1. 抖音 web 播放器走 **MSE**，`performance.getEntriesByType('resource')` 抓 douyinvod **命中 0**；媒体直链出现在 **`bu.network_requests()`** 的缓冲里。
2. 公开视频页 `https://www.douyin.com/video/<纯数字vid>` 在登录态下可直接播放；私密 / 关注可见 / 受限内容才需要登录。
3. playAddr 直链：域名 `v11-weba.douyinvod.com` / `v26-web.douyinvod.com`，路径 `/video/tos/cn/...`，query 带 `br=`（码率）、`mime_type=video_mp4`、`rc` 签名等。
4. **这条 `/video/tos` 流是音视频合一的 mp4**：URL 虽标 `mime_type=video_mp4`，但 `ffprobe` 实测同时含 **h264 视频流 + aac 音频流**（样例 1080×1920 / 44.1kHz 立体声 / 时长一致）。**下这一条就够，不需要再找 `/audio/tos` 独立音轨**（web 端通常也不出现独立 audio 流）。
5. 同一内容会出现多个 `br`（如 1027、1581），是不同清晰度，取 **`br` 数值最大**者。
6. **network buffer 跨浏览器 cell 会清空**：必须在**同一个 cell 内**依次完成「导航 → 点播放 → 取直链 → `bu.download`」；拆成多个 cell 会取空（`IndexError`）。
7. 直链是签名 URL、**时效很短**（路径里含过期时间 hex），取到后**立即下载**，不要存下来隔几分钟再用。

## 前置

- 已读 `browser-use-automation-mac` SKILL.md，用 `mac_computer_use_tool` 的 `plane="bu"`（其它平台用对应浏览器技能，逻辑相同）。
- bu 浏览器抖音登录态有效：打开 `https://www.douyin.com/user/self`，页面标题含用户名即已登录。
- 读操作返回空 / 登录提示 / 验证码 → 判定登录墙，**下一个动作必须 `interaction.request_action(type="browserControl")`** 交用户扫码，不得换 URL / 换号 / 改 cookie 绕过。

## 步骤（整段放在同一个浏览器 cell）

```python
import seed_browser_use as bu, json, re, time

vid = "7121280916038618405"          # 替换为目标视频纯数字 ID
out_name = f"probe_{vid}.mp4"        # 下载文件名（落浏览器下载目录）

def unwrap(x):                        # 兼容 bu.js 返回被 dict 包裹
    if isinstance(x, dict):
        for k in ("result", "value", "data"):
            if k in x: return unwrap(x[k])
    return x

# 1) 导航 + 点播放（不播放不会发起媒体流请求）
bu.navigate(f"https://www.douyin.com/video/{vid}")
bu.wait_for_load(timeout=20); time.sleep(4)
bu.js("var v=document.querySelector('video'); if(v){v.muted=false; v.play().catch(()=>{});}")
time.sleep(7)

# 2) 双路取流：performance（多数时候为空）+ network_requests（实测有效）
p = unwrap(bu.js("return performance.getEntriesByType('resource').map(e=>e.name)"
                 ".filter(n=>n.indexOf('/video/tos')>=0||n.indexOf('/audio/tos')>=0"
                 "||n.indexOf('douyinvod')>=0);")) or []
s = json.dumps(bu.network_requests(), ensure_ascii=False, default=str)
t = s.replace('\\u002F','/').replace('\\/','/').replace('\\u0026','&').replace('&amp;','&')
n = re.findall(r'https?://[^\s"\\\]\)<>]*?/(?:video|audio)/tos[^\s"\\\]\)<>]*', t)
urls = sorted(set([*p, *n]))

def br(u):
    m = re.search(r'[?&]br=(\d+)', u); return int(m.group(1)) if m else 0
vids = sorted([u for u in urls if '/video/tos' in u], key=br, reverse=True)
assert vids, "未取到 video/tos 直链：可能未播放/被风控/需登录，按登录墙或稍后重试处理"
url = vids[0]                        # 码率最高 = 最清晰（音视频合一）

# 3) 立即下载（浏览器上下文，带会话）
rec = bu.download(url, filename=out_name)
print(rec)                            # 关注 state=completed 与 path、bytes
```

## 下载后校验与转写

```bash
# 确认含视频流 + 音频流（应看到 h264 与 aac 两条 stream）
ffprobe -v error -show_entries stream=codec_type,codec_name,width,height \
        -of default "<下载目录>/probe_<vid>.mp4"

# 转写（FunASR，自动发现解释器；模型首次运行自动下载，之后离线）
python3 "$SKILL_DIR/scripts/process/funasr_transcribe.py" "<视频>.mp4" "<转写输出父目录>" --lang zh
# 产物：<输出父目录>/<视频文件名>/transcript.md + transcript.json
```

- 转写即**内容验证**：若内容名不副实（纯引流 / 无干货），在采集台账记为降级，不强行并入知识库。
- FunASR 常见同音错字（如"军绿宝石"应为"金绿宝石"），归并知识文档时用正确术语，转写原文保留。

## 防风控（硬性）

- **逐条串行**，严禁循环快刷；每条页面停留 ≥10–20s 模拟真人；建议单会话 / 每天限量（参考收藏遍历纪律：单会话 ≤15 条、间隔 ≥30s 更稳）。
- 撞验证码 / 限流 / 滑块：立即停、冷却，不换 UA、不改 cookie、不换号硬刚；需要验证就交用户。
- 每条完成立即回写台账 / 工单状态（去重基准），中断后续跑不重复下载。

## 与同目录文档分工

| 文档 | 负责 |
|---|---|
| `douyin-browser-extract.md` | 不下原片，浏览器直读"章节要点"+关键帧 OCR 出文稿（最轻） |
| `douyin-favorites-extract.md` | 登录态遍历收藏 / 关注列表，产出 vid+标题清单 |
| **本篇** | 拿到单条 vid 后，浏览器抓 douyinvod 合一直链**下载原片 mp4** |
