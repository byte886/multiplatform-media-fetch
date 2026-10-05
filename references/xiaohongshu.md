# 小红书（Xiaohongshu / RedNote）采集策略

> 实测时间：2026-10-05；实测环境：macOS + 系统 Google Chrome + Playwright persistent context。

## 平台特性与反爬

小红书 web 端反爬比 B 站/抖音更重，核心三道门：

1. **xsec_token 门**：裸 `/explore/{note_id}` 不带 `xsec_token` 参数，即使已登录也会被 `300031` 重定向到 `/404`，提示"当前笔记暂时无法浏览"。xsec_token 在从首页/搜索/用户主页点进笔记时由前端自动附加，有时效。
2. **登录门**：未登录时笔记正文图片不渲染，只显示评论区；扫码登录后才完整。
3. **CDN 样式签名门**：图片直链必须带 `!nd_dft_wgth_webp_3` 等样式后缀，去掉后缀 403；视频 mp4 直链带 `sign` 和 `t`（过期时间戳）参数，拿到 URL 后短时间内可无 header 直接下载。

## 技术选型（为什么不用 yt-dlp / 为什么不逆向签名）

- **yt-dlp 2026.08.19 虽内置 XiaoHongShu extractor，但实测坏的**：图文/视频均报 `No video formats found`。
- **Spider_XHS / XHS-Downloader 这类项目逆向了完整签名**（x-s / x-t / x-s-common / b1 / webSsk / x-rap-param），纯 HTTP 不启浏览器，但需要 Node.js 跑 JS 签名，且签名算法跟着小红书版本频繁更新（最近 2026-09-07 还在改），维护成本高。
- **本 skill 选择浏览器直读路线**：用 Playwright persistent context 启动一个独立 profile（cookie 持久化在 `~/.cache/multiplatform-media-fetch/xhs_profile/`），打开笔记页后从 DOM 抓 `notes_pre_post/` 图片、从 `performance.getEntriesByType('resource')` 抓 `sns-video-v6.xhscdn.com` 的 mp4 直链，再用 urllib 下载。直链不需要 cookie/referer。

## 脚本位置与用法

> **浏览器原则**：所有小红书操作统一走**外部 Google Chrome**（`channel="chrome"`，即 `/Applications/Google Chrome.app`），不使用 Doubao 内置 bu 浏览器。cookie 持久化在 `~/.cache/multiplatform-media-fetch/xhs_profile/`。

脚本：`scripts/xhs/xhs_downloader.py`

```bash
PY="/Users/wenjiechen/Library/Application Support/Doubao/sandbox_runtime/bases/e74152cd379ba45d7ca7f16dfa51b727/bin/python3"
# 或任意装了 playwright 的 python3

# 首次：扫码登录（cookie 自动持久化，以后免登）
$PY scripts/xhs/xhs_downloader.py login

# 单条笔记（图文+视频+元数据）
$PY scripts/xhs/xhs_downloader.py note "<带 xsec_token 的笔记 URL>" -o ./downloads

# 评论
$PY scripts/xhs/xhs_downloader.py comments "<笔记 URL>" -o ./downloads

# 搜索关键词（列出笔记列表，不下载详情）
$PY scripts/xhs/xhs_downloader.py search "<关键词>" --max 20 -o ./downloads

# 用户主页全部笔记列表
$PY scripts/xhs/xhs_downloader.py user "<用户主页 URL>" --max 30 -o ./downloads

# 我的收藏列表（登录态私有数据，自动识别当前账号）
$PY scripts/xhs/xhs_downloader.py favorites --max 100 -o ./downloads

# 我的收藏 + 逐条详情（推荐！列表→详情闭环，失效笔记自动标记）
$PY scripts/xhs/xhs_downloader.py favorites --max 100 --with-detail -o ./downloads
```

## 收藏→详情 闭环（2026-10-05 实测沉淀，v6 方案内置）

