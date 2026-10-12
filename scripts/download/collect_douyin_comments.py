#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
抖音（Douyin）单条视频评论采集器（只读 · 低频 · 浏览器直读 DOM）。

设计原则（与 multiplatform-media-fetch 其它平台一致）：
- 不逆向 /aweme/v1/web/comment/list/ 的 a_bogus/X-Bogus 签名（跟版本频繁变，维护成本高）；
- 用外部 Google Chrome 打开公开视频页，等评论面板渲染后从 DOM 直接抽取评论——公开视频页
  免登录可读，评论区随滚动懒加载；
- 三级回退（沿用 references/platforms/platform-strategy.md 抖音纪律）：
    1) 匿名（fresh context，无 cookie）——最安全，先试；
    2) Chrome 登录态（persistent profile，复用本 profile 内已登录的抖音账号）；
    3) 脚本两路都被登录墙/风控挡住 -> 不再硬闯，落盘 status=login_wall / blocked，
       提示走「浏览器直读人工开窗」（见 references/platforms/douyin-comments-extract.md）。
- 只读：只滚动加载评论，绝不点赞/回复/关注/发布任何内容。

CLI:
    python3 collect_douyin_comments.py <video_url_or_vid> [-o out_dir] [--max-rounds N] [--debug]

video_url_or_vid 形如：
    https://www.douyin.com/video/7474846772968426811
    https://v.douyin.com/xxxx/            （短链也会自动取最终 vid）
    7474846772968426811                  （纯数字 vid）

输出：
    <out_dir>/<vid>_comments.json
      meta: vid / source_url / title / digg_count(视频点赞) / fetched_at / tier_used / status
      comments[]: comment_id / user_name / content / like_count / reply_count / time

不写死任何凭证/token；登录态靠 persistent profile 自然携带，脚本本身不含账号信息。
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import time
from datetime import datetime
from pathlib import Path

PROFILE_DIR = Path.home() / ".cache" / "multiplatform-media-fetch" / "douyin_profile"
PROFILE_DIR.mkdir(parents=True, exist_ok=True)

VIDEO_URL_TMPL = "https://www.douyin.com/video/{vid}"


# --------------------------------------------------------------------------- #
# Playwright 自举：找一个装了 playwright 的 python（与 xhs 脚本同一套路）
# --------------------------------------------------------------------------- #
def _bootstrap_playwright():
    try:
        import playwright.sync_api  # noqa: F401
        return sys.executable
    except ImportError:
        pass
    candidates = [
        "/Users/wenjiechen/Library/Application Support/Doubao/sandbox_runtime/bases/e74152cd379ba45d7ca7f16dfa51b727/bin/python3",
    ]
    import subprocess
    for py in candidates:
        try:
            r = subprocess.run([py, "-c", "import playwright"], capture_output=True, timeout=10)
            if r.returncode == 0:
                return py
        except Exception:
            continue
    return None


# --------------------------------------------------------------------------- #
# vid 提取
# --------------------------------------------------------------------------- #
def extract_vid(arg: str) -> str:
    arg = arg.strip()
    m = re.search(r"/video/(\d+)", arg)
    if m:
        return m.group(1)
    m = re.search(r"/share/video/(\d+)", arg)
    if m:
        return m.group(1)
    m = re.search(r"/note/(\d+)", arg)
    if m:
        return m.group(1)
    m = re.fullmatch(r"\d{15,25}", arg)
    if m:
        return arg
    # 短链 v.douyin.com/xxx/ 无法本地解析，交给浏览器跳转后再从 URL 抓
    return arg  # 原样返回，navigate 后从 page.url 再提取


def vid_from_url(url: str) -> str:
    m = re.search(r"/video/(\d+)", url) or re.search(r"/share/video/(\d+)", url) or re.search(r"/note/(\d+)", url)
    return m.group(1) if m else ""


# --------------------------------------------------------------------------- #
# 登录墙 / 风控判定
# --------------------------------------------------------------------------- #
LOGIN_HINTS = [
    "登录后查看", "扫码登录", "登录即可见", "立即登录", "打开抖音",
    "你访问的页面", "滑块", "拖动滑块", "验证", "captcha",
]


