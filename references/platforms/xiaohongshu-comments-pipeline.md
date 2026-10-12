# 小红书评论接入主流水线（T06）+ 图文实采准备（⑩）

> 状态：**接入方案已设计 ✅ ｜ 实采 ⚠️ 待用户提供一条带 xsec_token 的真实笔记链接**
> 日期：2026-10-12 ｜ 归属：multiplatform-media-fetch 技能仓（主流水线 content-pipeline 文档不动）
> 上游：`references/platforms/xiaohongshu.md`（采集策略与风控红线）、`scripts/download/xiaohongshu/xiaohongshu_downloader.py`
> 字段对齐基准：`references/platforms/douyin-comments-extract.md`（抖音评论 canonical schema）

---

## 1. 目标

把小红书单条笔记的评论区抽成**与抖音同构**的结构化 JSON，落入主流水线权威库 `library/08_sources/`，供 S4 成文作选题 / FAQ / 观点验证信号；全程只读、低频、严守小红书风控红线。

## 2. 现状与差距（实测代码核对）

`collect_comments()`（脚本 L226–258）当前产物是**裸数组**：

```jsonc
[ { "user": "…", "content": "…", "like": "…", "time": "…" } ]
```

与抖音 canonical schema 对比，缺三项 + 缺外层 meta 信封：

| 抖音 canonical 字段 | 小红书当前 | 差距 / 处理 |
|---|---|---|
| `comment_id` | 无 | ⚠️ 当前选择器未取；需补 `data-id`/more 按钮子节点 id（对齐抖音 `tooltip_<cid>` 法） |
| `user_name` | `user` | 改名即可 |
| `content` | `content` | ✅ 一致 |
| `like_count` | `like` | 改名即可 |
| `reply_count` | 无 | ⚠️ 需补"展开 N 条回复"按钮计数 |
| `time` | `time` | ✅ 一致（相对时间+地区原文保留） |
| 外层 `{note_id, source_url, meta{title,author,fetched_at,tier_used,status,block_reason}, comment_count}` | 无（裸数组） | ⚠️ 需补信封 |

**结论**：采集脚本可跑，但**不能直接入主流水位/对账**——中间需一个 normalize 适配步（reshape 裸数组→canonical 信封），建议落在主流水线 S1 校验门做，不在采集脚本里硬改字段以免破坏 xiaohongshu.md 既有约定。

## 3. 落库约定

```
library/08_sources/xiaohongshu_comments/
└── {note_id}_comments.json      # canonical 信封（见 §4）
```

- 与抖音评论、图文 raw 同级（`08_sources/`＝来源素材）；raw/过程件不进 Git（`.gitignore: library/08_sources/*/raw/` 已覆盖）。
- 与笔记正文/图集的对应：图文 raw 在 `library/08_sources/<行业>/小红书/<note_id>/raw/`，评论独立成 `xiaohongshu_comments/{note_id}_comments.json`，靠 `note_id` 指针互连（不复制正文）。

## 4. Canonical 输出 schema（normalize 后）

```jsonc
{
  "note_id": "6aa040cd-xxxx",
  "source": "xiaohongshu",
  "source_url": "https://www.xiaohongshu.com/explore/<note_id>?xsec_token=...",
  "meta": {
    "title": "笔记标题",
    "author": "作者昵称（尽力取，可空）",
    "note_like_count": "笔记点赞（尽力取，可空）",
    "fetched_at": "2026-10-12T23:30:00+08:00",
    "tier_used": "chrome_profile",        // chrome_profile | failed
    "status": "ok",                        // ok | login_wall | captcha | not_found | empty
    "block_reason": null,                  // 撞墙时写明，不硬闯
    "pages_scrolled": 3                    // 实际滚动页数，≤3 硬性
  },
  "comment_count": 0,
  "comments": [
    {
      "comment_id": "",        // 尽力取，取不到留空但字段保留
      "user_name": "",
      "content": "",
      "like_count": 0,
      "reply_count": 0,
      "time": ""               // 相对时间+地区原文
    }
  ]
}
```

