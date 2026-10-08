#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
小红书（Xiaohongshu / RedNote）图文/视频/评论/搜索/用户主页采集器。

设计原则（与 multiplatform-media-fetch 其他平台一致）：
- 不逆向 x-s/x-t 签名算法（Spider_XHS 那套太重且经常跟着小红书版本变）；
- 用 Playwright persistent context 复用浏览器登录态，打开笔记页后从 DOM +
  performance entries 抓「直链」，再用 urllib 直接下载——直链不需要 cookie/referer。
- 首次运行打开 xiaohongshu.com 让用户扫码，cookie 持久化在
  ~/.cache/multiplatform-media-fetch/xhs_profile/，之后免登。

CLI:
    python3 xhs_downloader.py note <note_url> [-o out_dir]
    python3 xhs_downloader.py comments <note_url> [-o out_dir]
    python3 xhs_downloader.py search <keyword> [--max 20] [-o out_dir]
    python3 xhs_downloader.py user <user_url> [--max 30] [-o out_dir]
    python3 xhs_downloader.py login

note_url 形如:
    https://www.xiaohongshu.com/explore/<note_id>?xsec_token=xxx&xsec_source=
    https://www.xiaohongshu.com/discovery/item/<note_id>?...
裸 note_id 不带 xsec_token 会被 300031 反爬拦截，必须从首页/搜索点进后复制完整 URL。
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import time
import urllib.request
import urllib.parse
from pathlib import Path

PROFILE_DIR = Path.home() / ".cache" / "multiplatform-media-fetch" / "xhs_profile"
PROFILE_DIR.mkdir(parents=True, exist_ok=True)

XHS_HOME = "https://www.xiaohongshu.com/explore"


# --------------------------------------------------------------------------- #
# Playwright 自举：找一个装了 playwright 的 python
# --------------------------------------------------------------------------- #
def _bootstrap_playwright():
    try:
        from playwright.sync_api import sync_playwright  # noqa: F401
        return sys.executable
    except ImportError:
        pass
    # 找 sandbox python
    candidates = [
        "/Users/wenjiechen/Library/Application Support/Doubao/sandbox_runtime/bases/e74152cd379ba45d7ca7f16dfa51b727/bin/python3",
    ]
    for py in candidates:
        try:
            import subprocess
            r = subprocess.run([py, "-c", "import playwright"], capture_output=True, timeout=10)
            if r.returncode == 0:
                return py
        except Exception:
            continue
    return None


# --------------------------------------------------------------------------- #
# 浏览器 session
# --------------------------------------------------------------------------- #
class XHSSession:
    def __init__(self, headless: bool = False):
        self._bootstrap()
        from playwright.sync_api import sync_playwright
        self._pw = sync_playwright().start()
        launch_kwargs = dict(
            user_data_dir=str(PROFILE_DIR),
            headless=headless,
            viewport={"width": 1280, "height": 900},
            locale="zh-CN",
            args=["--disable-blink-features=AutomationControlled"],
        )
        # 优先用系统 Chrome；没有再退回 playwright 自带 chromium
        try:
            self.context = self._pw.chromium.launch_persistent_context(
                channel="chrome", **launch_kwargs
            )
        except Exception:
            self.context = self._pw.chromium.launch_persistent_context(**launch_kwargs)
        self.page = self.context.pages[0] if self.context.pages else self.context.new_page()

    def _bootstrap(self):
        py = _bootstrap_playwright()
        if py and py != sys.executable:
            os_exec = __import__("os").execv
            os_exec(py, [py] + sys.argv)

    def ensure_login(self):
        """打开首页，若未登录则等用户扫码。"""
        self.page.goto(XHS_HOME, wait_until="domcontentloaded", timeout=30000)
        self.page.wait_for_timeout(3000)
        # 简单判断：页面有没有"登录"弹窗/按钮
        content = self.page.content()
        if "扫码登录" in content or "输入手机号" in content:
            print("[xhs] 检测到未登录，请在打开的浏览器窗口扫码登录...")
            # 等用户登录成功（URL 变化或登录弹窗消失）
            for _ in range(120):
                self.page.wait_for_timeout(2000)
                c = self.page.content()
                if "扫码登录" not in c and "输入手机号" not in c:
                    print("[xhs] 登录成功")
                    return
            raise RuntimeError("登录超时（120秒）")

    def close(self):
        try:
            self.context.close()
        except Exception:
            pass
        self._pw.stop()


