# B 站单条视频评论采集（游客 buvid · 直连 · 纯 API · 只读）

> 2026-10-12 实测沉淀（BV1kK4y1w7UN 宝石学家老许，游客 buvid 一次成功，code=0）。
> 脚本：`scripts/download/collect_bilibili_comments.py`。
> 与抖音评论（`douyin-comments-extract.md`）同套纪律，但路线更轻：**纯 HTTP API，不启浏览器**。

## 能力说明

- 输入：bvid / av<aid> / 视频 URL；输出 `<out_dir>/<bvid>_comments.json`。
- 路线（三步，全程游客、直连）：
  1. `GET x/frontend/finger/spi` → 游客 `buvid3/buvid4`（每次会话现取，不硬编码）；
  2. `GET x/web-interface/view?bvid=...` → `aid` + 视频元信息；
  3. `GET x/v2/reply?type=1&oid=<aid>&pn=N&sort=1` → 热门评论列表。
- 评论列表属**单视频接口**（低风控），游客 buvid 即可，**无需登录、无需 SESSDATA、无需 wbi 签名**。

## 用法

```bash
python3 scripts/download/collect_bilibili_comments.py "BV1kK4y1w7UN" -o <输出目录>
python3 scripts/download/collect_bilibili_comments.py "https://www.bilibili.com/video/BV1kK4y1w7UN" -o <dir> --pages 2
```

## 风控纪律（硬性）

- **必须直连**：B 站走代理出口会 412。脚本用 `ProxyHandler({})` 强制绕过系统/Clash 代理，不要改回。
- **只读**：只 GET 评论列表，不点赞/回复/发评论。
- **低频串行**：一次一条视频；翻页 ≤2 页、页间停 1.5s；单会话总量克制（与收藏遍历不同，评论列表是单视频接口，风控低，但仍不高频）。
- 撞 412 / code=-352（风控票据）→ 立即停，冷却 10–30 分钟，不换 UA 硬刚；冷却后换新游客指纹重跑。
- 不读本机登录 Cookie、不落盘任何凭据。

## 输出格式

```jsonc
{
  "bvid": "BV1kK4y1w7UN",
  "aid": 887900068,
  "source_url": "https://www.bilibili.com/video/BV1kK4y1w7UN",
  "meta": {
    "title": "你买的珠宝到底成本是多少？是如何定价的？",
    "owner": "宝石学家老许",
    "view": 35370, "like": 1937, "reply_total": 68,
    "fetched_at": "2026-10-12T23:36:13+08:00",
    "tier": "visitor_api", "status": "ok"
  },
  "comment_count": 3,
  "comments": [
    {
      "comment_id": "4602528905",          // rpid
      "user_name": "挖石头呀挖石头",
      "content": "感觉up这个宝石价格的科普有点问题啊……",
      "like_count": 39,
      "reply_count": 2,                      // rcount（楼中楼回复数）
      "time": "2021-05-22 11:10",            // ctime 转 UTC+8
      "ctime": 1621653014
    }
  ]
}
```

## 字段映射（x/v2/reply → 输出）

| 输出字段 | 接口字段 |
|---|---|
| comment_id | `rpid` |
| user_name | `member.uname` |
| content | `content.message` |
| like_count | `like` |
| reply_count | `rcount`（楼中楼数，非本接口展开） |
| time / ctime | `ctime`（unix 秒，脚本转 UTC+8） |

## 已知坑

1. **必须直连**：走代理必 412；脚本已 `ProxyHandler({})`，别为"科学上网"加代理。
2. **buvid 每次现取**：`x/frontend/finger/spi` 匿名即给 `b_3/b_4`；不硬编码，会话内复用即可。
3. **x/v2/reply 是旧版评论接口**：当前（2026-10）游客仍 code=0；若日后被下线，换 `x/v2/reply/wbi/main`（需 wbi 签名，见 `bilibili-up-listing.md` §5）。
4. **只拿顶层评论**：`x/v2/reply` 返回顶层楼；`rcount` 是楼中楼计数，正文未展开。要楼中楼正文需另调 `x/v2/reply/detail?rpid=...`（同样游客可，低频）。
5. **排序**：`sort=1`=按热度；`sort=0`=按时间。
6. **reply_total 是计数**：`stat.reply` 含楼中楼总数，远多于顶层评论条数（本例 68 vs 顶层 3），别拿顶层条数当评论总数。

## 与同目录文档分工

| 文档 | 负责 |
|---|---|
| `bilibili-up-listing.md` | UP 空间投稿**列表**遍历（高风控，需登录小号页面 fetch） |
| **本篇** | 单条视频**评论正文**（游客 API，低风控） |
| `platform-strategy.md` | B 站直连/限速/412 通用策略 |