## 5. S4 成文用途（信号，不是正文）

- **选题信号**：高赞高频提问 → 后续文章 FAQ/小标题。
- **FAQ 素材**：把典型追问直接转成"读者会问的问题"小节。
- **观点验证**：评论区共识/争议用于正文论点的佐证或反方平衡。
- 红线：评论是**他人 UGC**，只提炼观点 + 引用，不整段搬运；与生财有术版权边界同规。

## 6. 风控落实（硬性，不可谈判）

| 项 | 规定 |
|---|---|
| 评论翻页 | **≤3 页**（脚本现固定 `for _ in range(5)` wheel 1500×1200ms，**需参数化并封顶到 3 页**——这是本项首要改动点） |
| 并发 | `MAX_CONCURRENCY=1`，同一时刻只飞一条 |
| 互动 | 只滚动加载，**不点赞/不回复/不关注/不发布** |
| 撞墙 | 撞 403/406/滑块/验证码 → 立即停，落盘 `status`，**冷却 ≥10 分钟**，不换 UA 硬刚 |
| 登录 | `web_session` 过期脚本会检测到登录弹窗 → 转人工扫码，**不自动破解** |
| 冷却期 | 账号 2026-10-07 已收「违规预警」→ 按红线停 **7–14 天纯人工**；期间不登 web、不开采集 profile |

## 7. 实采准备（⑩）状态：⚠️ 待用户提供链接

- **只读预检**：登录 profile `~/.cache/multiplatform-media-fetch/xhs_profile/` **存在**（`Default/Cookies` + `Local State`，时间戳 2026-10-05 23:24）。
- **但本次未实采**，原因（用户原则，2026-10-13 澄清）：**只处理已得到的原数据，没得到的暂不采集**——小红书当前没有已得的带 `xsec_token` 真实笔记链接，保持设计就绪、不主动采集。
- 按"不硬造 URL / 不强攻登录 / 未得数据不主动采集"纪律，**本项不标完成**。

### 用户提供链接后的实采闭环（人工触发）

```bash
PY="装了 playwright 的 python3"
# 0. 用户已提供一条带 xsec_token 的完整笔记链接（已得原数据）
# 1. （如 cookie 过期）人工扫码一次
$PY scripts/download/xiaohongshu/xiaohongshu_downloader.py login
# 2. 图文 + 元数据（用户从浏览器点进笔记后复制的完整 URL，必带 xsec_token）
$PY scripts/download/xiaohongshu/xiaohongshu_downloader.py note "<完整URL>" -o ./downloads
# 3. 评论（≤3 页；滚动轮数需先封顶）
$PY scripts/download/xiaohongshu/xiaohongshu_downloader.py comments "<完整URL>" -o ./downloads
# 4. normalize 成 §4 canonical 信封 → 落 library/08_sources/xiaohongshu_comments/{note_id}_comments.json
```

失效兜底：分享短链解析——`curl -sL -o /dev/null -w "%{url_effective}" "https://xhslink.cn/o/xxx"` 取 redirectPath 里的完整 `discovery/item/{id}?xsec_token=...`。

## 8. 坑

1. **裸数组 vs canonical**：现有评论 JSON 不能直接入对账，必须先 normalize（补 comment_id/reply_count/meta 信封）。
2. **脚本 5 轮滚动 > 3 页红线**：需把 `range(5)` 改为可配、默认 ≤3。
3. **xsec_token 有时效**：裸 note_id 必被 300031 重定向 404；必须用户从首页/搜索点进后复制完整 URL。
4. **设备互踢**：bu 浏览器与 playwright 脚本 profile 同登小红书会互踢；调试只用脚本独立 profile。
5. **选择性采集原则（2026-10-13 用户澄清）**：只处理已得到的原数据，未得到的暂不采集——小红书无已得 xsec_token 链接时保持设计就绪，不主动采集。
