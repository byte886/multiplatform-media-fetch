# 抖音单条视频评论采集（浏览器直读 DOM · 只读）

> 2026-10-12 实测沉淀（郭颖置顶片 7474846772968426811，匿名档一次成功，6 条文字评论）。
> 脚本：`scripts/download/collect_douyin_comments.py`。
> 与同目录其它抖音文档的分工：本篇只负责**把某条公开视频的评论区抽成结构化 JSON**；不下原片、不遍历列表。

## 能力说明

- 输入：视频 URL（`https://www.douyin.com/video/<vid>` / `v.douyin.com` 短链）或纯数字 vid。
- 输出：`<out_dir>/<vid>_comments.json`，含 meta（视频标题/点赞/抓取时间/命中档位/状态）+ comments[]。
- 路线：**不逆向评论接口签名**（`/aweme/v1/web/comment/list/` 的 a_bogus/X-Bogus 跟版本频繁变，维护成本高）。用外部 Google Chrome 打开公开视频页，等评论面板渲染后从 DOM 直接抽取。
- 三级回退（沿用 `platform-strategy.md` 抖音纪律）：
  1. **匿名**（fresh context，无 cookie）——公开视频评论匿名可读，最安全，先试；
  2. **Chrome 登录态**（persistent profile `~/.cache/multiplatform-media-fetch/douyin_profile/`）——匿名拿不到时复用本 profile 登录态；
  3. **仍被挡** → 落盘 `status=login_wall/captcha/empty`，**不硬闯**，提示人工开窗。

## 用法

```bash
PY="<装了 playwright 的 python3>"   # 脚本会自举找，通常直接 python3 即可
# 单条视频评论
$PY scripts/download/collect_douyin_comments.py "https://www.douyin.com/video/7474846772968426811" -o <输出目录>
# 或裸 vid
$PY scripts/download/collect_douyin_comments.py 7474846772968426811 -o <输出目录>
# 调滚动轮数（默认 6 轮≈30-60 条上限）、dump DOM 调选择器
$PY scripts/download/collect_douyin_comments.py <vid> -o <dir> --max-rounds 10 --debug
```

- 会弹出**外部 Google Chrome**（headed），属正常；脚本只读滚动，不点赞/不回复/不关注。
- 首次匿名档即可读公开评论；`--debug` 会把整页 DOM dump 到 `~/.cache/multiplatform-media-fetch/<vid>_dom_debug.html` 便于找选择器。

## 风控纪律（硬性）

- **只读**：脚本只滚动评论区加载，绝不点赞/回复/关注/发布。
- **低频串行**：一次只处理一条视频；条与条之间 ≥30s±jitter，单会话 ≤15 条（与 `douyin-favorites-extract.md` 同档）。批量时逐条串行，不要在脚本里循环快刷。
- **撞登录墙/滑块/403**：立即停，落盘状态，冷却 ≥30 分钟，不换 UA/不改 cookie 硬刚；需要登录就人工开窗（见下）。
- 公开视频评论匿名可读；私密/关注可见/受限内容才需登录——脚本拿不到就如实标 `login_wall`，不强行突破。

## 输出格式

```jsonc
{
  "vid": "7474846772968426811",
  "source_url": "https://www.douyin.com/video/7474846772968426811",
  "meta": {
    "title": "【院长开课了】郭颖：...",   // 视频标题（首行）
    "author": "",                       // 作者（尽力取，可能空）
    "digg_count": "251",                // 视频点赞
    "fetched_at": "2026-10-12T23:16:29",
    "tier_used": "anonymous",           // anonymous | chrome_profile | failed
    "status": "ok",                     // ok | login_wall | captcha | not_found | empty
    "block_reason": null
  },
  "comment_count": 6,
  "comments": [
    {
      "comment_id": "7475352172780585739",   // more 按钮子节点 id="tooltip_<cid>"
      "user_name": "芳叶亭",
      "content": "郭老师一直这么帅",
      "like_count": 2,
      "reply_count": 0,                        // 来自"展开N条回复"按钮
      "time": "1年前·北京"                     // 相对时间+地区原文
    }
  ]
}
```

