# B站：列取某 UP 主"全部投稿/合集"的防风控方法

> 被 `../SKILL.md` 与 `platform-strategy.md` 的 B 站小节按需引用。单条 BV 怎么下看主文档；本文件只解决"把某个 UP 的全部投稿列全（再批量下载）"这一最易触发风控的环节。
> 2026-09-11 在一个 UP（官方实时 count=**743** 投稿）上做全链路对照实测（强制直连、macOS、Chrome 152）。

## 0. 一句话结论

- **难点只在"列清单"，不在"下视频"**：空间列表接口对游客风控极强，但单个 BV 的解析/下载通常不受影响。先稳妥把 BV 清单拉全成 JSON，再走单视频链路慢速下载。
- **游客态（脚本接口 / 独立 Chrome 驱动前端 DOM 慢翻，见 §2、§3）在数百条量级最终都被请求密度软限流掐断、列不全**；仅在投稿量很小（几十条内）时 §3 的游客慢翻值得一试。
- **【最终正解，已一次列全 743 条】让用户在独立 Chrome 登录小号，本地匿名算 wbi、在"已登录页面上下文"里 fetch `arc/search`**：wbi mixin 本地计算（与账号无关，匿名 nav 也给 wbi_img），数据请求在页面内发出、`credentials:'include'` 自动携带 HttpOnly 的 SESSDATA，**不导出、不落盘任何账号凭据**；ps=50 约 1 分钟翻完 15 页，条数与官方实时 `count` 对齐（当次分页合计 742，拉取时官方 count 在 742–743 间随 UP 实时投稿小幅跳动，以当次 count 为准）。细节见 §6.2。

## 1. 先分清两类接口

| 接口类别 | 端点举例 | 游客风控 | 说明 |
| --- | --- | --- | --- |
| 单视频 | `x/player/wbi/v2`、`playurl` | 低 | 走 `media_downloader.py` 下 BV；列表接口被限流时单个 BV 往往仍可下 |
| 列表/翻页 | `x/space/wbi/arc/search`、`x/polymer/web-dynamic/v1/feed/space`、`seasons_series_list` | **极高** | 游客快速翻页必撞 412 / -352 / 空白软限流，是本文件重点 |

## 2. 已实测"游客态做不通 / 有硬限制"的通道（别重复踩）

| 通道 | 游客实测结果 | 结论 |
| --- | --- | --- |
| urllib/requests 直调 `arc/search`（带 wbi、buvid、真实 UA、直连） | 恒 412 / code=-352（返回 `v_voucher` 票据） | 走不通 |
| `curl_cffi impersonate="chrome"`（真实 TLS/JA3）调 `arc/search` | **仍 412/-352** | 与 TLS 指纹无关，别再往这个方向耗 |
| 在真实页面上下文里 `fetch('arc/search')`（浏览器自动带 cookie/头） | 仍 -352 | 缺前端那层 `bili_ticket`/gaia 风控验证闭环，裸 fetch 补不上 |
| 动态流 `feed/space` 游标翻页 | 首页（offset 空、不带 dm）成；第 2 页带齐 `dm_*` 指纹成；**第 3 页起必空（游客深度墙≈前 24 条）** | 只能拿最新一屏，列不全 |
| URL 直接定位 `?pn=N`（如 `/upload/video?pn=7`） | 参数被忽略/列表空 | **新版 upload/video 是纯前端分页，不认 URL pn** |
| yt-dlp `extract_flat` 翻空间 | 大量 412，得到一堆空壳 | 不可用 |
| 复用本机 Chrome 登录态 | 该用户三个 Profile 均无 `SESSDATA`（未登录） | 无登录态可借时不成立 |

> `-352` 响应里的 `v_voucher` 是风控验证票据：前端正常浏览时会自动跑一次内部验证（ExClimbWuzhi/gaia）拿到 `bili_ticket` 再放行；外部脚本复刻这套 wasm 验证成本极高，**正解是让前端自己跑（§3），而不是自己补票据。**

## 3. 游客方案：独立 Chrome + 驱动前端翻页 + 读 DOM（小量可试，数百条量级最终被证伪）