`favorites --with-detail` 一条命令完成「列表 + 每条详情」，详情（图文/视频/meta）落在 `downloads/<note_id>/`，结果清单含 `status` 字段：

| status | 含义 | 处理 |
|---|---|---|
| `ok` | 图文/视频/meta 全部抓到 | 正常使用 |
| `deleted_or_private` | 收藏页卡片点不到/点击无 token/主页搜索均找不到 → **原文已删除、下架或转私密**（收藏页仍显示占位，原文不可达） | 不必再试；列表已留标题/作者可供记录 |
| `no_token` / `extract_err` | 页面异常/提取失败 | 重跑该条或人工复制带 xsec_token 链接 |

**方法**（已内置，无需手写）：①回到收藏 tab 滚动直到目标 `section.note-item[data-note-id]` 出现（每轮 2000px/1.8s，≤12 轮）→ ②同一帧 `scrollIntoView`+点击**可见** a → ③等 URL 含 `xsec_token`（新 tab 需切换）→ ④**留在当前详情页内联提取**（图片 `notes_pre_post`、视频 `sns-video` mp4），**不要 goto 二次访问 token URL**（会渲染为空）。

**失效兜底＝分享短链解析（2026-10-05 实测，最高优先级）**：收藏页/搜索/作者主页三路全空时，**不要判定"原文已删除"**——先请用户从 App 分享笔记链接（xhslink.cn 短链），然后：
1. `curl -sL -o /dev/null -w "%{url_effective}" "https://xhslink.cn/o/xxx"` → 重定向到 login?redirectPath=...，**redirectPath 里含完整 `discovery/item/{id}?xsec_token=...` URL**（URL decode 后把 http 换 https）
2. 直接用 `note "<该完整URL>"` 子命令抓取——分享签发的 token 直接 goto 可读（不适用"token 二次访问渲染为空"的教训，那是收藏页点击场景）
3. 实测：某 2 条"三路全空"的收藏（AI珠宝设计入门/首饰模特图3步）用此法 **2/2 抓取成功**（9图+2图，正文完整）
> 结论：`deleted_or_private` 标记只在「三路全空 **且** 用户无法提供可访问分享链接」时使用；能拿到分享链接一律先走短链解析。

## URL 要求（关键！）

**必须复制带 `xsec_token` 的完整 URL**：
- ✅ `https://www.xiaohongshu.com/explore/6aa040cd...?xsec_token=AB8l-mdf...&xsec_source=`
- ❌ `https://www.xiaohongshu.com/explore/6aa040cd...`（裸 ID，会被 300031 拦截）

获取方式：在浏览器里从首页/搜索结果/用户主页点进笔记，复制地址栏完整 URL。

## 输出结构

```
downloads/
└── {note_id}/
    ├── img_01.jpg ... img_NN.jpg     # 正文图（webp 转存为 .jpg 后缀，实际 RIFF webp）
    ├── video_01.mp4                  # 视频（如有）
    └── meta.json                     # 标题/正文/作者/点赞/收藏/评论/直链清单
```

## 实测结论（2026-10-05）

| 场景 | 结果 |
|---|---|
| 未登录 + 裸 note_id curl | ❌ 300031 拦截，重定向 404 |
| 已登录 + 裸 note_id（无 xsec_token） | ❌ 同样 300031 |
| 已登录 + 带 xsec_token | ✅ 图文/视频都能抓 |
| 图片直链下载 | ✅ webp 样式 97KB/张，无 header 直接下；原图样式 403 |
| 视频 mp4 直链下载 | ✅ 无 header 直接下，7.1MB/条实测成功 |

## 各子命令实测状态（2026-10-05 全部通过）

