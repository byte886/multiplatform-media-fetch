#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
B 站（Bilibili）单条视频评论采集器（只读 · 游客 buvid · 直连）。

设计原则（与 collect_douyin_comments.py 同套纪律）：
- 只读：只拉评论列表，不点赞/回复/关注/发评论；
- 低频串行：一次一条视频，评论翻页 ≤2 页，单会话总量克制；
- 直连：B 站走代理出口会 412，全程强制不走代理；
- 不写死任何凭证：游客 buvid3/buvid4 每次会话从 x/frontend/finger/spi 现取，
  不读本机登录 Cookie、不落盘 SESSDATA（评论列表游客可读，无需登录）。

路线：纯 HTTP API（不启浏览器），比 DOM 直读更轻更稳：
  1) GET x/frontend/finger/spi           -> buvid3/buvid4（游客设备指纹）
  2) GET x/web-interface/view?bvid=...   -> aid + 视频元信息
  3) GET x/v2/reply?type=1&oid=<aid>&pn=1&sort=1  -> 热门评论列表

CLI:
    python3 collect_bilibili_comments.py <bvid_or_avid_or_url> [-o out_dir] [--pages N]

输入形如：
    https://www.bilibili.com/video/BV1kK4y1w7UN
    BV1kK4y1w7UN
    av887900068            （avid 数字，开头 av）

输出：<out_dir>/<bvid>_comments.json
  meta: bvid / aid / source_url / title / owner / view / like / reply_total / fetched_at / status
  comments[]: comment_id / user_name / content / like_count / reply_count / time(ISO+原始ctime)
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import time
import urllib.request
import http.cookiejar
from datetime import datetime, timezone, timedelta

UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
      "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36")
REFERER = "https://www.bilibili.com/"
CST = timezone(timedelta(hours=8))   # B 站时间戳转 UTC+8


def _opener():
    # 关键：ProxyHandler({}) 强制直连，B 站走代理出口必 412
    return urllib.request.build_opener(urllib.request.ProxyHandler({}))


def _get_json(opener, url, cookie=""):
    headers = {"User-Agent": UA, "Referer": REFERER}
    if cookie:
        headers["Cookie"] = cookie
    req = urllib.request.Request(url, headers=headers)
    with opener.open(req, timeout=20) as r:
        return json.loads(r.read().decode())


def resolve_buvid(opener):
    spi = _get_json(opener, "https://api.bilibili.com/x/frontend/finger/spi")
    if spi.get("code") != 0:
        raise RuntimeError(f"取 buvid 失败: {spi.get('message')}")
    return spi["data"]["b_3"], spi["data"]["b_4"]


def resolve_video(opener, cookie, video_arg):
    """返回 (bvid, aid, meta_dict)。支持 bvid / av<aid> / URL。"""
    bv = ""
    m = re.search(r"(BV[0-9A-Za-z]{10})", video_arg)
    if m:
        bv = m.group(1)
    av = None
    m2 = re.search(r"av(\d+)", video_arg, re.I)
    if m2:
        av = m2.group(1)

    if bv:
        view = _get_json(opener, f"https://api.bilibili.com/x/web-interface/view?bvid={bv}", cookie)
    elif av:
        view = _get_json(opener, f"https://api.bilibili.com/x/web-interface/view?aid={av}", cookie)
    else:
        raise RuntimeError(f"无法从输入解析 bvid/aid: {video_arg}")

    if view.get("code") != 0:
        raise RuntimeError(f"解析视频失败 code={view.get('code')} msg={view.get('message')}")
    d = view["data"]
    meta = {
        "title": d.get("title", ""),
        "owner": d.get("owner", {}).get("name", ""),
        "view": d.get("stat", {}).get("view"),
        "like": d.get("stat", {}).get("like"),
        "reply_total": d.get("stat", {}).get("reply"),
        "pubdate": d.get("pubdate"),
    }
    return d.get("bvid", bv), d["aid"], meta


def fetch_comments(opener, cookie, aid, pages):
    """拉前 N 页热门评论（每页停 1.5s 人类节奏，只读）。返回 comments 列表。"""
    out = []
    for pn in range(1, pages + 1):
        url = f"https://api.bilibili.com/x/v2/reply?type=1&oid={aid}&pn={pn}&sort=1"
        rep = _get_json(opener, url, cookie)
        if rep.get("code") != 0:
            print(f"[bili] p{pn} code={rep.get('code')} msg={rep.get('message')}")
            break
        replies = (rep.get("data") or {}).get("replies") or []
        if not replies:
            break
        for c in replies:
            out.append({
                "comment_id": str(c.get("rpid", "")),
                "user_name": c.get("member", {}).get("uname", ""),
                "content": c.get("content", {}).get("message", ""),
                "like_count": c.get("like", 0),
                "reply_count": c.get("rcount", 0),
                "time": datetime.fromtimestamp(c.get("ctime", 0), CST).strftime("%Y-%m-%d %H:%M"),
                "ctime": c.get("ctime", 0),
            })
        if pn < pages:
            time.sleep(1.5)   # 低频，页间停 1.5s
    return out


def main():
    ap = argparse.ArgumentParser(description="B 站单条视频评论采集（游客 buvid · 直连 · 只读）")
    ap.add_argument("video", help="bvid / av<aid> / 视频 URL")
    ap.add_argument("-o", "--out", default="./bilibili_comments")
    ap.add_argument("--pages", type=int, default=2, help="评论翻页（每页20条，默认2页≈40条上限）")
    args = ap.parse_args()

    import os
    out_dir = os.path.abspath(args.out)
    os.makedirs(out_dir, exist_ok=True)

    opener = _opener()
    status = "ok"
    comments = []
    meta = {}
    try:
        b3, b4 = resolve_buvid(opener)
        cookie = f"buvid3={b3}; buvid4={b4}"
        bvid, aid, meta = resolve_video(opener, cookie, args.video)
        comments = fetch_comments(opener, cookie, aid, args.pages)
        if not comments:
            status = "empty"
    except Exception as e:
        status = "error"
        meta["error"] = str(e)

    payload = {
        "bvid": bvid if 'bvid' in dir() else "",
        "aid": aid if 'aid' in dir() else None,
        "source_url": f"https://www.bilibili.com/video/{bvid}" if 'bvid' in dir() else args.video,
        "meta": {
            "title": meta.get("title", ""),
            "owner": meta.get("owner", ""),
            "view": meta.get("view"),
            "like": meta.get("like"),
            "reply_total": meta.get("reply_total"),
            "fetched_at": datetime.now(CST).isoformat(timespec="seconds"),
            "tier": "visitor_api",
            "status": status,
        },
        "comment_count": len(comments),
        "comments": comments,
    }
    name = bvid if payload["bvid"] else "unknown"
    out_path = os.path.join(out_dir, f"{name}_comments.json")
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
    print(f"[bili] status={status} 评论 {len(comments)} 条 -> {out_path}")
    if status == "error":
        print(f"[bili] 失败原因: {meta.get('error')}")


if __name__ == "__main__":
    main()