> ⚠️ **最终复核**：本方案"深页可达、慢翻"在头几页成立，但连续翻到第 2~3 页后仍稳定触发软限流（页码变、列表不刷新），数字跳页 / 整页重置也无法持续，**743 条量级没跑通，最终改用 §6.2 登录小号页面 fetch 一次列全**。下面保留具体做法，供 UP 投稿量小、且坚持零登录时使用。

思路：**所有数据请求都让 B 站前端自己发（自带完整风控闭环），脚本只做"翻页动作 + 读已渲染 DOM"，不自己调任何列表接口。** 全程不登录、不碰账号，等价于"一个真人在慢慢翻这个 UP 的投稿页"。

### 3.1 起一个与主浏览器隔离的游客实例（不污染、不碰用户登录态）

```bash
"/Applications/Google Chrome.app/Contents/MacOS/Google Chrome" \
  --remote-debugging-port=9223 \
  --user-data-dir="<任务目录>/.chrome-prof" \
  --no-first-run --no-default-browser-check --disable-extensions --disable-sync \
  about:blank
```
- 用**独立 `--user-data-dir` + 独立端口**，不动用户日常 Chrome（保护其登录态、也避免脏调试会话卡死主浏览器，见 §6 教训）。
- Chrome 152 起 `/json/list`、`/json/version` HTTP 端点被关（404），**只剩 `DevTools listening on ws://127.0.0.1:<port>/devtools/browser/<id>`**：从启动日志取这个 ws，用 CDP over WebSocket（`Target.getTargets / attachToTarget(flatten) / Runtime.evaluate / Page.navigate`）操作。

### 3.2 投稿页 DOM 选择器（已逐字段验证）

- 卡片：`a.bili-cover-card[href*="/video/BV"]`；bvid 从 href 正则 `/BV[0-9A-Za-z]{10}/`。
- **标题取卡片内 `img.alt`**（卡片 innerText 是"播放 弹幕 时长"杂糅，别用）。
- `.bili-cover-card__stat span` 依次为 播放 / 弹幕 / 时长。
- 当前页：`.vui_button--active` 的数字；数字页码按钮：`button.vui_pagenation--btn-num`；上一页/下一页：`button.vui_pagenation--btn-side`（按文本"下一页"区分）。
- 侧栏"视频 N"=官方投稿总数；该 UP 实测 19 页、每页 40、最后一页 22（18×40+22=742，与侧栏一致）。

### 3.3 翻页方式与"深页可达、快翻必限"（关键）

- **游客能到任意深页**：从第 1 页直接点数字页码"19"，一次就加载出最后一页 22 条（最早的视频）。所以**不存在"游客只能看前几页"的硬墙**。
- **但连续快速点"下一页"会触发频率软限流**：现象是**分页器页码变了、视频列表却不刷新**（页码乐观更新，数据请求被静默拒）。3–6s/页的快节奏在第 2–3 页后必现；卡住后干等不会自愈。
- 因此：
  1. **慢**：每页之间随机停 **10–18s**（真人浏览节奏，19 页约 5 分钟，慢可接受）；
  2. **判据要双条件**：必须同时满足"当前页码变化"且"第一张卡片 BV 确实更换、本页卡片数>0"才算翻成功，不能只看页码；
  3. **优先点相邻数字页码**（文本=当前页+1 的 `--btn-num`，折叠不可见时退回点"下一页"）；
  4. **退避自愈**：某页 20s 没刷新就退避 20/40/60s 再点，最多 3 次；仍失败则停手保断点（下次可"导航回第1页→直接点目标数字页码"跳到断点页续采，深页可达已验证）。
- 每采一页实时落盘 `{last_page, videos[]}`，按 bvid 去重，可随时中断续采。

> 全量 19 页"10–18s 慢节奏一次跑通"这一步在实测当日因前期高频实验触发软限流而**待冷却后最终复核**；但"深页可达、快翻被限、双条件判据、数字跳页"均已单独实测成立。

## 4. 软限流的识别与冷却（最重要的防风控纪律）

