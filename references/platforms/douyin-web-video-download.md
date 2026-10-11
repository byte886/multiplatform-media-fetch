# 抖音视频原片下载（currentSrc + `__vid` 铁证法 · 浏览器直读 douyinvod）

> 2026-10-11 实测沉淀，当日经"批2 钻石 11 条"连续下载验证（11 条 md5 全唯一、转写名实相符）。
> 目标是拿到**视频原片 mp4**（供抽帧 / 视频分析 / 本地归档 / 转写），不是只读文稿。

## 什么时候用

- 需要视频**原片**，而 yt-dlp 抖音链路（匿名 ttwid、`--browser chrome`）已被风控拒绝（报 `Fresh cookies (not necessarily logged in) are needed` / 403）。
- 只要文字稿、不要原片时，优先走更轻的 [`douyin-browser-extract.md`](douyin-browser-extract.md)（官方"章节要点"等效字幕 + 关键帧 OCR），不必下载。
- 要先拿到一批收藏链接清单，走 [`douyin-favorites-extract.md`](douyin-favorites-extract.md)；本篇负责"拿到单条 vid 后把原片下下来"。

## 核心原理：为什么必须用 currentSrc + `__vid`（务必先读）

抖音 web 视频页里，`<video>` 元素的 **`currentSrc`（或 `.src`）直接就是播放器此刻真实播放的完整 mp4 直链**（2026-10-11 实测为**直接 mp4 URL，不是 `blob:` MSE**），而且这个 URL 的 query 末尾带一个身份参数 **`__vid=<19位视频id>`**。

- **`__vid` 是"这条流属于哪个视频"的铁证**：URL 含 `__vid=<目标vid>`，才能保证下下来的是当前视频，而不是别的视频。
- **播放器初始化有"预加载流污染"**：打开/切换视频页的瞬间，播放器会先挂一个**预加载或上一条残留的高码率流**（它的 `br` 往往反而更高），当前视频的真实流要稍等 1–40 秒才挂上。若"只等几秒 + 取全局最高 `br`"，会**误选到预加载流，下成另一条视频**（串流）。
  - 该污染发生在**抖音播放器 / 服务端层**，不在浏览器 CDP target 缓冲层——**"开新标签页隔离"无法避免**（实测新标签里黄钻页播放器一度仍放南非视频）。
  - 旧的"`bu.network_requests()` 取最高 `br`"、"播放前后 path 差集取最高 `br`"两种写法都会踩这个坑，**已废弃**，只在文末留档。
- **同 objectid 取最高码率**：currentSrc 只反映播放器"当前清晰度档"。先用它的 **objectid**（URL path 末段、去掉 `?` 之后那段）锚定身份，再在已缓冲的所有 tos URL 里筛**同一 objectid 且带同一 `__vid`** 的档位、取 `br` 最高者。同 objectid 必为同一条内容，零身份风险，又能拿到最清晰档。
- 页面的 `#RENDER_DATA`（SSR JSON）**不含播放地址**（走异步接口），不要试图从 SSR 里找 playAddr；currentSrc 才是正解。

## 关键事实（2026-10-11 实测，macOS · bu 浏览器 · 已登录态）

1. 公开视频页 `https://www.douyin.com/video/<纯数字vid>` 登录态可直接播放；私密 / 关注可见 / 受限内容才需要登录。
2. 直链域名 `v11-weba.douyinvod.com` / `v26-web.douyinvod.com`，路径 `/video/tos/cn/tos-cn-ve-xxxx/<objectid>/`，query 带 `br=`（码率）、`mime_type=video_mp4`、`__vid=<vid>`、签名等。
3. 这条 `/video/tos` 流是**音视频合一 mp4**：实测含 **h264 或 hevc 视频流 + aac 音频流**，下这一条即可，不需要另抓 `/audio/tos`。
4. 同一 objectid 可能有多个 `br` 清晰度档；也有部分老视频只有一档（`br` 两三百，属源片清晰度，照下）。
5. 直链是签名 URL、**时效很短**，取到后**立即下载**。
6. 编码可能是 **hevc(H.265)**（多见于早期/横屏视频），fmmpeg/ffprobe 一般可直接解；FunASR 只抽音轨不受影响。

## 前置

- 已读 `browser-use-automation-mac` SKILL.md，用 `mac_computer_use_tool` 的 `plane="bu"`（其它平台用对应浏览器技能，逻辑相同）。
- bu 浏览器抖音登录态有效：打开 `https://www.douyin.com/user/self`，页面标题含用户名即已登录。
- 读操作返回空 / 登录提示 / 验证码 → 判定登录墙，**下一个动作必须 `interaction.request_action(type="browserControl")`** 交用户扫码，不得换 URL / 换号 / 改 cookie 绕过。

## 步骤（一条视频一个独立 cell）

> 一条视频用一个独立浏览器 cell；**不要在一个 cell 里长循环连下多条**（cell 有时长上限，且不利于逐条核对）。条与条之间停顿、限量，见文末防风控。