def detect_block(page) -> str | None:
    """返回 None=未被挡；否则返回挡因（login_wall / captcha / not_found）。"""
    try:
        url = page.url
        title = (page.title() or "")
        body_snip = (page.evaluate("() => document.body ? document.body.innerText.slice(0, 1500) : ''") or "")
    except Exception:
        return "page_error"

    if "验证" in body_snip and ("滑块" in body_snip or "captcha" in body_snip.lower()):
        return "captcha"
    if ("页面不见了" in title) or ("页面不见了" in body_snip) or ("/404" in url):
        return "not_found"
    # 登录墙：评论区提示登录 / 弹出扫码
    if any(h in body_snip for h in ["登录后查看评论", "登录后查看", "扫码登录", "登录后免费"]):
        return "login_wall"
    return None


# --------------------------------------------------------------------------- #
# 评论 DOM 抽取（多选择器兜底，实测以 data-e2e 为主）
# --------------------------------------------------------------------------- #
EXTRACT_JS = r"""
() => {
  const out = [];
  const seen = new Set();

  // 评论项容器：data-e2e="comment-item"（2026-10-12 实测抖音 web 端稳定）
  const items = document.querySelectorAll('[data-e2e="comment-item"]');

  const parseCount = (s) => {
    s = (s || '').toString().trim();
    if (!s) return 0;
    const m = s.match(/([0-9.]+)\s*万/);
    if (m) return Math.round(parseFloat(m[1]) * 10000);
    s = s.replace(/[^0-9.]/g, '');
    if (!s) return 0;
    if (s.includes('.')) return Math.round(parseFloat(s) * 1000);
    return parseInt(s, 10) || 0;
  };
  const TIME_RE = /(年前|个月前|天前|小时前|分钟前|刚刚|\d{4}年\d{1,2}月\d{1,2}日)/;

  items.forEach((el) => {
    // comment_id：more 按钮子节点 id="tooltip_<commentid>"
    let cid = '';
    const tip = el.querySelector('[id^="tooltip_"]');
    if (tip) cid = (tip.id || '').replace(/^tooltip_/, '');

    // user_name：info-wrap 里指向 /user/ 的链接
    const wrap = el.querySelector('.comment-item-info-wrap');
    let user = '';
    if (wrap) {
      const a = wrap.querySelector('a[href*="/user/"]');
      if (a) user = a.innerText.trim();
    }
    if (!user) {
      const a = el.querySelector('a[href*="/user/"]');
      if (a) user = a.innerText.trim();
    }

    // time：item 内匹配时间模式的元素里，取 innerText 最短者（最贴近 "1年前·山东" 的叶子节点）
    let time = '';
    let bestLen = 1e9;
    Array.from(el.querySelectorAll('div,span')).forEach((n) => {
      const t = (n.innerText || '').trim();
      if (t && t.length < 40 && TIME_RE.test(t) && t.length < bestLen) { time = t; bestLen = t.length; }
    });

    // like_count：stats 容器第一个数字；reply_count：展开回复按钮 "展开N条回复"
    let likeN = 0, replyN = 0;
    const stats = el.querySelector('.comment-item-stats-container');
    if (stats) likeN = parseCount((stats.innerText || '').split('\n')[0]);
    const expand = el.querySelector('.comment-reply-expand-btn');
    if (expand) {
      const m = (expand.innerText || '').match(/(\d+)\s*条回复/);
      if (m) replyN = parseInt(m[1], 10);
    }

    // content：克隆 item，剥掉已知子树（作者行/头像/统计/标签/展开按钮），剩余即正文+时间；再正则去掉时间串
    let content = '';
    try {
      const clone = el.cloneNode(true);
      clone.querySelectorAll('.comment-item-info-wrap, .comment-item-avatar, .comment-item-stats-container, '
        + '.comment-item-tag, .comment-reply-expand-btn, [id^="tooltip_"]')
        .forEach((n) => n.remove());
      content = (clone.textContent || '').replace(/\s+/g, ' ').trim();
      // 去掉时间串（如 "1年前·山东" / "2025-02-24"）与残留空白
      content = content.replace(time, '').replace(/[0-9]{4}年[0-9]{1,2}月[0-9]{1,2}日/g, '')
                       .replace(/\d+\s*(年前|个月前|天前|小时前|分钟前)/g, '')
                       .replace(/·[\u4e00-\u9fa5]{2,}/g, '').trim();
    } catch (e) {}

    if (!content) return;   // 纯表情/纯标签评论无文字，跳过
    const key = user + '|' + content.slice(0, 40);
    if (seen.has(key)) return;
    seen.add(key);

    out.push({
      comment_id: cid,
      user_name: user,
      content: content,
      like_count: likeN,
      reply_count: replyN,
      time: time,
    });
  });

  // 视频元信息（尽力取）
  const get = (sels) => { for (const s of sels) { const n = document.querySelector(s); if (n && n.innerText && n.innerText.trim()) return n.innerText.trim(); } return ''; };
  const meta = {};
  let t0 = get(['[data-e2e="detail-video-info"]']) || document.title;
  meta.title = t0.split('\n')[0].trim();   // 侧栏统计/举报/发布时间是后续行，只取首行正文
  meta.digg_count = get(['[data-e2e="video-player-digg"]', '[data-e2e="video-like-count"]']);
  meta.author = get(['[data-e2e="video-author-name"]', '[data-e2e="video-author-nickname"]']);
  return { comments: out, meta: meta, item_count: items.length };
}
"""