- **典型空态（截图实锤）**：页面框架、顶部导航、UP 名、侧栏"视频 742"都在，但视频列表区显示"**空间主人还没投过视频，这里什么也没有…**"——侧栏有数、列表说没有，**自相矛盾即列表接口被限流的空态兜底，不是真的没视频**；此时通常无验证码、无登录弹窗。
- 一旦出现：**立刻停止一切 B 站请求，冷却 10–30 分钟（严重更久）**。期间换参数、换接口、反复刷新/重试都只会延长限流（这是当日用两小时高频对照换来的教训）。
- 冷却后建议**重启独立 Chrome 并换新 `--user-data-dir`（全新游客 buvid 指纹）**再采，且一次慢速跑完，不再做零散试探。
- 强制直连（走代理出口反而 412）；本机时间与标准时间误差 <30s。

## 5. wbi 与接口前置（仅在走接口方案/登录态时需要）

- 设备指纹：先 `GET x/frontend/finger/spi` 取 `b_3/b_4` 作 `buvid3/buvid4` + `b_nut=<unix秒>`。
- wbi：`x/web-interface/nav`（**匿名 code=-101 也照常返回 `wbi_img`**）取 img/sub key 文件名拼接，按官方 64 位重排表取前 32 为 mixin key；参数加 `wts`、按 key 升序 urlencode，`w_rid=md5(query+mixin)`；**key 每日轮换，每次会话重取，勿硬编码**。
- 动态流若用：首页 offset 空且**不带** `dm_*`；翻页 offset 非空时**必须带齐** `web_location=333.999 / dm_img_list=[] / dm_img_str / dm_cover_img_str / dm_img_inter` 且参与 wbi 签名；offset 原样透传长整数字符串。但记住它游客只能翻约 2 页（§2）。

## 6. 仍搞不定时的升级路径（代价从低到高）

1. 冷却 + 换全新游客指纹（§4），并用 §3 的慢节奏，多数情况到此即可，**不需要登录**。
2. **【本次最终就靠这档一次成功，推荐】让用户在独立 Chrome 登录一个专用小号（非主号；只读公开投稿、慢速，主号零风险），不导出 cookie，而是"本地算 wbi + 已登录页面内 fetch"**：
   - wbi 签名在本地 Python 匿名完成：匿名 `nav` 取 `wbi_img`（code=-101 也照常给），mixin key 与账号无关、每次会话重取、勿硬编码；
   - 数据请求在**已登录页面的 JS 上下文**里 `fetch('x/space/wbi/arc/search?'+signedQuery,{credentials:'include'})`：HttpOnly 的 SESSDATA 浏览器自动携带，JS 读不到也不必读，**绝不导出/落盘账号凭据**；
   - ps=50、单线程、约 1~2s/页，15 页约 1 分钟列全 743 条，与官方实时 `count` 对齐；官方合集走 `seasons_series_list` → `seasons_archives_list`（series 的 polymer 端点对该 UP 无效时回退旧 `x/series/archives`，不签名），同样在登录页面 fetch；
   - 备选：导出 Netscape `cookies.txt`（含 SESSDATA）交脚本也能解除限制，但凭据会落盘，安全性不如"页面内 fetch"。
3. 换更干净的出口 IP；确认 bilibili.com 走直连。
4. 桌面 GUI 级拟人兜底（真实鼠标逐页滚动），成本最高；§3 的 CDP 驱动前端已是"程序化的拟人"，通常不必退到这一步。

**教训（CDP 运维）**：通过 ws 调试端点连 Chrome，结束时必须发 `Target.detach`/优雅关闭 WebSocket 握手；一次 `sys.exit` 没关连接曾把主 Chrome 的 browser 调试端点"占住"十几分钟不自愈（后续握手全超时，只能重启主 Chrome）。所以才用独立实例隔离。

## 7. 拿到清单之后

- 清单字段至少 `bvid/title/duration/play/page/url`；**分类首选 UP 自己的"合集和系列"**（该 UP 有 11 个合集；接口 `seasons_series_list`，冷却后随清单一起拉），缺合集映射再按标题主题聚类。
- 批量下载回到主链路 `media_downloader.py <BV>`：单线程、默认限速 2MiB/s、文件间随机间隔、每 10 个长冷却、`--download-archive` 记已完成 BV、遇退出码 14（412）整体冷却，可断点续跑。
- 取文字仍遵循主流水线：字幕优先，无字幕才下最小音频交 FunASR；珠宝/口播类中文按分钟 250–320 字核对转写完整度。