```python
import seed_browser_use as bu, json, re, time

vid = "7166928141812763935"        # 目标视频纯数字 ID
expect_kw = "黄钻"                 # 标题应包含的关键词（标题校验，辅助防串）
out_name = "为什么有些黄色钻石不叫黄钻.mp4"

def unwrap(x):                      # 兼容 bu.js 返回被 dict 包裹
    if isinstance(x, dict):
        for k in ("result", "value", "data"):
            if k in x: return unwrap(x[k])
    return x

def collect_tos():                  # performance + network 双路汇总已缓冲的 /video/tos 直链
    p = unwrap(bu.js("return performance.getEntriesByType('resource').map(function(e){return e.name;})"
                     ".filter(function(n){return n.indexOf('/video/tos')>=0||n.indexOf('douyinvod')>=0;});")) or []
    s = json.dumps(bu.network_requests(), ensure_ascii=False, default=str)
    t = s.replace('\\u002F','/').replace('\\/','/').replace('\\u0026','&').replace('&amp;','&')
    n = re.findall(r'https?://[^\s"\\\]\)<>]*?/video/tos[^\s"\\\]\)<>]*', t)
    return [*p, *n]

def br(u):
    m = re.search(r'[?&]br=(\d+)', u); return int(m.group(1)) if m else 0

# 1) 导航 + 标题校验（第一道闸）
bu.navigate(f"https://www.douyin.com/video/{vid}"); bu.wait_for_load(timeout=20); time.sleep(3)
info = bu.page_info()
assert vid in str(info.get("url","")) and expect_kw in str(info.get("title","")), info.get("title")

# 2) 轮询 video.currentSrc，直到 URL 带 __vid=目标vid（身份铁证，核心步骤）
anchor = None
for i in range(22):                 # 约每 2 秒一次，最多等 ~44 秒
    s = unwrap(bu.js("var v=document.querySelector('video'); return v?(v.currentSrc||v.src||''):'';")) or ""
    if f"__vid={vid}" in s:
        anchor = s; break
    # 还没稳定：静音播放 + 轻微 seek，促发真实流挂上
    bu.js("var v=document.querySelector('video'); if(v){v.muted=true;v.play().catch(function(){}); v.currentTime=2+("+str(i)+"%4);}")
    time.sleep(2)
assert anchor, "currentSrc 始终未带目标 __vid：可能未播放/被风控/需登录，按登录墙或稍后重试"

# 3) 以 currentSrc 的 objectid 锚定身份，取同一 objectid + 同一 __vid 的最高码率档
oid = anchor.split('?')[0].rstrip('/').split('/')[-1]
same = [u for u in collect_tos() if oid in u.split('?')[0] and f"__vid={vid}" in u]
url = max(same, key=br) if same else anchor     # 同 objectid 必为同一内容；缓冲里只有当前档就直接用 anchor

# 4) 立即下载（签名 URL 时效极短；浏览器上下文带会话）
rec = bu.download(url, filename=out_name)
print("oid", oid[:20], "同object档数", len(same), "选br", br(url), rec.get("state"), rec.get("bytes"))
```

> bu.js 内嵌 JS 用朴素写法（`function(){}`、`indexOf`、字符串拼接），避免在里面写正则字面量 / `forEach` 复杂链式，实测个别写法会被 JS 评估器判 `Invalid left-hand side`。

## 下载后校验与转写（多条连下必做）

```bash
# 1) 身份/串流复核：本批所有文件 md5 必须两两唯一；任一相同即串流，删错的重下
for f in *.mp4; do md5 -q "$f"; done | sort | uniq -d     # macOS；有输出=存在重复，需排查
ffprobe -v error -show_entries format=duration -of default=nk=1:nw=1 "<文件>.mp4"   # 时长辅助判别

# 2) 确认含视频流 + 音频流（h264/hevc + aac）
ffprobe -v error -select_streams v:0 -show_entries stream=codec_name,width,height -of csv=p=0 "<文件>.mp4"
ffprobe -v error -select_streams a:0 -show_entries stream=codec_name        -of csv=p=0 "<文件>.mp4"

# 3) 转写（FunASR，自动发现解释器；模型首次运行自动下载，之后离线）
python3 "$SKILL_DIR/scripts/process/funasr_transcribe.py" "<视频>.mp4" "<转写输出父目录>" --lang zh
# 产物：<输出父目录>/<视频文件名>/transcript.md + transcript.json
```

- **转写 / 抽帧是最终内容验证**：md5 唯一只证明"不是上一条"，仍要抽 1–2 帧中后段画面（看硬字幕主题）或读转写，确认名实相符；名不副实（纯引流 / 无干货）在台账记降级，不强行归并。
- FunASR 常见同音错字（如"GIE"应为 GIA、"FL"被识成"FI"、"木佐绿"识成"穆朵绿"），归并知识文档时用正确术语，转写原文保留。

## 防风控（硬性）

- **逐条串行**，严禁循环快刷；每条页面停留 ≥10–20s 模拟真人；单会话 ≤15 条、条间 ≥30s 更稳，建议每天 1–2 批。
- 撞验证码 / 限流 / 滑块：立即停、冷却，不换 UA、不改 cookie、不换号硬刚；需要验证就 `interaction.request_action(type="browserControl")` 交用户。
- 每条完成立即回写台账 / 工单状态（去重基准），中断后续跑不重复下载。

## 已废弃写法留档（不要再用）

- ❌ `"network_requests 里所有 /video/tos 取 br 最高者"`：会选到播放器初始化瞬间挂的**预加载/残留高码率流**（串流，批 2 第 2、6 条曾下错）。
- ❌ `"记录播放前 path 集合、只取播放后新增差集的最高 br"`：差集里同样可能混入预加载流，且 new_tab 隔离也无法避免该污染。
- ❌ `"从 #RENDER_DATA 解析 playAddr"`：SSR 数据里不含播放地址（异步接口下发）。
- ✅ 正解就是上面的 **轮询 `video.currentSrc` 到 `__vid` 匹配 → 同 objectid 取最高 br**。

## 与同目录文档分工

| 文档 | 负责 |
|---|---|
| `douyin-browser-extract.md` | 不下原片，浏览器直读"章节要点"+关键帧 OCR 出文稿（最轻） |
| `douyin-favorites-extract.md` | 登录态遍历收藏 / 关注列表，产出 vid+标题清单 |
| **本篇** | 拿到单条 vid 后，用 currentSrc+`__vid` 铁证法**下载原片 mp4** |
