# 抖音作者作品列表遍历（增量检查 · 登录态/公开均可）

> 2026-10-12 实测沉淀。用于"某博主相比台账有没有发新视频""把某作者全部作品 vid+标题拉一遍"。
> 与 [`douyin-favorites-extract.md`](douyin-favorites-extract.md) 的区别：那篇遍历**自己的收藏夹**（私有、登录态）；本篇遍历**任一公开作者的作品网格**（公开视频免登录可读）。

## 什么时候用

- 定期增量检查：库里已归档某博主 N 条，要找出主页新发布的视频（差集=新增）。
- 首次盘点某博主全部作品 vid+标题。
- 单条视频下载仍走 [`douyin-web-video-download.md`](douyin-web-video-download.md)；本篇只负责"拿到完整 vid 清单"。

## 两个必踩的坑（先读）

1. **作品列表是"容器内滚动 + 虚拟渲染"，`window.scrollBy` 无效**。必须在作品网格容器内滚动：对末卡片 `scrollIntoView()`，或直接设滚动父容器 `div.parent-route-container.route-sc` 的 `scrollTop`。
2. **全页 `a[href*='/video/']` 会混入"推荐位"污染**：作者页侧栏/底部会推荐无关视频（短剧、家常菜、二手车等，vid 多为 71xx–75xx 的老片）。**必须把选择器限定在作品网格容器 `[data-e2e="user-post-list"]` 内**，否则差集会多出一批假增量。

## 步骤（bu 浏览器）

### 1. 拿到作者主页 URL（sec_uid）

- 已知主页 URL 直接用（形如 `https://www.douyin.com/user/<sec_uid>`）。
- 只有某条视频 vid 时：打开该视频页，从作者昵称链接取主页地址。
  - **坑：视频页 `data-e2e="video-author-avatar"/"video-author-nickname"` 等作者选择器会失效**；用 `bu.snapshot()` 的文本节点找作者名对应的 `a[href*='/user/']`，或 JS：
    ```js
    Array.from(document.querySelectorAll("a[href*='/user/']")).map(a=>a.href)
    ```

### 2. 进作品 tab，容器内滚动收集（href 去重）

```python
import seed_browser_use as bu, time
bu.navigate("https://www.douyin.com/user/<sec_uid>"); bu.wait_for_load(timeout=20); time.sleep(4)
items={}                      # vid -> 标题
for i in range(40):           # 虚拟列表，轮数按作品数/每屏条数估，380 条约 20+ 轮
    rows = bu.read_all('[data-e2e="user-post-list"] a[href*="/video/"]',
                       fields=["text","href"], limit=200)   # read_all 单次上限 200
    for r in rows:
        h=r.get("href","")
        if "/video/" in h:
            vid=h.split("/video/")[1].split("?")[0]
            if vid and vid not in items: items[vid]=(r.get("text","") or "").strip()
    # 容器内滚动：末卡片 scrollIntoView（或设父容器 scrollTop）
    bu.js("""
      var box=document.querySelector('[data-e2e="user-post-list"]');
      var cards=box?box.querySelectorAll("a[href*='/video/']"):[];
      if(cards.length){cards[cards.length-1].scrollIntoView({block:'end'});}
      var sc=document.querySelector('div.parent-route-container.route-sc');
      if(sc){sc.scrollTop=sc.scrollHeight;}
    """)
    time.sleep(1.5)
    # 连续若干轮条数不再增长即收完（自行计数 break）
```

- 作品 tab 顶部有"作品 N"计数，可作为**总数校验**（注意：计数通常不含置顶，网格会额外含 1–2 条置顶视频）。
- 图文帖（`/note/`）与视频（`/video/`）链接形态不同，按需一并收集或只取视频。

### 3. 增量差集

```python
# 台账 vid 从 manifest.csv 的 vid 列、或 xlsx 的 url 列提取（xlsx 的 vid 列是科学计数法、丢精度，务必从 url 提取）
old=set(已有台账vid); live=set(本次网格vid)
new=live-old          # 主页有、台账无 = 真增量（还要排除图文/已删的口径差异）
missing=old-live      # 台账有、主页网格不显示 = 图文帖/已删/私密，通常不用管
```

- 差集出来的每条新 vid，再走单条下载→转写/OCR→分级→归并流程。

## 注意

- 公开作者页免登录可读；撞登录墙/验证码按 `browser-use-automation-mac` 协议移交用户，不换号硬刚。
- 滚动低频（每轮停 1.5s 左右），不要快刷。
- 网格 vid 数与"作品 N"计数对不上时，先排查：置顶视频、图文帖（`/note/`）、虚拟列表未滚到底。
