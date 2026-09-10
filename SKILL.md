---
name: multiplatform-media-fetch
description: 下载 YouTube / 哔哩哔哩(B站/bilibili，支持裸 BV 号) / 抖音(douyin，支持纯数字视频ID) 的音视频，并以“拿到文字、梳理成文章”为默认目标：优先找字幕（多种字幕里中文优先、简中优先于繁中），无字幕则在平台允许时优先下最小尺寸音频做本地离线转写（SenseVoice+FunASR，中/英/日/韩/粤），连音轨都没有才下可被 OCR 的视频（下载的视频默认不自动 OCR）；非中文内容默认翻译成中文，并按视频中作者的角色/身份梳理成文章/博文/逐字稿/主播内容梳理/分段导览；也覆盖**一次给多个同作者/同系列/强相关链接**时的批量探查、按章节取稿与体系化梳理编排（合一篇综述或拆多篇、与已有知识库重新编排）。当用户要“下载/保存/提取某条 YouTube、B站、抖音链接”“只要音频/最小音轨”“把视频转成文字稿/逐字稿/字幕”“无字幕就转写”“转写后翻译成中文”“梳理/总结成文章或博文”“按章节分段转写”时使用。内置三平台防风控策略（代理分流、JS 挑战、匿名票据/Cookie 复用、限速），脚本自动发现本机已装 yt-dlp / FunASR 的 Python 环境，可在任意任务窗口直接运行。暂不涉及剪映等剪辑。
compatibility: "仅在 macOS(Darwin) 实测可用；Windows/Linux 未适配。执行前先判平台(uname -s 返回 Darwin)，非 macOS 停止并告知需另行适配、不硬跑；将来补齐 Windows 后仍按平台分流并分别标注验证状态"
---

# 多平台音视频获取：默认为“出文字、成文章”服务

## 平台适用（执行前先读）
- 本技能当前**仅在 macOS（Darwin）实测可用**，命令、路径、代理端口与系统原生能力均按 Mac。
- 动手前先判平台：`uname -s` 返回 `Darwin` 才走本技能流程；**Windows/Linux 未适配，遇到就停下告知用户“需先做该平台适配”，不要用想当然的等价命令硬跑**。
- 以后补齐 Windows 后也必须保留“先判平台 → 按平台分流”的结构：mac/Windows 的命令与路径分开写、各自标注是否已验证。

三种用法，**单条默认走第一条（出文章流水线）**；一次给多个相关链接走第三条；只做收藏/分享、明确要某个文件时才用第二条原语。

- **A. 出文章（单条，默认）**：`fetch_for_article.py` 一条命令自动决定下什么，再转写/翻译/成文。
- **B. 纯下载原语**：`media_downloader.py` 手动下音频或视频（收藏、微信分享、剪辑素材等）。
- **C. 多链接/同系列**：`batch_fetch.py` 批量探查 + 字幕按章节取稿，再按 `references/series-synthesis.md` 体系化梳理编排。

## 脚本（任意 python3 调用即可，脚本会自动寻找带 yt-dlp/funasr 的解释器重入自身）

- `scripts/fetch_for_article.py`：**单条出文章默认入口**，自动跑下面的决策链并写 manifest。
- `scripts/batch_fetch.py`：**多链接/同系列入口**，批量探查总览 + 字幕按章节切稿（无字幕条目委托回单条流水线）。
- `scripts/media_downloader.py`：下载/列格式/列字幕原语（`--audio --smallest`、`--quality 720`、`--list-subs`、`--subs` 等）。
- `scripts/clean_subtitle.py`：srt/vtt 字幕清洗成纯文本（去时间轴标签、消自动字幕滚动重复）。
- `scripts/transcribe.py`：本地 FunASR 离线转写（整段 / 按章节）。

> 当前 python3 没装 yt-dlp/funasr 也能跑：脚本按 环境变量 → 全局命令 → `~/Doubao/chats` 下各 venv 自动找可用解释器并重入。手动指定用 `YTDLP_PYTHON` / `FUNASR_PYTHON`。

## A. 出文章默认流水线（六条默认行为，按顺序决策）

一条命令：
```bash
python3 "<skill>/scripts/fetch_for_article.py" "<URL或BV号/抖音ID>" -o downloads
```

决策顺序与默认值（**用户没特别说明时严格按此执行，不要一上来就下大视频**）：

1. **字幕优先**：先探测手动+自动字幕，多种字幕里**中文优先（简中 zh-Hans > 繁中 zh-Hant > 英文 en > 其他），同语言手动字幕优先于自动字幕**。命中就**只下字幕、转 srt、自动清洗成纯文本，不再下载任何音视频**（最省）。
2. **无字幕 → 最小音频**：平台有音轨就下**最小尺寸音频**（`worstaudio`，转写够用、最省流量；抖音无独立音轨会自动从合一视频无损抽出 m4a），交给 `transcribe.py` 转写。
3. **连音轨都没有 → 可 OCR 的视频**：才下视频，取**适中清晰度（默认 ≤720p，保证画面文字可识别，不能取最小糊视频）**。
4. **下载得到的视频默认不跑 OCR**：OCR 只是兜底文字来源，不自动执行；确需画面文字时再用 OCR/work-doc-extract 技能，且若视频其实有声，优先改回音频路线。
5. **非中文默认翻译成中文**：字幕语言或转写文本非中文时，默认译为通顺中文（不是硬译，贴合中文同类作者口吻）。
6. **默认按作者角色成文**：分析内容、判断视频里作者的身份（教学/新闻评论/测评/经验分享/访谈口播/宣传带货…），用匹配的结构梳理成文章。方法与模板见 `references/article-pipeline.md`。

