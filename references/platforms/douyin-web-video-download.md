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

> ⚠️ **一条视频一个独立 cell，禁止在一个 cell 里长循环连下多条**（2026-10-11 实测踩坑）：单 cell 有执行时长上限，长循环会超时；更危险的是 SPA 切换视频后画面/缓冲切换慢，若边导航边取 URL 会**串流**——连续两条下成同一个 tos 对象（md5 相同）。下面的稳健版用三道闸防串流：①导航后 `page_info` 校验 URL 含 vid 且标题正确；②记录播放**前**已缓冲的流 path 集合，只取播放**后新增差集**；③URL 一律按 **path（去掉 `?` 签名 query）识别身份**——同一 tos 对象每次重签 query 都不同，用完整 URL 去重会失效。下载后再用 md5 复核（见下节）。

```python
import seed_browser_use as bu, json, re, time

vid = "7121280916038618405"          # 目标视频纯数字 ID
expect_kw = "能变色的贵重宝石"        # 标题应包含的关键词（确认没串到别的视频）
out_name = f"{expect_kw}.mp4"        # 建议用简短中文标题命名落盘

def unwrap(x):                        # 兼容 bu.js 返回被 dict 包裹
    if isinstance(x, dict):
        for k in ("result", "value", "data"):
            if k in x: return unwrap(x[k])
    return x

def tos_paths():
    # 返回 {去签名path: (br, 完整url)}；path 才是流的身份，签名 query 每次会变
    p = unwrap(bu.js("return performance.getEntriesByType('resource').map(e=>e.name)"
                     ".filter(n=>n.indexOf('/video/tos')>=0||n.indexOf('douyinvod')>=0);")) or []
    s = json.dumps(bu.network_requests(), ensure_ascii=False, default=str)
    t = s.replace('\\u002F','/').replace('\\/','/').replace('\\u0026','&').replace('&amp;','&')
    urls = re.findall(r'https?://[^\s"\\\]\)<>]*?/video/tos[^\s"\\\]\)<>]*', t)
    out = {}
    for u in [*p, *urls]:
        path = u.split('?')[0]
        m = re.search(r'[?&]br=(\d+)', u); br = int(m.group(1)) if m else 0
        if path not in out or br > out[path][0]:   # 同 path 保留码率最高者
            out[path] = (br, u)
    return out

# 1) 导航，先校验页面确实是目标视频（防串流第一道闸）
bu.navigate(f"https://www.douyin.com/video/{vid}")
bu.wait_for_load(timeout=20); time.sleep(3)
info = bu.page_info()
assert vid in str(info.get("url", "")), f"页面URL不含目标vid：{info.get('url')}"
assert expect_kw in str(info.get("title", "")), f"标题不符（疑串流）：{info.get('title')}"

# 2) 记录播放前已缓冲的流 path 集合（SPA 可能残留上一条视频的流）
before = set(tos_paths().keys())

# 3) 点播放并拖动，等新流缓冲（不播放不发起媒体流请求）
bu.js("var v=document.querySelector('video'); if(v){v.muted=false; v.currentTime=2; v.play().catch(()=>{});}")
time.sleep(9)
after = tos_paths()

# 4) 只选“播放后新增”的流，取 br 最高（音视频合一，无需另抓 audio 轨）
new_paths = set(after) - before
cand = sorted(new_paths, key=lambda x: after[x][0], reverse=True)
assert cand, "播放后无新增 video/tos 流：可能未播放/被风控/需登录，按登录墙或稍后重试处理"
url = after[cand[0]][1]

# 5) 立即下载（签名 URL 时效极短；浏览器上下文带会话）
rec = bu.download(url, filename=out_name)
print(rec, "\npath=", cand[0], "br=", after[cand[0]][0])
```

## 下载后校验与转写

```bash
# 1) 防串流复核（多条连下必做）：算新文件 md5，与本批已下载文件逐一比对
md5 -q "<下载目录>/<新文件>.mp4"     # macOS；Linux 用 md5sum
#    出现与任一已下载文件相同的 md5 = 串流（下成了上一条），删除该文件、回到步骤1重下；
#    ffprobe 的时长也可辅助判别（不同视频时长一般不同）。

# 2) 确认含视频流 + 音频流（应看到 h264 与 aac 两条 stream；web playAddr 音视频合一）
ffprobe -v error -show_entries stream=codec_type,codec_name,width,height \
        -of default "<下载目录>/<文件>.mp4"

# 3) 转写（FunASR，自动发现解释器；模型首次运行自动下载，之后离线）
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
