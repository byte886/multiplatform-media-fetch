# 视频屏幕文字 OCR 流水线

## 什么时候用

视频里有**只存在于画面上、语音没说出来**的关键信息，需要系统提取：
- ComfyUI/PS 等软件界面上的模型文件名、参数、节点设置
- PPT 上的文字（如果语音转写已经覆盖就不用 OCR）
- 提示词文本框、代码、表格、数据图表
- 教程中老师打开的文件、文件夹、菜单

**不要用的情况**：
- 视频主要靠语音讲解，画面只是辅助 → 只用语音转写
- 画面上没有重要文字（只是人脸、风景）→ 不用 OCR
- 已经有字幕/字幕文件 → 不用 OCR

## 流水线

```
视频文件
  → ① ffmpeg 定时抽帧（每 10 秒 1 帧，缩放到 1280 宽）
  → ② dHash 感知哈希去重（连续相似帧只留一张）
  → ③ macOS Vision OCR 批量识别唯一帧
  → ④ 输出带时间戳的 Markdown，grep 关键词定位
```

## 一键命令

```bash
SKILL_DIR="$HOME/Doubao/skills/multiplatform-media-fetch"
python3 "$SKILL_DIR/scripts/video_ocr_pipeline.py" "video.mp4" -o output_ocr.md
```

参数：
- `--interval 10`：抽帧间隔（秒）。教程类 10s 足够；快速操作/代码演示用 5s；PPT 类用 15-30s
- `--hash-threshold 15`：dHash 去重阈值。画面变化大就调小（5-10），PPT 静止画面多就调大（20-30）

## 依赖

- ffmpeg
- Python: `pip install imagehash Pillow`
- macOS: swift + `work-doc-extract/scripts/ocr_vision.swift`

## 工作流程建议

1. **先跑语音转写**（FunASR），拿到全文 transcript
2. **再跑本脚本**，对视频做系统 OCR
3. **grep OCR 结果**找关键词（`.safetensors`、`.json`、`步数`、分辨率数字等）
4. **对 OCR 识别不清的关键帧**，直接用 `Read` 工具看图（Vision OCR 对小字不如人眼/VLM）
5. 结合 transcript + OCR 结果写总结

## 已知限制

- macOS Vision OCR 对 ComfyUI/PS 等软件的**小字号界面文字识别一般**，大标题/PPT 识别好
- OCR 结果中有错别字（如"细节增强"识别成"细节婚强"），需要 grep 时用模糊匹配
- 4 小时视频约 1440 帧 → 去重后 400-600 帧 → OCR 约 15-20 分钟
- 如果需要更高精度，可对关键帧用 `Read` 工具直接视觉阅读（多模态）

## 与 article-pipeline 的关系

`article-pipeline.md` 第 6 节"视频默认不 OCR"说的就是这个流程：
- 默认走字幕 → 音频转写，不下视频
- 只有当关键信息确实只在画面上、且语音转写覆盖不到时，才用本脚本补 OCR
- 本脚本是"兜底"，不是默认步骤
