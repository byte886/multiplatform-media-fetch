---
name: multiplatform-media-fetch
description: 多平台音视频采集与文字化处理。支持YouTube/B站/抖音/小红书/腾讯VOD加密站，核心能力：单条视频下载与文字提取（字幕/转写/OCR/翻译/成文）、多链接批量取稿与体系化编排、编号课堂等加密站专用下载。
compatibility: 仅 macOS(Darwin) 实测；Windows/Linux 未适配
---

# 多平台音视频采集与文字化处理

> 支持YouTube/B站/抖音/小红书/腾讯VOD加密站等平台，覆盖下载、转写、OCR、批量取稿、建知识库等场景。**详细场景→服务映射见下文表格。**

---

## 执行原则（AI执行前必读）
- **浏览器**：所有需要开浏览器的采集/调试，统一走**外部Google Chrome**，不用Doubao内置浏览器（登录态不共享，会互相挤掉）

---

## 三种用法（按场景选）
| 场景 | 用法 | 入口脚本 |
|---|---|---|
| 单条视频，要文字/文章 | A. 出文章（默认） | `fetch_for_article.py` |
| 只要视频/音频文件（收藏/分享） | B. 纯下载原语 | `media_downloader.py` |
| 多链接同作者/同系列 | C. 批量取稿+体系化编排 | `batch_series_fetch.py` |

## 脚本（按功能分组）

> 下文命令统一先设 `SKILL_DIR`＝本技能实际安装目录。**不写死单一位置**：同一套技能可能安装在 `~/Doubao/skills`、`~/DoubaoWork/skills` 或其它 clone/软链共享路径，一律以技能加载返回的实际路径为准。

### 下载类（download/）
| 脚本 | 用途 |
|---|---|
| `scripts/download/fetch_for_article.py` | **单条出文章默认入口**，自动决策下字幕/音频/视频 |
| `scripts/download/batch_series_fetch.py` | **多链接/同系列入口**，批量探查+按章节切稿 |
| `scripts/download/media_downloader.py` | 通用下载原语（列格式/列字幕/手动下载） |

### 内容处理类（process/）
| 脚本 | 用途 |
|---|---|
| `scripts/process/funasr_transcribe.py` | FunASR离线语音转文字 |
| `scripts/process/macos_vision_ocr_pipeline.py` | 视频画面OCR |
| `scripts/process/opencv_keyframe_extractor.py` | 智能关键帧抽取 |
| `scripts/process/clean_subtitle.py` | srt/vtt字幕清洗 |

> 当前 python3 没装 yt-dlp/funasr 也能跑：脚本按 环境变量 → 全局命令 → `~/Doubao/chats` 下各 venv 自动找可用解释器并重入。手动指定用 `YTDLP_PYTHON` / `FUNASR_PYTHON`。

---

## 场景→服务映射（按用户需求选对应功能）

### 一、下载类
| 用户需求 | 对应服务 | 入口 |
|---|---|---|
| 只要视频/音频文件（收藏/分享/剪辑素材） | 通用下载（YouTube/B站/抖音等） | `media_downloader.py` |
| 小红书笔记/视频下载 | 小红书专用（yt-dlp内置提取器坏了） | 读 `references/platforms/xiaohongshu.md` |
| 编号课堂/腾讯VOD加密站下载 | 加密站专用（直下不通） | 读 `references/platforms/tencent-vod-simpleaes.md` |
| HLS直播录制 | 直播流录制 | 读 `references/platforms/live-stream-record.md` |

### 二、文字提取类
| 用户需求 | 对应服务 | 入口 |
|---|---|---|
| 单条视频，要文字/文章/笔记 | 出文章流水线（自动决策字幕/音频/视频） | `fetch_for_article.py` |
| 已有音频/视频，直接转写成文字 | 语音转写（FunASR） | `funasr_transcribe.py` |
| 已有视频，要提取画面里的文字（界面/PPT/代码） | 视频画面OCR | `macos_vision_ocr_pipeline.py` |
| 已有srt/vtt字幕文件，清洗成纯文本 | 字幕清洗 | `clean_subtitle.py` |