def collect_from_page(page, vid: str, max_rounds: int, debug: bool) -> dict:
    """在已打开视频页的 page 上：等渲染 -> 温和滚动评论区 -> 抽取。返回 dict(result, block)。"""
    # 等待 SPA 与评论面板
    page.wait_for_timeout(6000)

    block = detect_block(page)
    if block in ("login_wall", "captcha", "not_found"):
        return {"block": block, "comments": [], "meta": {}}

    # 温和滚动：先滚一下整页触发评论懒加载，再针对评论容器滚动
    # 只读滚动，每轮停 2s（人类节奏），默认 6 轮约 30-60 条上限
    prev = -1
    stall = 0
    for i in range(max_rounds):
        page.mouse.wheel(0, 1200)
        page.wait_for_timeout(2000)
        # 针对评论列表容器单独滚（评论区是内部滚动容器）
        try:
            page.evaluate(
                "() => { var b=document.querySelector('[data-e2e=\"comment-list\"]');"
                " if(b){b.scrollTop=b.scrollHeight;} }"
            )
        except Exception:
            pass
        got = page.evaluate(EXTRACT_JS)
        n = len(got.get("comments", []))
        if n == prev:
            stall += 1
        else:
            stall = 0
        prev = n
        if stall >= 2:   # 连续 2 轮无新增即收完
            break

    result = page.evaluate(EXTRACT_JS)
    if debug:
        try:
            dbg = Path.home() / f".cache/multiplatform-media-fetch/{vid}_dom_debug.html"
            dbg.write_text(page.content(), encoding="utf-8")
            print(f"[debug] DOM dump -> {dbg}")
        except Exception:
            pass

    block = detect_block(page) if not result.get("comments") else None
    return {"block": block, "comments": result.get("comments", []), "meta": result.get("meta", {})}


