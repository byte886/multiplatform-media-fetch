# 转写与翻译工作流

> 被 `../SKILL.md` 按需引用：选语种、按章节转写、把转写稿翻译成中文/双语、或需要自建 FunASR 环境时读这里。

## 目录
1. 环境与自举（FunASR 在哪、找不到怎么办）
2. 整段转写 vs 按章节转写
3. 语种怎么选
4. 翻译怎么做（转写不翻译，翻译由模型完成）
5. 转写稿常见同音错字校正
6. 性能参考
7. 批量/并行转写（扩展位：何时做、项目参考在哪）

## 1. 环境与自举
- 方案：FunASR 1.4.3 + 模型 `iic/SenseVoiceSmall` + VAD `fsmn-vad`，后端 torch，**本地 CPU 离线、0 成本、数据不出本机**。
- `transcribe.py` 会自动发现一个“能 import funasr 的 Python”：环境变量 `FUNASR_PYTHON` → `~/Doubao/chats/**/transcription/venv` → PATH 的 python3。
- 固定锁版本（macOS x86 实测）：`torch==2.2.2`、`numpy<2`、`funasr==1.4.3`、`modelscope`；模型首次运行自动下载到 `~/.cache/modelscope/models/`，之后离线可用。
- 全新环境自建（一般不需要，本机已有现成 venv）：
  ```bash
  python3 -m venv venv
  venv/bin/pip install "torch==2.2.2" "numpy<2" "funasr==1.4.3" modelscope
  # 然后用 FUNASR_PYTHON 指向 venv/bin/python
  ```
- 前置：`ffmpeg/ffprobe` 在 PATH（脚本内部自动把任意音视频转 16kHz 单声道 wav，无需手动转）。
- **不要**改装 faster-whisper / openai-whisper：Intel CPU 上约 1x 实时，过慢，已永久弃用。

## 2. 整段 vs 按章节

> 输入形态：纯音频或视频文件都可以，脚本内部统一用 ffmpeg 转 16kHz 单声道 wav，二者等价、**无需先手动抽轨**。抖音这类没有独立音轨的平台，推荐先用 `media_downloader.py --audio --smallest` 自动抽出最小 m4a（比直接下 mp4 省流量，见 platform-strategy.md 抖音音频段）；已有 mp4 也能直接喂。

- **整段**（默认）：`python3 transcribe.py <音视频> [输出目录] --lang auto`
  产出 `transcripts/<名>/transcript.md`（按语义≤500字段落）+ `transcript.json`。适合大多数“整个转成文字稿”。
- **按章节精确分段**：用户给了时间点/平台自带章节时用，模型只加载一次、按边界逐段识别，章节与时间精确对齐：
  ```bash
  python3 transcribe.py video.mp4 transcripts --chapters chapters.json --lang zh
  # chapters.json 元素：{"start": 0, "end": 141, "title": "开场"}，时间单位秒
  ```
  产出 `chapters.json`（每章带 text）+ `chapters_raw.md`，适合“分段导览/每章摘要”。
- 断点续跑：整段结果已存在且 >100 字节、章节结果已存在时会自动跳过。

## 3. 语种怎么选
`--lang` 支持 `auto / zh / ja / en / ko / yue`（粤语）。
- 中文课程/口播：`zh`（或 auto）。
- **日语内容必须显式 `ja`**——用 zh 转日语会乱码；auto 偶尔误判，明确是日语就直接 ja。
- 英语/韩语对应 en/ko；多语种混杂用 auto。
- 转写参数 `use_itn=True`（数字标点规范化）、VAD 单段≤30s、`batch_size_s=60` 已在脚本内固定，不要改。

## 4. 翻译怎么做
> 默认行为：内容非中文时**默认翻译成中文**；最终如何按视频作者角色梳理成文章，见 `article-pipeline.md`（本文件只讲转写与翻译这两道工序）。

SenseVoice 只把“语音转成对应语言的文字”，**不负责翻译**。要译文由你（模型）在拿到 `transcript.md`（或字幕清洗稿）后完成：

1. 先通读转写稿，校正语音同音错字（见第 5 节），再翻译，避免错译。
2. 按用户要的风格产出：
   - **要中文理解**：写成通顺中文，不逐字硬翻；若是视频/口播，允许用目标受众习惯的表达（如中文主播口吻），专有名词首次出现保留原文并括注。
   - **要双语对照**：逐段“原文 + 译文”，段落与 transcript 的“第 N 段”对齐，便于回查时间位置。
   - **要字幕**：基于时间信息生成 srt/vtt（章节 json 带秒级边界；整段 json 只有分段、无逐字时间轴，需要精确字幕时改用按章节模式或外部对齐）。
3. 译文单独成文件（如 `译文-<名>.md` / `双语对照-<名>.md`），不要覆盖原始 transcript，原始稿留作溯源。
4. 专业术语、数字、人名地名要与画面/讲义一致，不确定处标注“（此处听存疑）”，不要编造。

## 5. 中文转写常见同音错字（校正时优先排查）
语音识别常把术语识别成同音词，梳理/翻译前先改：
- “跟仓/根仓”→根仓库/主仓库；“AGMD”→AGENTS.md；“托肯”→token
- “换觉率”→幻觉率；“讲罚”→奖惩；“史山”→屎山；“注册量”→注释量
- “结耦”→解耦；“竞争值/净增值”→净增量；“A景/agnt/ent化”→Agent/Agent 化；“dops”→DevOps
- 通用做法：结合上下文与领域常识判断，数字/英文缩写回听或对照画面确认。

## 6. 性能参考（Intel i5-13600KF，纯 CPU）
- VAD 加速后约 15x 实时：10 分钟音频约 35~40 秒，2.5 小时视频约 10 分钟；模型加载 3~4 秒（章节模式只加载一次）。
- 长视频转写用后台任务跑并轮询，避免前台超时；并发数按 CPU 核数调整。

## 7. 批量 / 并行转写（扩展位，当前不做通用脚本）
- **已覆盖的批量**：多链接"下载 → 取字幕/无字幕转写 → 成文"走 `fetch_for_article.py` / `batch_fetch.py`；单条整段或按章节走 `transcribe.py`，都已断点跳过。
- **当前刻意不做**：与具体项目无关的"给一个本地音频文件夹做批量/并行 ASR"的通用脚本（如 `transcribe_batch.py`）——没有重复出现的真实需求前不预先写，避免僵尸代码。
- **项目参考实现（高顿课程，强耦合，勿直接拷）**：`~/Doubao/chats/2026-08-26/new-chat/gaodun-course-knowledge-base/` 下 `scripts/transcribe_parallel.sh`、`transcribe_all.sh`、`transcribe_pipeline.py`（按 `GAODUN_COURSE_PROFILE` 转整门课、iTerm 多窗口并行、汇总报告）；方法与性能见该项目 `docs/development/tools/transcription.md`，选型见 `docs/project-management/decisions/ADR-003-音频转写方案.md`。它们绑定课程目录/profile，留项目内，不搬进本技能。
- **何时提炼、怎么提炼**：当出现"脱离任何项目、对一批本地音视频统一离线转写"的真实需求时，再新增 `scripts/transcribe_batch.py`——复用 `transcribe.py` 的单条能力（不重写模型加载/后处理），只加目录遍历、有限并行（按 CPU 核数）、断点跳过与汇总；启用前先拿 3~5 条小样本实测通过再放量。