## DOM 选择器（2026-10-12 实测，抖音 web 端）

抖音 class 名是**混淆的**（`Eh0a5CD4`/`FduGc_lz`/`VAQA49VP` 随构建变），但保留一批稳定钩子：

| 字段 | 稳定取法 |
|---|---|
| 评论项 | `[data-e2e="comment-item"]` |
| comment_id | 项内 `[id^="tooltip_"]` 的 id 去掉 `tooltip_` 前缀 |
| user_name | `.comment-item-info-wrap` 里第一个 `a[href*="/user/"]` 的 innerText |
| like_count | `.comment-item-stats-container` innerText 首行数字（支持"万"） |
| reply_count | `.comment-reply-expand-btn` 文本"展开N条回复"里的 N |
| time | 项内匹配 `/(年前|个月前|天前|小时前|分钟前|YYYY年M月D日)/` 的**最短**元素 |
| content | **克隆整个 comment-item → 移除已知子树**（info-wrap/avatar/stats/tag/展开按钮/tooltip）→ `textContent`，再正则去掉时间串 |

> 关键：正文/时间/统计**全部嵌套在同一个 `dIlRe7ZV` 容器内**，不是 info-wrap 的兄弟节点；所以正文不能靠"兄弟节点归类"，必须用"克隆+剥子树+textContent"。

## 已知坑（实测踩过）

1. **混淆 class 会变**：不要写死 `.FduGc_lz` 这类；只用 `data-e2e` 和 `comment-item-*` 稳定后缀。
2. **正文不是 info-wrap 的兄弟**：作者行/正文/时间/统计全在 `dIlRe7ZV` 里嵌套；按"兄弟节点"分类会把整个正文容器当作者行跳过，结果只剩"展开N条回复"。
3. **`cloneNode` 后用 `innerText` 取正文 = 空**：脱离文档的节点没有渲染布局，`innerText` 返回空；必须用 `textContent`。
4. **时间删除别用 DOM remove**：对克隆节点做"匹配时间就 remove"会把"正文+时间"合在一起的父容器（含"年前"且<40字）整个删掉，正文变空。改为提取后用正则去掉时间串。
5. **time 要选最短匹配**：`querySelectorAll('div,span')` 按文档序第一个命中的往往是最外层容器（innerText 含整段评论）；要取 innerText 最短的那个叶子节点。
6. **纯表情评论无文字**：正文剥完为空，脚本跳过（不输出空 content）。
7. **"作者赞过"标签**：在 `.comment-item-tag` 里，剥子树时一并移除，不进正文。
8. **匿名即可读公开评论**：本次匿名档一次成功；匿名档偶发 0 条（页面未渲染完/被临时降权）会自动回退 Chrome profile 档。

## 失败时怎么办

- `status=login_wall`：评论要登录才给看。**待人工开窗**：在外部 Chrome 登录抖音后重跑本脚本（会自动走 Chrome profile 档），或按 `douyin-browser-extract.md` 人工浏览器直读评论区。
- `status=captcha`：撞滑块/验证。立即停，人工过验证，冷却后再跑，不自动化破解。
- `status=not_found`：vid 错或视频已删/私密。
- `status=empty` 但 DOM dump 里有评论：选择器被抖音改版了，看 `--debug` dump 重找稳定钩子。

## 与同目录文档分工

| 文档 | 负责 |
|---|---|
| `douyin-browser-extract.md` | 不下原片，浏览器直读"章节要点"+关键帧 OCR 出文稿 |
| `douyin-favorites-extract.md` | 登录态遍历收藏/关注列表，产出 vid+标题清单 |
| `douyin-web-video-download.md` | currentSrc+`__vid` 铁证法下载原片 mp4 |
| **本篇** | 拿到 vid 后，把该视频**评论区**抽成结构化 JSON |