### 三、分析类
| 用户需求 | 对应服务 | 入口 |
|---|---|---|
| 视频要分析运镜/情绪/镜头语言（生成视频参考） | 视频效果分析 | 读 `references/process/video-effect-analysis.md` |
| 已有视频，要抽关键帧（做素材/截图） | 智能关键帧抽取 | `opencv_keyframe_extractor.py` |

### 四、批量/知识库类
| 用户需求 | 对应服务 | 入口 |
|---|---|---|
| 多链接同作者/同系列，要整理成体系/知识库 | 批量取稿+体系化编排 | `batch_series_fetch.py` |
| 下载某个UP主全部视频，筛选有价值的建知识库 | 作者全量知识库（6步流水线） | 读 `references/pipeline/author-video-knowledge-base.md` |
| B站UP主全部投稿采集 | B站专用（游客Chrome翻页） | 读 `references/platforms/bilibili-up-listing.md` |
| 抖音收藏/关注列表采集 | 抖音专用（登录态，低频防风控） | 读 `references/platforms/douyin-favorites-extract.md` |

---

## A. 出文章默认流水线（六条默认行为，按顺序决策）

一条命令：
```bash
python3 "$SKILL_DIR/scripts/download/fetch_for_article.py" "<URL或BV号/抖音ID>" -o downloads
```

决策顺序与默认值（**用户没特别说明时严格按此执行，不要一上来就下大视频**）：

1. **字幕优先**：先探测手动+自动字幕，多种字幕里**中文优先（简中 zh-Hans > 繁中 zh-Hant > 英文 en > 其他），同语言手动字幕优先于自动字幕**。命中就**只下字幕、转 srt、自动清洗成纯文本，不再下载任何音视频**（最省）。
2. **无字幕 → 最小音频**：平台有音轨就下**最小尺寸音频**（`worstaudio`，转写够用、最省流量；抖音无独立音轨会自动从合一视频无损抽出 m4a），交给 `scripts/process/funasr_transcribe.py` 转写。
3. **连音轨都没有 → 可 OCR 的视频**：才下视频，取**适中清晰度（默认 ≤720p，保证画面文字可识别，不能取最小糊视频）**。
4. **下载得到的视频默认不跑 OCR**：OCR 只是兜底文字来源，不自动执行；确需画面文字时跑 `scripts/process/macos_vision_ocr_pipeline.py`（详见 `references/process/video-screen-ocr.md`），且若视频其实有声，优先改回音频路线。
5. **非中文默认翻译成中文**：字幕语言或转写文本非中文时，默认译为通顺中文（不是硬译，贴合中文同类作者口吻）。
6. **默认按作者角色成文**：分析内容、判断视频里作者的身份（教学/新闻评论/测评/经验分享/访谈口播/宣传带货…），用匹配的结构梳理成文章。方法与模板见 `references/pipeline/article-pipeline.md`。

可用 `--force subtitle|audio|video` 强制走某条路线（默认 auto），`--ocr-quality` 调兜底视频清晰度上限。每跑一次产出 `fetch-manifest-<id>.json`，写明 `route`(subtitle/audio/video-for-ocr)、产物路径、`need_transcribe`、`need_translate`、下一步。

先看有哪些字幕：`scripts/download/media_downloader.py "<URL>" --list-subs`；只下字幕：`--subs`。

## B. 纯下载原语（收藏/分享/指定文件时）
```bash
python3 "$SKILL_DIR/scripts/download/media_downloader.py" "URL" --audio --smallest
```
详细参数（列格式、限清晰度、下字幕等）：`python3 media_downloader.py --help` 或读 `references/platforms/platform-strategy.md`

## 转写/翻译/成文（A路线后半段）
```bash
python3 "$SKILL_DIR/scripts/process/funasr_transcribe.py" "audio.m4a" transcripts --lang auto
```
详细参数（按章节分段、双语稿、FunASR环境）：读 `references/process/transcribe-and-translate.md` 与 `references/pipeline/article-pipeline.md`

