# 参考文档目录（references）

本目录是各功能的详细说明文档，按功能分类：

---

## 一、平台相关（platforms/）
各平台的采集策略、风控、专用方案

| 文档 | 用途 |
|---|---|
| `platforms/platform-strategy.md` | 各平台总览（网络/Cookie/风控对照表） |
| `platforms/bilibili-up-listing.md` | B站UP主列表采集 |
| `platforms/douyin-browser-extract.md` | 抖音浏览器直读方案（被风控时的兜底） |
| `platforms/douyin-favorites-extract.md` | 抖音收藏采集 |
| `platforms/xiaohongshu.md` | 小红书平台说明 |
| `platforms/tencent-vod-simpleaes.md` | 腾讯VOD加密说明 |
| `platforms/live-stream-record.md` | HLS直播录制 |

---

## 二、内容处理相关（process/）
转写、OCR、效果分析的详细说明

| 文档 | 用途 |
|---|---|
| `process/transcribe-and-translate.md` | 语音转写与翻译详细说明 |
| `process/video-screen-ocr.md` | 视频画面OCR详细说明 |
| `process/video-effect-analysis.md` | 视频效果分析（运镜/情绪/提示词） |

---

## 三、流水线相关（pipeline/）
完整流程的SOP和编排方法

| 文档 | 用途 |
|---|---|
| `pipeline/article-pipeline.md` | 单条出文章流水线 |
| `pipeline/series-synthesis.md` | 同系列视频体系化编排方法 |
| `pipeline/author-video-knowledge-base.md` | 作者全量知识库构建6步SOP |

---

## 四、行业插件（domain-plugins/）
不同行业的知识提取维度模板

> 详细说明见 [domain-plugins/README.md](domain-plugins/README.md)
> 目前支持：珠宝鉴赏类、视频创作/生成类