# --------------------------------------------------------------------------- #
# 直链下载（不需要 cookie/referer）
# --------------------------------------------------------------------------- #
def download_url(url: str, out_path: Path, headers: dict | None = None) -> int:
    req = urllib.request.Request(url, headers=headers or {})
    with urllib.request.urlopen(req, timeout=60) as resp:
        data = resp.read()
    out_path.write_bytes(data)
    return len(data)


# --------------------------------------------------------------------------- #
# 单条笔记采集
# --------------------------------------------------------------------------- #
def collect_note(session: XHSSession, note_url: str, out_dir: Path) -> dict:
    out_dir.mkdir(parents=True, exist_ok=True)
    page = session.page
    page.goto(note_url, wait_until="domcontentloaded", timeout=30000)
    page.wait_for_timeout(3500)  # 等 SPA 渲染

    # 被 300031 拦截检测
    if "你访问的页面不见了" in page.title() or "404" in page.url:
        raise RuntimeError(
            f"笔记被反爬拦截（300031）。请从浏览器首页/搜索点进笔记后复制完整 URL（必须带 xsec_token）。\nURL: {note_url}"
        )

    # 元数据
    meta = page.evaluate("""
    () => {
        const get = (sel) => document.querySelector(sel)?.innerText?.trim() || '';
        return {
            title: get('#detail-title') || get('.note-content .title') || document.title,
            desc: get('#detail-desc') || get('.note-content .desc') || '',
            author: get('.author-container .username') || get('.username') || '',
            like: get('.like-wrapper .count') || '',
            collect: get('.collect-wrapper .count') || '',
            comment: get('.chat-wrapper .count') || '',
            time: get('.date') || '',
        };
    }
    """)

    # 图片：notes_pre_post 路径
    img_urls = page.evaluate("""
    () => Array.from(document.querySelectorAll('img'))
        .map(i => i.src)
        .filter(s => s && s.includes('notes_pre_post'))
    """)
    img_urls = list(dict.fromkeys(img_urls))

    # 视频：从 performance entries 抓 sns-video mp4
    video_urls = page.evaluate("""
    () => performance.getEntriesByType('resource')
        .map(e => e.name)
        .filter(u => u.includes('sns-video') && u.includes('.mp4'))
    """)
    video_urls = list(dict.fromkeys(video_urls))

    # 笔记 ID 作为子目录
    note_id_m = re.search(r"/explore/([a-f0-9]+)", note_url) or re.search(r"/item/([a-f0-9]+)", note_url)
    note_id = note_id_m.group(1) if note_id_m else "unknown"
    note_dir = out_dir / note_id
    note_dir.mkdir(exist_ok=True)

    # 下载图片
    saved_imgs = []
    for i, u in enumerate(img_urls, 1):
        # 去掉 !xxx webp 后缀，尝试要原图；403 就退回原 webp URL
        base = u.split("!")[0]
        for candidate in [u, base]:
            try:
                ext = ".webp" if candidate.endswith("webp") else ".jpg"
                p = note_dir / f"img_{i:02d}{ext}"
                size = download_url(candidate, p)
                saved_imgs.append({"url": candidate, "path": str(p), "bytes": size})
                break
            except Exception as e:
                print(f"  [warn] 图片下载失败 {candidate[:80]}: {e}")

    # 下载视频
    saved_videos = []
    for i, u in enumerate(video_urls, 1):
        p = note_dir / f"video_{i:02d}.mp4"
        try:
            size = download_url(u, p)
            saved_videos.append({"url": u, "path": str(p), "bytes": size})
        except Exception as e:
            print(f"  [warn] 视频下载失败: {e}")

    result = {
        "note_id": note_id,
        "source_url": note_url,
        "meta": meta,
        "images": saved_imgs,
        "videos": saved_videos,
    }
    (note_dir / "meta.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return result


# --------------------------------------------------------------------------- #
# 评论采集
# --------------------------------------------------------------------------- #
def collect_comments(session: XHSSession, note_url: str, out_dir: Path) -> list:
    out_dir.mkdir(parents=True, exist_ok=True)
    page = session.page
    page.goto(note_url, wait_until="domcontentloaded", timeout=30000)
    page.wait_for_timeout(3000)

    # 滚动评论区加载更多
    for _ in range(5):
        page.mouse.wheel(0, 1500)
        page.wait_for_timeout(1200)

    comments = page.evaluate("""
    () => {
      const out = [];
      const seen = new Set();
      document.querySelectorAll('.comment-item, .parent-comment').forEach(el => {
        const userLink = el.querySelector('a[href*="/user/profile/"]');
        const user = userLink ? userLink.innerText.trim() : '';
        const content = el.querySelector('.note-text, .comment-content, .content')?.innerText?.trim() || '';
        const like = el.querySelector('.like-container .count, .like-wrapper .count, .like--MdAxq')?.innerText?.trim() || '';
        const time = el.querySelector('.time, .date, .when')?.innerText?.trim() || '';
        const key = user + '|' + content;
        if (content && !seen.has(key)) { seen.add(key); out.push({user, content, like, time}); }
      });
      return out;
    }
    """)
    note_id = re.search(r"/(?:explore|item)/([a-f0-9]+)", note_url)
    note_id = note_id.group(1) if note_id else "unknown"
    p = out_dir / f"{note_id}_comments.json"
    p.write_text(json.dumps(comments, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[xhs] 抓到 {len(comments)} 条评论 -> {p}")
    return comments


# --------------------------------------------------------------------------- #
# 搜索
# --------------------------------------------------------------------------- #
def search_notes(session: XHSSession, keyword: str, max_n: int = 20, out_dir: Path | None = None):
    page = session.page
    url = f"https://www.xiaohongshu.com/search_result?keyword={urllib.parse.quote(keyword)}&source=web_explore_feed"
    page.goto(url, wait_until="domcontentloaded", timeout=30000)
    page.wait_for_timeout(4000)  # 等搜索结果渲染

    results = []
    seen = set()
    # 小红书搜索结果卡片是 section.note-item，笔记 id 在 data-note-id 属性或 cover div 上
    for _ in range(max(3, max_n // 8)):
        page.mouse.wheel(0, 1500)
        page.wait_for_timeout(1800)
        batch = page.evaluate("""
        () => {
          const out = [];
          document.querySelectorAll('section.note-item, [data-note-id]').forEach(el => {
            const nid = el.getAttribute('data-note-id') || '';
            if (!nid) return;
            const title = el.querySelector('.title, .note-title, a.title')?.innerText?.trim() || '';
            const author = el.querySelector('.author .name, .name')?.innerText?.trim() || '';
            const like = el.querySelector('.like-count, .count')?.innerText?.trim() || '';
            out.push({note_id: nid, title, author, like});
          });
          return out;
        }
        """)
        for n in batch:
            nid = n["note_id"]
            if nid in seen: continue
            seen.add(nid)
            # 搜索页拿到的是 note_id，xsec_token 需要后续从点进去时获取
            n["url"] = f"https://www.xiaohongshu.com/explore/{nid}"
            results.append(n)
            if len(results) >= max_n: break
        if len(results) >= max_n: break

    if out_dir:
        out_dir.mkdir(parents=True, exist_ok=True)
        p = out_dir / f"search_{keyword[:20]}.json"
        p.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"[xhs] 搜索 '{keyword}' 命中 {len(results)} 条 -> {p}")
        print("      注意：拿到的是 note_id 列表，下载详情时需从浏览器点进笔记补 xsec_token")
    return results


# --------------------------------------------------------------------------- #
# 用户主页
# --------------------------------------------------------------------------- #
def user_notes(session: XHSSession, user_url: str, max_n: int = 30, out_dir: Path | None = None):
    page = session.page
    page.goto(user_url, wait_until="domcontentloaded", timeout=30000)
    page.wait_for_timeout(4000)

    results = []
    seen = set()
    for _ in range(max(3, max_n // 8)):
        page.mouse.wheel(0, 1500)
        page.wait_for_timeout(1800)
        batch = page.evaluate("""
        () => {
          const out = [];
          document.querySelectorAll('section.note-item, [data-note-id]').forEach(el => {
            const nid = el.getAttribute('data-note-id') || '';
            if (!nid) return;
            const title = el.querySelector('.title, .note-title')?.innerText?.trim() || '';
            out.push({note_id: nid, title});
          });
          return out;
        }
        """)
        for n in batch:
            nid = n["note_id"]
            if nid in seen: continue
            seen.add(nid)
            n["url"] = f"https://www.xiaohongshu.com/explore/{nid}"
            results.append(n)
            if len(results) >= max_n: break
        if len(results) >= max_n: break

    if out_dir:
        out_dir.mkdir(parents=True, exist_ok=True)
        p = out_dir / "user_notes.json"
        p.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"[xhs] 用户主页 {len(results)} 条笔记 -> {p}")
    return results


# --------------------------------------------------------------------------- #
# 我的收藏（登录态私有数据）
# --------------------------------------------------------------------------- #
def my_favorites(session: XHSSession, max_n: int = 100, out_dir: Path | None = None):
    """抓取当前登录账号的「我的收藏」列表。"""
    page = session.page

    # 1. 打开首页，从导航栏拿当前登录用户的 profile URL
    page.goto(XHS_HOME, wait_until="domcontentloaded", timeout=30000)
    page.wait_for_timeout(3500)

    profile_url = page.evaluate("""
    () => {
      // 导航栏里指向 /user/profile/ 的链接通常就是当前用户主页
      const a = document.querySelector('a[href*="/user/profile/"]');
      return a ? a.href : '';
    }
    """)
    if not profile_url:
        raise RuntimeError("未找到当前登录用户主页链接——可能未登录或页面结构变了。请先跑 login。")

    # 清理 query，只保留 profile 路径
    profile_url = profile_url.split("?")[0]
    print(f"[xhs] 当前登录用户主页: {profile_url}")

    # 2. 打开个人主页，点「收藏」tab
    page.goto(profile_url, wait_until="domcontentloaded", timeout=30000)
    page.wait_for_timeout(3500)

    # 点"收藏"tab（按钮文字含"收藏"）
    clicked = page.evaluate("""
    () => {
      const tabs = Array.from(document.querySelectorAll('a, div, span, button'));
      const fav = tabs.find(el => el.innerText && el.innerText.trim() === '收藏');
      if (fav) { fav.click(); return true; }
      return false;
    }
    """)
    if clicked:
        print("[xhs] 已切到「收藏」tab")
        page.wait_for_timeout(3000)
    else:
        print("[xhs] 未找到「收藏」tab 按钮，尝试 URL 直接带 tab 参数")
        sep = "&" if "?" in profile_url else "?"
        page.goto(f"{profile_url}{sep}tab=fav", wait_until="domcontentloaded", timeout=30000)
        page.wait_for_timeout(3500)

    # 3. 滚动加载收藏列表
    results = []
    seen = set()
    for _ in range(max(4, max_n // 10)):
        page.mouse.wheel(0, 1800)
        page.wait_for_timeout(1800)
        batch = page.evaluate("""
        () => {
          const out = [];
          document.querySelectorAll('section.note-item, [data-note-id]').forEach(el => {
            const nid = el.getAttribute('data-note-id') || '';
            if (!nid) return;
            const title = el.querySelector('.title, .note-title, a.title')?.innerText?.trim() || '';
            const author = el.querySelector('.author .name, .name')?.innerText?.trim() || '';
            out.push({note_id: nid, title, author});
          });
          return out;
        }
        """)
        for n in batch:
            nid = n["note_id"]
            if nid in seen: continue
            seen.add(nid)
            n["url"] = f"https://www.xiaohongshu.com/explore/{nid}"
            results.append(n)
            if len(results) >= max_n: break
        if len(results) >= max_n: break

    if out_dir:
        out_dir.mkdir(parents=True, exist_ok=True)
        p = out_dir / "my_favorites.json"
        p.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"[xhs] 我的收藏共 {len(results)} 条 -> {p}")
        print("      注意：拿到的是 note_id + 标题列表，下载详情时需从浏览器点进笔记补 xsec_token")
    return results


# --------------------------------------------------------------------------- #
# 收藏详情批量抓取（2026-10-05 v6 方案内置：滚动加载→同帧点击→内联提取）
# --------------------------------------------------------------------------- #
def collect_favorite_details(session: XHSSession, fav_list: list, out_dir: Path, max_scroll: int = 12) -> list:
    """对收藏列表逐条抓详情：滚动直到卡片出现→同帧 scrollIntoView+点击可见 a→等 token→当前页内联提取。

    失效笔记识别：点击不到卡片 / 点击后无 token / 详情为空 → 标记 deleted_or_private，
    这类通常是作者已删除/下架/转私密（收藏页仍显示占位，但原文不可达）。
    返回带 status 的列表；详情（图/视频/meta）落在 out_dir/<note_id>/。
    """
    out_dir.mkdir(parents=True, exist_ok=True)
    results = []
    profile_url = None

    def open_fav():
        nonlocal profile_url
        if profile_url is None:
            session.page.goto(XHS_HOME, wait_until="domcontentloaded", timeout=30000)
            session.page.wait_for_timeout(3500)
            profile_url = session.page.evaluate(
                """() => {
                  const a = document.querySelector('a[href*="/user/profile/"]');
                  return a ? a.href.split('?')[0] : '';
                }"""
            )
            if not profile_url:
                raise RuntimeError("未找到当前登录用户主页——请先 login")
        session.page.goto(profile_url, wait_until="domcontentloaded", timeout=30000)
        session.page.wait_for_timeout(3500)
        session.page.evaluate(
            """() => {
              const tabs = Array.from(document.querySelectorAll('a, div, span, button'));
              const fav = tabs.find(el => el.innerText && el.innerText.trim() === '收藏');
              if (fav) { fav.click(); return true; }
              return false;
            }"""
        )
        session.page.wait_for_timeout(3000)

    def scroll_until(nid):
        for _ in range(max_scroll):
            found = session.page.evaluate(
                """(nid) => !!document.querySelector(`section.note-item[data-note-id="${nid}"]`)""", nid
            )
            if found:
                return True
            session.page.mouse.wheel(0, 2000)
            session.page.wait_for_timeout(1800)
        return False

    def click_target(nid):
        return session.page.evaluate(
            """(nid) => {
                const card = document.querySelector(`section.note-item[data-note-id="${nid}"]`);
                if (!card) return 0;
                card.scrollIntoView({block:'center'});
                const visA = Array.from(card.querySelectorAll('a')).find(a => a.offsetParent !== null);
                if (visA) { visA.click(); return 2; }
                const img = card.querySelector('img');
                if (img) { img.click(); return 3; }
                card.click(); return 4;
            }""",
            nid,
        )

    def extract_inline(nid):
        """当前已打开的详情页内联提取（不 goto 二次访问，token 二次访问会渲染为空）。"""
        data = session.page.evaluate("""
        () => {
            const get = (sel) => document.querySelector(sel)?.innerText?.trim() || '';
            const imgs = Array.from(document.querySelectorAll('img'))
                .map(i => i.src).filter(u => u && u.includes('notes_pre_post'));
            const vids = performance.getEntriesByType('resource')
                .map(e => e.name).filter(u => u.includes('sns-video') && u.includes('.mp4'));
            return {
                title: get('#detail-title') || get('.note-content .title') || document.title,
                desc: get('#detail-desc') || get('.note-content .desc') || '',
                author: get('.author-container .username') || get('.username') || '',
                like: get('.like-wrapper .count') || '',
                collect: get('.collect-wrapper .count') || '',
                imgs: Array.from(new Set(imgs)),
                vids: Array.from(new Set(vids)),
            };
        }
        """)
        note_dir = out_dir / nid
        note_dir.mkdir(parents=True, exist_ok=True)
        saved_imgs, saved_vids = [], []
        for i, u in enumerate(dict.fromkeys(data["imgs"]), 1):
            base = u.split("!")[0]
            for cand in [u, base]:
                try:
                    ext = ".webp" if cand.endswith("webp") else ".jpg"
                    p = note_dir / f"img_{i:02d}{ext}"
                    download_url(cand, p)
                    saved_imgs.append(p.name)
                    break
                except Exception:
                    continue
        for i, u in enumerate(dict.fromkeys(data["vids"]), 1):
            try:
                p = note_dir / f"video_{i:02d}.mp4"
                download_url(u, p)
                saved_vids.append(p.name)
            except Exception:
                continue
        data["saved_imgs"] = saved_imgs
        data["saved_vids"] = saved_vids
        (note_dir / "meta.json").write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        return data

    for i, item in enumerate(fav_list, 1):
        nid = item["note_id"]
        label = item.get("title", "")[:30]
        print(f"[xhs] 收藏详情 [{i}/{len(fav_list)}] {label}", flush=True)
        open_fav()
        if not scroll_until(nid):
            item["status"] = "deleted_or_private"
            item["detail"] = "收藏页滚动未出现该卡片（原文已删除/下架/私密）"
            print("      → 失效（卡片不存在）", flush=True)
            results.append(item)
            continue
        r = click_target(nid)
        if r == 0:
            item["status"] = "deleted_or_private"
            item["detail"] = "卡片存在但点击失败（疑似失效占位）"
            print("      → 点击失败", flush=True)
            results.append(item)
            continue
        cur = session.page.url
        if len(session.context.pages) > 1:
            session.page = session.context.pages[-1]
            cur = session.page.url
        got_token = False
        for _ in range(12):
            if "xsec_token" in cur and nid in cur:
                got_token = True
                break
            session.page.wait_for_timeout(1500)
            cur = session.page.url
        if not got_token:
            item["status"] = "no_token"
            item["detail"] = cur[:120]
            print("      → 无 token（已失效或页面异常）", flush=True)
            results.append(item)
            try:
                if len(session.context.pages) > 1:
                    session.page.close()
                    session.page = session.context.pages[0]
            except Exception:
                pass
            continue
        session.page.wait_for_timeout(3500)
        try:
            data = extract_inline(nid)
            item["status"] = "ok"
            item["title"] = data.get("title", item.get("title", ""))
            item["author"] = data.get("author", item.get("author", ""))
            item["imgs"] = len(data.get("saved_imgs", []))
            item["vids"] = len(data.get("saved_vids", []))
            item["detail"] = out_dir / nid
            print(f"      → OK | 图 {item['imgs']} | 视频 {item['vids']}", flush=True)
        except Exception as e:
            item["status"] = "extract_err"
            item["detail"] = str(e)[:120]
            print(f"      → 提取异常 {str(e)[:80]}", flush=True)
        try:
            if len(session.context.pages) > 1:
                session.page.close()
                session.page = session.context.pages[0]
        except Exception:
            pass
        results.append(item)

    return results


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #
def main():
    ap = argparse.ArgumentParser(description="小红书图文/视频/评论/搜索采集")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p_note = sub.add_parser("note", help="下载单条笔记（图片+视频）")
    p_note.add_argument("url")
    p_note.add_argument("-o", "--out", default="./xhs_downloads")

    p_comm = sub.add_parser("comments", help="抓单条笔记评论")
    p_comm.add_argument("url")
    p_comm.add_argument("-o", "--out", default="./xhs_downloads")

    p_search = sub.add_parser("search", help="搜索关键词")
    p_search.add_argument("keyword")
    p_search.add_argument("--max", type=int, default=20)
    p_search.add_argument("-o", "--out", default="./xhs_downloads")

    p_user = sub.add_parser("user", help="采集用户主页笔记列表")
    p_user.add_argument("url")
    p_user.add_argument("--max", type=int, default=30)
    p_user.add_argument("-o", "--out", default="./xhs_downloads")

    p_fav = sub.add_parser("favorites", help="抓取当前登录账号的「我的收藏」列表；--with-detail 连详情一起抓")
    p_fav.add_argument("--max", type=int, default=100)
    p_fav.add_argument("-o", "--out", default="./xhs_downloads")
    p_fav.add_argument("--with-detail", action="store_true",
                       help="列表抓完后逐条抓详情（滚动加载→点击→内联提取）；失效笔记标记 deleted_or_private")

    sub.add_parser("login", help="扫码登录（cookie 自动持久化）")

    args = ap.parse_args()

    s = XHSSession(headless=False)
    try:
        s.ensure_login()
        if args.cmd == "note":
            r = collect_note(s, args.url, Path(args.out))
            print(f"[xhs] 完成: {r['note_id']} | 图 {len(r['images'])} 张 | 视频 {len(r['videos'])} 个")
            print(f"      标题: {r['meta'].get('title','')}")
        elif args.cmd == "comments":
            collect_comments(s, args.url, Path(args.out))
        elif args.cmd == "search":
            search_notes(s, args.keyword, args.max, Path(args.out))
        elif args.cmd == "user":
            user_notes(s, args.url, args.max, Path(args.out))
        elif args.cmd == "favorites":
            favs = my_favorites(s, args.max, Path(args.out))
            if getattr(args, "with_detail", False):
                print("[xhs] 开始逐条抓收藏详情（--with-detail）...")
                favs = collect_favorite_details(s, favs, Path(args.out))
                detail_p = Path(args.out) / "favorites_details.json"
                detail_p.write_text(json.dumps(favs, ensure_ascii=False, indent=2), encoding="utf-8")
                ok_n = sum(1 for f in favs if f.get("status") == "ok")
                dead_n = sum(1 for f in favs if f.get("status") == "deleted_or_private")
                print(f"[xhs] 收藏详情完成：ok {ok_n} | 失效 {dead_n} | 其他 {len(favs)-ok_n-dead_n} -> {detail_p}")
        elif args.cmd == "login":
            print("[xhs] 登录态已就绪")
    finally:
        s.close()


if __name__ == "__main__":
    main()