| 子命令 | 状态 | 实测结果 |
|---|---|---|
| `note <url>` | ✅ | 图文 8 张 webp + 视频 7.1MB mp4 + 完整元数据 |
| `comments <url>` | ✅ | 抓到 20-30 条评论（内容/点赞/时间）；user 字段选择器待优化（可能为空） |
| `search <kw>` | ✅ | 命中 10 条，从 `section.note-item[data-note-id]` 提取 note_id + 标题 + 点赞数 |
| `user <url>` | ✅ | 作者主页 15 条笔记，标题正确，含之前测试的汉堡笔记交叉验证一致 |
| `favorites` | ✅ | 自动识别当前登录账号主页 → 切"收藏"tab → 抓到 28 条收藏（note_id + 标题 + 作者） |
| `favorites --with-detail` | ✅ | 列表→逐条详情闭环；实测 28 条中 26 条 ok（含图文+视频）；2 条三路全空→**用分享短链解析兜底后 2/2 成功**（2026-10-05 实测） |

**注意**：小红书 web 端限制同时在线设备数，bu 浏览器和 playwright 脚本同时登录会互相挤掉（报"电脑设备登录超限"）。实际使用时**只用 playwright 脚本那个独立 profile**，不要同时开多个已登录实例。

**调试规范（2026-10-05 沉淀）**：看 DOM/找选择器时**不要再开 bu 浏览器登小红书**——两个 Chrome 实例会互踢登录态。调试统一在 playwright 脚本里加 `print(page.content())` 或 `page.pause()`（headed 模式会暂停在弹出的 Chrome 里直接看）。bu 浏览器留给其他不需要登录态的网站调试。

## 防风控要点

- **不要高频翻页/批量**：搜索和用户主页翻页每次滚动后停 1.5s，不要像爬虫一样快速刷。
- **不要复用脚本 profile 做日常浏览**：这个 profile 只给采集用，日常用自己的 Chrome。
- **cookie 过期后重新扫码**：`web_session` 是服务端签发，过期后脚本会自动检测到登录弹窗，重新扫一次即可。
- **图片直链有时效**：拿到后尽快下载，不要存几小时后再下。
- **撞 403/406 就停**：不要立刻重试，冷却 10 分钟以上。

## 收藏逐条详情抓取（v6 已验证方案，2026-10-05 实测 11/13 成功）

favorites 列表（28 条）稳定可抓；逐条详情此前被 xsec_token 卡住，2026-10-05 突破：

1. **打开收藏页**（profile?tab=fav&subTab=note），滚动加载直到目标卡片 `section.note-item[data-note-id="..."]` 出现在 DOM（每轮 wheel 2000px + 1.8s，最多 12 轮；目标不出现就换下一轮）
2. **同一 evaluate 内** `card.scrollIntoView({block:'center'})` + 点击**可见** a（`Array.from(card.querySelectorAll('a')).find(a => a.offsetParent !== null)`）——点击 display:none 的隐藏 a 会触发 sec_ 风控跳 404
3. 等待 URL 含 `xsec_token` 且含 note_id（最多 12s；新 tab 需 `context.pages[-1]` 切换）
4. **拿到 token 后直接在当前页内联提取**——标题/正文/作者/点赞/收藏 + `notes_pre_post` 图片 + performance entries 里 `sns-video` 的 mp4 直链 → `download_url` 下载。**不要再 goto 该 token URL 二次访问**（详情会渲染为空，图0视频0）

失败场景备忘：裸 note_id 直开 300031→404（已登录也不行）；收藏页某些条目滚动 22 轮+搜索路线都找不到（疑为收藏 tab 虚拟渲染/子视图差异，遇此类条目可先跳过，用 search 关键词从搜索结果页点击同机制拿 token）。

## 与其他平台的分工

- YouTube/B站/抖音：继续走 `media_downloader.py`（yt-dlp 路线）。
- 小红书：yt-dlp extractor 当前坏的，且反爬重，走 `scripts/xhs/xhs_downloader.py`（浏览器直读路线）。
- 后续如果 yt-dlp 修复了 XiaoHongShu extractor，可在 `media_downloader.py` 里加一个分发，但当前优先保证本脚本能跑。
