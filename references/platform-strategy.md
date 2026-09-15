# 平台防风控策略与进阶处理

> 本文件被 `../SKILL.md` 按需引用：遇到平台拦截、多音轨、微信封装、yt-dlp 升级时读这里。

## 目录
1. 三平台网络/Cookie 策略对照
2. 常见报错与处理（含抖音 Fresh cookies、B站 412、YouTube bot 拦截）
3. yt-dlp 版本与升级
4. 多音轨选流（同 itag 多语言）
5. 微信分享封装 ffmpeg 配方
6. 代理与浏览器 Cookie 手动指定

## 1. 三平台策略对照

| 维度 | YouTube | 哔哩哔哩 | 抖音 |
|---|---|---|---|
| 网络 | **必须走代理**，自动探测 7890/7897/1087/1080/8889 | **必须直连**（代理出口触发 412） | **必须直连** |
| JS 挑战 | 需要 node/deno/bun 运行时 + `ejs:github` 远程组件 | 不需要 | 不需要 |
| Cookie | 默认不带；被拦再加 `--browser chrome` | 默认不带（保护账号）；大会员清晰度才带 | **默认匿名设备票据 ttwid（免登录、免开 Chrome）**，匿名被拒自动回退 Chrome 登录态 |
| 限速/间隔 | 一般不需要 | 请求间隔 2s、文件间 3~8s、默认限速 2MiB/s | 温和间隔 |
| 输入形式 | 完整链接 / youtu.be 短链 | 完整链接 / **裸 BV 号** | 完整链接 / **纯数字视频 ID** |

## 2. 常见报错与处理

### 抖音：`Fresh cookies (not necessarily logged in) are needed` / web detail JSON 空 / 403
**关键认知**：报错里的 "not necessarily logged in" 说明抖音要的是**新鲜设备票据 ttwid，不是登录态**。2026-09-07 实测：仅一枚匿名 ttwid（不登录、不读 Chrome）即可拉取公开视频全部格式。脚本已内置三级 Cookie 策略，正常无需人工：
1. **默认＝匿名 ttwid 优先**：首次自动向 `ttwid.bytedance.com/ttwid/union/register/` 匿名注册 ttwid（约一年有效），缓存到系统临时目录 `.mediafetch_douyin_ttwid.txt`（权限 600，仅匿名设备票据、非账号凭据，30 天主动刷新），公开视频直接下载，**不打开/不读取 Chrome**。
2. **匿名被拒→自动回退 Chrome**：匿名票据被风控或该视频需登录时，自动改用 `cookiesfrombrowser=chrome` 复用登录态重试一次（全程自动，仅这步读 Chrome）。实现注意：`ignoreerrors='only_download'` 会把解析错误转成返回码而不抛异常，匿名首试必须临时设 `ignoreerrors=False` 才能捕获并回退。
3. **仍失败才人工兜底**（少见）：① 升预发布版 `HTTPS_PROXY=http://127.0.0.1:${PROXY_PORT:-7890} python3 -m pip install -U --pre yt-dlp -i https://pypi.org/simple`（官方源走代理）；② 在 Chrome 打开该视频页、确认登录并刷新一次再跑；多配置用 `--browser-profile "Profile 1"`，或扩展导出 Netscape `cookies.txt` 后 `--cookies cookies.txt`（最稳）。

**手动开关**：`--no-browser-cookies`＝只用匿名 ttwid、绝不读 Chrome（拉不动就报错、不回退）；`--browser chrome`＝强制登录态；`--cookies f`＝用自带文件。
**消不掉的人工**：私密/关注可见/会员内容、滑块或设备校验属抖音安全机制，匿名票据无法替代，仍需本人登录一次。

