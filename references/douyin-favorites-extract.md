# 抖音收藏遍历提取法（登录态 · 列表级）

> 2026-10-05 实测沉淀。与 `douyin-browser-extract.md` 的分工：那篇是**公开视频页免登录**单条直读；本篇是**登录态下遍历收藏/关注列表**，用于"把用户抖音收藏里所有与 XX 相关的视频找出来逐个解析"。

## 适用场景

用户要求"看我的抖音收藏""遍历收藏里与视频生成相关的视频"——收藏是**私有数据**，必须登录态，不能走匿名 ttwid / 免登录直读。

## 前置条件

1. **Chrome 已登录抖音**：验证方法是打开个人页 `https://www.douyin.com/user/self?showTab=favorite_collection`，页面标题出现用户名（如"byte886 的抖音"）即已登录。
2. 未登录 → 出现登录墙（读操作返回空/登录提示）→ **下一条动作必须是 `interaction.request_action`（type=browserControl）** 交给用户登录，不得换 URL/平台绕过。

## 流程

### 步骤 1：打开收藏页并验证登录

```python
bu.navigate("https://www.douyin.com/user/self?showTab=favorite_collection")
bu.wait_for_load(timeout=20)
time.sleep(4)   # 收藏列表懒加载，必须等
info = bu.page_info()
# 标题含用户名 = 已登录；否则按登录墙判定移交
```

收藏页结构：顶部 tab 有「收藏夹：视频 / 音乐 / 合集 / 短剧」，默认在"视频"。列表是**无限滚动**（懒加载），一次只渲染可见部分。

### 步骤 2：滚动收集全部条目（href 去重）

```python
all_items = {}   # href -> 标题
for i in range(25):
    rows = bu.read_all("a[href*='/video/']", fields=["text", "href"], limit=100)
    for r in rows:
        href = r.get("href", "")
        if href and href not in all_items:
            all_items[href] = (r.get("text", "") or "").strip()
    bu.js("window.scrollBy(0, 1200)")
    time.sleep(1.5)
    # 条目数不再增长（连续多轮不变）即收完，可提前 break
```

- `read_all` 的 text 字段每行是独立条目文本（点赞数、标题、话题通常分行，需要按"标题行"甄别；点赞数字行可作排序参考）。
- 视频 ID 从 href 提取：`https://www.douyin.com/video/<纯数字>`。

### 步骤 3：剔除非收藏干扰

- **`?source=Baiduspider`（含 `Baiduspider-sdc`）的链接是搜索引擎抓取的页面，不是用户收藏**，按 href 特征直接剔除。
- 无关主题条目（游戏/旅游/教程杂项）按用户给定筛选词剔除。

### 步骤 4：筛选 + 逐条解析

按用户主题筛选（如"视频生成相关"）→ 对选中条目逐个走 `video-effect-analysis.md` SOP：
1. 打开视频页 `https://www.douyin.com/video/<ID>`
2. 章节要点（官方面板，等效字幕）优先；短视频无要点则关键帧采样
3. 评论区滚 1-2 屏（博主常自述核心参数/方法，是金矿）
4. 按输出模板写解析条目，标注四档来源

## 注意

- 收藏可能上百条：**先建盘点总表（编号+分类+状态）再分批解析**，避免边看边写没有总览。
- 每个视频 2-3 次浏览器调用（打开读信息 → 采样/评论），**大批量时逐条控制在"章节要点+关键帧2-4张+评论1屏"的轻量模式**，控制 token。
- 私密收藏/需关注的作者内容可能被墙——按登录墙判定处理（移交用户）。
- 与脚本链路关系：`media_downloader.py` 无法访问收藏列表（列表接口风控），浏览器直读是正解。