# --------------------------------------------------------------------------- #
# 三级回退采集
# --------------------------------------------------------------------------- #
def run(pi, vid_arg: str, out_dir: Path, max_rounds: int, debug: bool):
    out_dir.mkdir(parents=True, exist_ok=True)
    final = None

    # ---- Tier 1: 匿名 fresh context（无登录态，最安全）----
    tier = None
    try:
        browser = pi.chromium.launch(channel="chrome", headless=False,
                                      args=["--disable-blink-features=AutomationControlled"])
        ctx = browser.new_context(viewport={"width": 1366, "height": 900}, locale="zh-CN")
        page = ctx.new_page()
        page.goto(VIDEO_URL_TMPL.format(vid=vid_arg) if vid_arg.isdigit() else vid_arg,
                  wait_until="domcontentloaded", timeout=45000)
        page.wait_for_timeout(3000)
        live_vid = vid_from_url(page.url) or vid_arg
        res = collect_from_page(page, live_vid, max_rounds, debug)
        tier = "anonymous"
        if res["comments"]:
            final = (live_vid, tier, res)
        else:
            print(f"[douyin] 匿名 tier 无评论（block={res['block']}），回退 Chrome 登录态")
        ctx.close(); browser.close()
    except Exception as e:
        print(f"[douyin] 匿名 tier 异常: {str(e)[:120]}")
        try: browser.close()
        except Exception: pass

    # ---- Tier 2: Chrome persistent profile（复用本 profile 登录态）----
    if final is None:
        try:
            ctx = pi.chromium.launch_persistent_context(
                user_data_dir=str(PROFILE_DIR), channel="chrome", headless=False,
                viewport={"width": 1366, "height": 900}, locale="zh-CN",
                args=["--disable-blink-features=AutomationControlled"],
            )
            page = ctx.pages[0] if ctx.pages else ctx.new_page()
            page.goto(VIDEO_URL_TMPL.format(vid=vid_arg) if vid_arg.isdigit() else vid_arg,
                      wait_until="domcontentloaded", timeout=45000)
            page.wait_for_timeout(3000)
            live_vid = vid_from_url(page.url) or vid_arg
            res = collect_from_page(page, live_vid, max_rounds, debug)
            tier = "chrome_profile"
            if res["comments"]:
                final = (live_vid, tier, res)
            else:
                print(f"[douyin] Chrome profile tier 无评论（block={res['block']}）")
            ctx.close()
        except Exception as e:
            print(f"[douyin] Chrome profile tier 异常: {str(e)[:120]}")

    # ---- Tier 3: 仍失败 -> 落盘状态，不硬闯 ----
    if final is None:
        live_vid = vid_arg if vid_arg.isdigit() else "unknown"
        block = res.get("block") if 'res' in dir() else "empty"
        final = (live_vid, "failed", {"comments": [], "meta": {}, "block": block})

    live_vid, tier, res = final
    comments = res["comments"]
    meta_in = res.get("meta", {})
    block = res.get("block")

    status = "ok" if comments else ("login_wall" if block == "login_wall" else (
        "captcha" if block == "captcha" else ("not_found" if block == "not_found" else "empty")))

    payload = {
        "vid": live_vid,
        "source_url": VIDEO_URL_TMPL.format(vid=live_vid),
        "meta": {
            "title": meta_in.get("title", ""),
            "author": meta_in.get("author", ""),
            "digg_count": meta_in.get("digg_count", ""),
            "comment_total_hint": meta_in.get("comment_total", ""),
            "fetched_at": datetime.now().isoformat(timespec="seconds"),
            "tier_used": tier,
            "status": status,
            "block_reason": block,
        },
        "comment_count": len(comments),
        "comments": comments,
    }

    out_path = out_dir / f"{live_vid}_comments.json"
    out_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[douyin] tier={tier} status={status} 评论 {len(comments)} 条 -> {out_path}")
    if status != "ok":
        print("[douyin] 未取到评论。若为 login_wall/captcha：待人工开窗（浏览器登录抖音后重跑），"
              "或走 references/platforms/douyin-comments-extract.md 的人工浏览器直读法。不硬闯。")
    return payload


def main():
    ap = argparse.ArgumentParser(description="抖音单条视频评论采集（只读 · 低频 · 三级回退）")
    ap.add_argument("video", help="视频 URL 或纯数字 vid")
    ap.add_argument("-o", "--out", default="./douyin_comments")
    ap.add_argument("--max-rounds", type=int, default=6, help="评论区滚动加载轮数（每轮停2s，默认6≈30-60条上限）")
    ap.add_argument("--debug", action="store_true", help="额外 dump 页面 DOM 便于调选择器")
    args = ap.parse_args()

    py = _bootstrap_playwright()
    if not py:
        print("[douyin] 未找到装了 playwright 的 python", file=sys.stderr); sys.exit(2)
    if py != sys.executable:
        import os
        os.execv(py, [py] + sys.argv)

    from playwright.sync_api import sync_playwright
    pi = sync_playwright().start()
    try:
        run(pi, args.video, Path(args.out), args.max_rounds, args.debug)
    finally:
        pi.stop()


if __name__ == "__main__":
    main()