### 抖音音频：没有独立音轨，`--audio` 自动抽轨（2026-09-07 实测沉淀）
- **现象/根因**：想"只下音频"，结果得到音视频合一 `.mp4`，看起来像"音频没法自动化"。实测 `--list-formats`：抖音 web detail API 只给音视频合一 mp4（h264/h265 + aac），**没有任何 audio-only 流**，`bestaudio` 匹配不到纯音轨，只能落到合一流；若不挂后处理就直接留下 mp4。
- **已内置修复（无需手动 ffmpeg）**：`--audio` 时对抖音自动挂 `FFmpegExtractAudio`，把合一流里的 aac **无损 remux 成 m4a（流复制、不重编码）**并删除中间 mp4；`--audio --smallest` 再按 `filesize→tbr→res` 选**体积最小的含音频流**。实测同一视频：540p h265 约 11.7MiB，比 720p 水印流约 38MiB 省约 2/3 下载量，而抽出的是同一条 aac 音轨、结果等价（11 分钟视频抽出 m4a，ffprobe 仅 audio/aac、无视频流）。
- 要 mp3/wav：显式 `--audio-format mp3`；抽轨依赖 ffmpeg（缺失会明确报错退出，macOS：`brew install ffmpeg`）。
- **转写两条路等价**：喂自动抽出的 m4a，或直接把 mp4 交给 `transcribe.py`（内部 ffmpeg 抽轨）都行；批量转写推荐先 `--audio --smallest` 拿 m4a，省下载流量与时间。
- **排错（改脚本时注意）**：不要用 `worst` 这类"锁死单项"的选择器再指望 `format_sort` 按体积排序——候选只剩一个时排序无意义（会选到分辨率低但体积更大的水印流）。正确做法是 `worstaudio/[acodec!=none]` 先取出"所有含音频流"候选，再用 `format_sort=+filesize_approx,+filesize,+tbr,+res` 取最小。

### B站：竖屏视频别用 `[height<=720]` 选清晰度（2026-09-11 实测）
竖屏 720p 的帧尺寸是 **720×1280（高>宽）**。用 `bestvideo[height<=720]` 会因 height=1280 不达标，**错选到 360p（640×360）**，体积只有正确档的 1/3 左右；而 yt-dlp 过滤器不支持字段间比较，写 `[width>=height]` 会直接语法错。
正解是用 format_sort 的 **`res`（=min(宽,高)，较短边）封顶**：`-f 'bv*+ba/b' -S 'res:720'`——横竖屏都按"较短边=720"选中正确档（实测竖屏选 720×1280、`res:1080` 选 1080×1920）。`media_downloader.py` 的整数 quality 分支已统一改成 `format_sort=[res:Q,...]`，调用方无需手动处理；横屏行为同样正确。

### B站：HTTP 412 / 429
临时限流，不是封号。脚本遇到会立即退出（退出码 14）并打印指引：
- 立刻停止，冷却 10~30 分钟（严重时数小时），期间勿反复重试，否则会从 IP 限流升级为账号风控；
- 确认代理软件为 `bilibili.com` 配了直连规则（脚本本身已强制直连）；
- 公开音视频不要加 `--browser`；
- 可用 `--limit-rate 1024` 进一步降速。
- **要列某 UP 主"全部投稿/合集"**（不是单条 BV）属于另一类高风控的"列表翻页"接口，完整方法见 [`bilibili-up-listing.md`](bilibili-up-listing.md)：finger/spi 设备指纹、wbi 签名、动态流翻页必备的 `dm_*` 指纹参数、软限流（返回空 items）识别与冷却、断点续拉。

### YouTube：bot 验证 / Sign in to confirm / 429
- 确认代理可用（自动探测失败就 `--proxy http://127.0.0.1:${PROXY_PORT:-7890}`（端口以实测为准）或设 `MEDIA_FETCH_PROXY`）；
- 确认装了 node（`which node`），缺 JS 运行时会被风控；
- 仍被拦加 `--browser chrome` 复用浏览器登录态；
- 地区/年龄限制视频同样靠 `--browser chrome`。

## 3. yt-dlp 版本与升级
- 脚本通过 Python API 调用，要求运行解释器装了 yt-dlp（自举逻辑会自动找）。
- 稳定版追平平台风控较慢，抖音/YouTube 出怪问题时优先试 `--pre` 预发布版。
- 查版本：`yt-dlp --version` 或 `python3 -c "import yt_dlp;print(yt_dlp.version.__version__)"`。