可用 `--force subtitle|audio|video` 强制走某条路线（默认 auto），`--ocr-quality` 调兜底视频清晰度上限。每跑一次产出 `fetch-manifest-<id>.json`，写明 `route`(subtitle/audio/video-for-ocr)、产物路径、`need_transcribe`、`need_translate`、下一步。

先看有哪些字幕：`media_downloader.py "<URL>" --list-subs`；只下字幕：`--subs`。

## B. 纯下载原语（收藏 / 分享 / 指定文件时）

```bash
DL="<skill>/scripts/media_downloader.py"
python3 "$DL" "URL" --audio --smallest            # 只要最小音轨（转写/听声）
python3 "$DL" "URL" --quality 720                 # 限清晰度下视频（微信分享常用 720p）
python3 "$DL" "URL" --list-formats                # 先看有哪些清晰度/音轨
python3 "$DL" BV1N64xzKEfA --audio --smallest     # B站裸 BV 号
python3 "$DL" 7681310654023716147 --audio --audio-format mp3   # 抖音纯数字 ID
```
- YouTube 多语言音轨默认锁**原声**、避开 AI 自动配音，要其它音轨加 `--audio-lang en`。
- 下载默认进 `./downloads/`，命名 `标题 [id].扩展名`。

## 转写 / 翻译 / 成文（A 路线的后半段）

```bash
TR="<skill>/scripts/transcribe.py"
python3 "$TR" "downloads/xxx.m4a" transcripts --lang auto         # 整段；日语显式 --lang ja
python3 "$TR" "video.mp4" transcripts --chapters chapters.json    # 按章节分段（元素 {"start","end","title"} 秒）
```
产出 `transcripts/<名>/transcript.md`(可读稿)+`transcript.json`(带时间戳)，章节模式另出 `chapters_raw.md`。语种选择、非中文默认译中文、双语稿、按作者角色成文、FunASR 环境：读 `references/transcribe-and-translate.md` 与 `references/article-pipeline.md`。

## C. 多链接 / 同系列：批量取稿 + 体系化梳理

识别信号：一次给 ≥2 个链接且同作者/同系列/强相关，或用户说"整理到一起、一个体系、重新编排、形成知识库/一篇"。这不是 N 个独立任务，先成体系再动笔：

```bash
BF="<skill>/scripts/batch_fetch.py"
python3 "$BF" "<url1>" "<url2>" "<url3>" -o series-fetch        # 批量探查+字幕按章节切稿+总览
python3 "$BF" "<url1>" ... --with-audio                          # 无字幕条目也自动委托单条流水线取稿
```

- 先看 `series-fetch/series-overview.md`：同作者检测、按上传日期排序的总览、每集语言/字幕/章节/字数，据此判断递进还是并列、有无缺口。
- 有字幕的条目已在 `series-fetch/transcripts/<id>.md` 按**视频自带章节**切好；无字幕的单跑 A 路线补齐。
- 取稿之后的"抽主线、合一篇还是拆多篇、横向去重、与已有知识库交叉重排、**落库时的结构治理（建主题簇/导航页、何时该全量重组）**、事实分级"是 AI 的工作，方法与检查清单读 `references/series-synthesis.md`；多链接内容天然成簇，探查阶段就要预判它将来落到知识库哪一层，不要逐集堆摘要、也不要写完才发现无处安放。

## 三平台默认策略（排错先看这里，细节见 references/platform-strategy.md）

- **YouTube**：自动探测代理端口(7890/7897/1087…)（`MEDIA_FETCH_PROXY`/`--proxy` 指定）+ node/deno/bun 跑 JS 挑战 + ejs 远程组件；被 bot 拦/429 加 `--browser chrome`。
- **B站**：强制直连（走代理会 412），自带 UA/Referer、默认限速 2MiB/s、默认不带 Cookie；撞 412 立即停、冷却，勿反复重试。
- **抖音**：强制直连，默认用匿名设备票据 ttwid（公开视频免登录、免开 Chrome），匿名被拒（Fresh cookies）才回退复用 Chrome 登录态（加 `--browser chrome`）；无独立音轨时 `--audio` 自动抽 m4a。

## 硬性约束与交付检查

- 转写参数（use_itn、VAD 单段≤30s、batch_size_s=60）已在脚本内固定，不要改；**不要装/用 faster-whisper（Intel CPU 过慢，已弃用）**，统一 FunASR SenseVoiceSmall+fsmn-vad。
- 日语音频必须 `--lang ja`（auto/zh 偶发误判）。
- 出文章默认顺序不可颠倒：能字幕就不下载媒体，能音频就不下视频，视频默认不 OCR，非中文默认译中文。
- 完成后核对：字幕清洗稿/转写稿字数与时长相称（中文口播约每分钟 250–320 字）、音频可播放、manifest 的 route 与实际产物一致；再按作者角色成文。
- 多链接/同系列：先 `batch_fetch.py` 出总览、补齐缺口再动笔，按 `references/series-synthesis.md` 做体系化编排，不逐集堆摘要。
- 平台风控、多音轨选流、微信封装、yt-dlp 升级等进阶问题读 `references/platform-strategy.md`。