## C. 多链接/同系列（批量取稿+体系化编排）
识别信号：≥2个链接同作者/同系列，或用户说"整理到一起/形成知识库"
```bash
python3 "$SKILL_DIR/scripts/download/batch_series_fetch.py" "<url1>" "<url2>" -o series-fetch
```
详细流程（系列总览、按章节切稿、体系化编排）：读 `references/pipeline/series-synthesis.md`

## 效果分析（效果呈现类视频，2026-10-05 新增）

价值在"呈现效果/情绪/镜头语言"的视频（活人感教程、胶片旅拍、广告级成片、短剧片段）**只出文字不够**：内容层（字幕/音频/OCR）照旧拿文稿，**画面层**另做效果拆解——叙事结构（HOOK→CTA）+ 情绪弧线 + 镜头语言（景别/运镜/转场/光线/色彩质感）+ 分平台可复用提示词。
完整流程与输出模板见 [references/process/video-effect-analysis.md](references/process/video-effect-analysis.md)；画面获取优先下载抽帧，被拒走浏览器直读截图（[references/platforms/douyin-browser-extract.md](references/platforms/douyin-browser-extract.md)）。

## 各平台关键策略（排错先看这里，细节见 references/platforms/platform-strategy.md）

| 平台 | 关键决策点 | 详细文档 |
|---|---|---|
| YouTube | 自动探测代理端口，被拦加 `--browser chrome` | `platforms/platform-strategy.md` |
| B站 | **必须直连**（走代理会412），限速2MiB/s | `platforms/platform-strategy.md` |
| B站UP主全量采集 | 开游客Chrome驱动前端翻页，不要用yt-dlp | `platforms/bilibili-up-listing.md` |
| 抖音 | 匿名ttwid→被拒回退Chrome→再被拒走浏览器直读 | `platforms/douyin-browser-extract.md` |
| 抖音收藏/遍历 | 静默风控，低频（≥30s/条），单会话≤15条 | `platforms/douyin-favorites-extract.md` |
| 小红书 | yt-dlp内置提取器坏了，用专用脚本，严禁批量遍历 | `platforms/xiaohongshu.md` |
| 腾讯VOD加密 | 直下不通，走一键脚本+CDP解密 | `platforms/tencent-vod-simpleaes.md` |
| HLS直播录制 | 无加密m3u8直接录，加密走CDP提取 | `platforms/live-stream-record.md` |

## 行业插件（domain-plugins）
不同行业的知识提取维度不一样，按需读取。

> 详细模板见 [references/domain-plugins/](references/domain-plugins/)
> 目前支持：珠宝鉴赏类、视频创作/生成类

## 硬性约束与交付检查
- **转写参数**：已在脚本内固定，不要改；统一用FunASR，不要用faster-whisper
- **日语音频**：必须加`--lang ja`
- **完成核对**：字数与时长相称（中文约250-320字/分钟）、音频可播放、manifest路由与实际产物一致
- **多链接**：先批量取总览、补齐缺口再动笔，不要逐集堆摘要

## 进阶：作者全量视频知识库构建

当用户需要"下载某个博主/UP主的所有视频，筛选有知识价值的，建立结构化知识库"时，**先读 `references/pipeline/author-video-knowledge-base.md`**。

这不是单条下载，而是完整流水线：
1. 遍历作者主页收集全量视频列表（标题+URL）
2. 按标题自动分类（品类/价值等级/处理需求预判）
3. 生成带状态追踪的Excel清单（增量更新基础）
4. 按人类节奏批量下载防风控
5. 每个视频自动处理：语音转写 + 智能关键帧抽取 + 画面OCR
6. 按行业插件生成结构化知识文档（珠宝/视频创作/编程等）

核心脚本：`scripts/process/opencv_keyframe_extractor.py`（智能抽帧，替代固定10秒抽帧）。