## 4. 多音轨选流（YouTube 原声 vs AI 自动配音）

### 现象（2026-09-07 实测踩坑）
带多语言 AI 配音的 YouTube 视频，同一 itag 会生成多条音轨，`format_id` 用 `-序号` 区分：
- `xxx-1` = `original (default)` 视频原声（例：zh-Hant 中文原声）；
- `xxx-0` = AI 自动配音（例：en-US，`format_note` 往往只写 "English (US)"、**不一定出现 dubbed 字样**）。

早期 `--audio --smallest` 只按体积/码率挑最小，会误中 `-0` 英文配音，结果转写整段变成英文、英文术语全错（如 show-me 被识别成 SHME）。

### 脚本已内置：默认锁原声，无需手动选
`--audio`（含 `--smallest`）下载 YouTube 前会先探一次格式，按「原声 original(default) 优先、无原声标注的自动配音靠后」排序，同档内再按 smallest/质量挑，并**打印全部候选音轨与选中原因**；探测失败自动回退通用选流、不阻断下载。
```bash
python3 media_downloader.py "URL" --audio --smallest        # 默认选 original 原声（转写用这个）
python3 media_downloader.py "URL" --audio --audio-lang en   # 显式要英文自动配音
python3 media_downloader.py "URL" --list-formats            # 只查看全部音轨与语言标注
```
实测同一视频 10 条音轨（5 条 zh-Hant 原声 + 5 条 en-US 配音）：默认选中其中最省流量的中文原声 `139-1`，`--audio-lang en` 改选 `249-0`。判定靠"original(default) 强标注"，不依赖 note 一定含 dub。

### 手动兜底（绕过脚本、直接用全局 yt-dlp 时）
按 id 后缀精确指定，配合本表第 1 节的代理/Cookie 策略：
```bash
yt-dlp -f "136+140-1" "URL"     # 画面 + 140-1 中文原声，避开 140-0 英文配音
```
> 「原声优选」目前只作用于 `--audio` 音频路径；下视频（`bestvideo+bestaudio`）若也遇到多配音，先 `--list-formats` 看 id 再用 `-f` 手动指定。

## 5. 微信分享封装 ffmpeg 配方
目标：微信“以文件发送”不被二次压缩、手机端可直接播放。规格：**MP4 / H.264(avc1) / AAC / ≤720p / faststart（moov 在 mdat 前）**。

```bash
# 流复制合并（无二次压缩、最快）：下载到的画面/音频本身就是目标编码时用
ffmpeg -i video.mp4 -i audio.m4a -c copy -movflags +faststart out.mp4

# 需要降清晰度/统一编码时重编码（CRF 20 画质/体积均衡）
ffmpeg -i in.mp4 -vf "scale='min(1280,iw)':-2" -c:v libx264 -crf 20 \
       -c:a aac -b:a 128k -movflags +faststart out-720p.mp4

# 帧精确切亮点片段（-ss/-to 放在 -i 前为输入定位；要帧精确就重编码，别 -c copy）
ffmpeg -ss 740 -to 793 -i in.mp4 -c:v libx264 -crf 20 -c:a aac -b:a 128k \
       -movflags +faststart highlight.mp4
```
校验 faststart（moov 偏移必须小于 mdat）：
```bash
# 输出里 moov 的字节偏移应出现在 mdat 之前
ffmpeg -v trace -i out.mp4 2>&1 | grep -E "moov|mdat" | head
```

## 6. 手动指定代理 / Cookie / 解释器
- 代理：`--proxy http://host:port`，或环境变量 `MEDIA_FETCH_PROXY`；强制直连 `--no-proxy`。
- 下载解释器：环境变量 `YTDLP_PYTHON=/path/to/python`；转写解释器：`FUNASR_PYTHON`。
- Cookie 优先级：`--cookies file` > `--browser 浏览器 [--browser-profile 配置]` > 平台默认。
