# 脚本目录（scripts）

> 按功能科学分类，每个子目录对应一类功能。

---

## 一、下载类（download/）
从各平台下载视频/音频/正文

| 脚本路径 | 用途 |
|---|---|
| `download/media_downloader.py` | 跨平台（基于yt-dlp）：媒体下载原语（视频/音频/字幕） |
| `download/batch_series_fetch.py` | 跨平台（基于yt-dlp）：多链接/同系列批量取稿（批量探查元信息+下字幕+按章节切稿+生成系列总览） |
| `download/fetch_for_article.py` | 跨平台（基于yt-dlp）：单条视频默认入口（自动决策下字幕/最小音频/可OCR视频，最终得到文字稿） |
| `download/download_tencent_vod_encrypted.sh` | 平台专用：腾讯云VOD加密视频一键下载（编号课堂） |
| `download/download_tencent_vod.py` | 平台专用：腾讯VOD下载 |
| `download/xiaohongshu/xiaohongshu_downloader.py` | 平台专用：小红书专用下载（Playwright浏览器直读，yt-dlp不支持） |

> 注：跨平台=基于yt-dlp，支持主流平台：
> - 海外：YouTube、TikTok、Instagram、Twitter/X、Facebook等
> - 国内：B站、抖音、小红书（yt-dlp内置支持，但本技能另写了专用脚本因为内置提取器坏了）、西瓜视频、优酷、腾讯视频等
> - 完整支持列表见 yt-dlp 官方文档（1000+站点）
> 
> 新平台接入时先试yt-dlp，不支持/被风控再写专用脚本。

---

## 二、内容处理类（process/）
把下载的媒体变成可搜索的文字（**全部通用，不针对特定平台**）

| 脚本路径 | 用途 |
|---|---|
| `process/funasr_transcribe.py` | FunASR本地离线语音转文字（支持中文/英文/日文等） |
| `process/macos_vision_ocr_pipeline.py` | 视频画面OCR（ffmpeg抽帧→dHash去重→macOS Vision OCR→带时间戳Markdown） |
| `process/opencv_keyframe_extractor.py` | 智能关键帧抽取（ffmpeg镜头检测→OpenCV清晰度评分→dHash去重） |
| `process/clean_subtitle.py` | srt/vtt字幕清洗成纯文本（去时间轴、消自动字幕滚动重复） |

> 注：以上所有脚本都是通用工具，处理任何平台下载的音视频/字幕/图片，不绑定特定平台。

---

## 三、CDP浏览器自动化类（cdp/）
通过Chrome DevTools Protocol提取视频流、处理弹窗（**通用，不针对特定平台**）

| 脚本路径 | 用途 | 备注 |
|---|---|---|
| `cdp/cdp_extract_live_m3u8.js` | 通用：通过CDP提取HLS直播/点播m3u8地址 | 主工具 |
| `cdp/cdp_extract_tencent_vod.js` | 平台专用：提取腾讯云SimpleAES加密解密参数 | 主工具（腾讯） |
| `cdp/press_chrome_debug_allow.applescript` | 实际执行：点掉Chrome"允许远程调试"弹窗 | 底层，一般不直接调 |
| `cdp/press_chrome_debug_allow_locked.sh` | 带跨进程锁的点弹窗包装 | 入口，直接调这个就行 |

---

## 四、直播类（live/）
HLS直播录制

| 脚本路径 | 用途 |
|---|---|
| `live/record_live.sh` | 无加密HLS直播流录制（支持大多数网页直播，不支持DRM加密直播） |

> 适用范围：
> - 支持：网页端无加密的HLS直播（B站、抖音、YouTube等公开直播）
> - 不支持：有DRM/ SimpleAES加密的直播（加密直播走CDP提取专用脚本）
