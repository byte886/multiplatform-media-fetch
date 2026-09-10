#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
多平台音视频下载器（基于 yt-dlp Python API），可在任意任务窗口运行。
支持：YouTube / 哔哩哔哩（含裸 BV 号）/ 抖音（含纯数字 ID）。

可移植性：本脚本不依赖某个项目的虚拟环境。若当前解释器没装 yt_dlp，
会自动按以下顺序寻找一个“装了 yt_dlp 的 Python”并用它重入自身：
    1) 环境变量 YTDLP_PYTHON
    2) 全局命令 `yt-dlp` 可执行文件 shebang 指向的解释器
    3) PATH 上的 python3 / python
    4) ~/Doubao/chats 下各项目 .venv
也可直接用一个已装 yt-dlp 的解释器显式运行：
    /path/to/python media_downloader.py URL --audio

各平台自动策略（已内置）：
■ YouTube：自动走本机代理（探测常见端口）+ node/deno/bun JS 运行时 + ejs:github 远程挑战组件；
  多语言音轨默认优选“原声 original”、避开 AI 自动配音(dubbed-auto，如同 itag 的 -0)，可用 --audio-lang 指定语言
■ 哔哩哔哩：强制直连（走代理会 412）+ 真实 UA/Referer + 请求间隔 + 默认限速 2MiB/s，默认不带 Cookie
■ 抖音：强制直连；Cookie 默认匿名设备票据 ttwid（公开视频免登录、免开 Chrome），匿名被拒自动回退 Chrome；
  其流均为音视频合一、无独立音轨，--audio 自动用 ffmpeg 无损抽出 m4a，--smallest 按体积挑最小含音频流

CLI 示例：
    python3 media_downloader.py "https://www.youtube.com/watch?v=ID" --audio
    python3 media_downloader.py BV1N64xzKEfA --audio --smallest
    python3 media_downloader.py "76581310654023716147" --audio --audio-format mp3
    python3 media_downloader.py URL --quality 720
    python3 media_downloader.py URL --list-formats
"""
import argparse
import glob
import os
import re
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path


# --------------------------------------------------------------------------- #
# 解释器自举：在任意窗口都能找到装了 yt_dlp 的 Python
# --------------------------------------------------------------------------- #
def _python_can_import(py: str, module: str = "yt_dlp") -> bool:
    try:
        r = subprocess.run([py, "-c", f"import {module}"],
                           capture_output=True, timeout=20)
        return r.returncode == 0
    except Exception:
        return False


def _shebang_python(cli_path: str):
    """从一个可执行脚本（如 /usr/local/bin/yt-dlp）的 shebang 解析其解释器。"""
    try:
        first = Path(cli_path).read_text(errors="ignore").splitlines()[0]
        if not first.startswith("#!"):
            return None
        parts = first[2:].strip().split()
        if parts and parts[0].endswith("/env"):
            parts = parts[1:]
        return parts[0] if parts else None
    except Exception:
        return None


def _candidate_pythons():
    cands = []
    env = os.environ.get("YTDLP_PYTHON")
    if env:
        cands.append(env)
    cli = shutil.which("yt-dlp")
    if cli:
        sp = _shebang_python(cli)
        if sp:
            cands.append(sp)
    for name in ("python3", "python"):
        p = shutil.which(name)
        if p:
            cands.append(p)
    home = str(Path.home())
    for pat in (f"{home}/Doubao/chats/*/*/.venv/bin/python",
                f"{home}/Doubao/chats/*/*/*/.venv/bin/python",
                f"{home}/.venv/bin/python", f"{home}/venv/bin/python"):
        cands.extend(sorted(glob.glob(pat)))
    return cands


def bootstrap_ytdlp():
    try:
        import yt_dlp  # noqa: F401
        return  # 当前解释器可用
    except ImportError:
        pass
    seen = set()
    for py in _candidate_pythons():
        if not py or py in seen:
            continue
        seen.add(py)
        if not Path(py).exists() or not os.access(py, os.X_OK):
            continue
        if _python_can_import(py, "yt_dlp"):
            # 重入“真正的入口脚本”：直接运行本文件时是 __file__；被其它脚本
            # （如 fetch_for_article.py）import 时，sys.argv[0] 是调用方脚本，
            # 必须重入它而不是本文件，否则会错误地跑成下载器主程序。
            entry = sys.argv[0] if sys.argv else ""
            entry_abs = os.path.abspath(entry) if entry else ""
            if entry_abs.endswith(".py") and Path(entry_abs).is_file():
                print(f"[bootstrap] 改用带 yt-dlp 的解释器：{py}", flush=True)
                os.execv(py, [py, entry_abs, *sys.argv[1:]])
            # python -c / -m / stdin 等没有真实脚本入口，无法安全重入：放弃自举
            return
    sys.exit(
        "缺少依赖 yt-dlp，且未找到任何已安装它的 Python。\n"
        "解决：python3 -m pip install -U yt-dlp（或 brew install yt-dlp / pipx install yt-dlp）；\n"
        "也可设置环境变量 YTDLP_PYTHON 指向一个已装 yt-dlp 的解释器。"
    )


bootstrap_ytdlp()

import yt_dlp  # noqa: E402
from yt_dlp.utils import DownloadError  # noqa: E402


# 真实浏览器 UA（如过期可换成自己浏览器的 UA）
CHROME_UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/138.0.0.0 Safari/537.36"
)

# 本机常见代理端口（Clash/ClashVerge/V2Ray 等），可用环境变量 MEDIA_FETCH_PROXY 覆盖
PROXY_PORT_CANDIDATES = (7890, 7897, 1087, 1080, 8889)

RISK_STATUS_CODES = ("412", "429")

_JS_RUNTIME_CANDIDATES = {
    "deno": ("/usr/local/bin/deno", "/opt/homebrew/bin/deno"),
    "node": ("/usr/local/bin/node", "/opt/homebrew/bin/node"),
    "bun": ("/usr/local/bin/bun", "/opt/homebrew/bin/bun"),
}


def detect_platform(url: str) -> str:
    u = url.strip()
    if re.fullmatch(r"BV[0-9A-Za-z]{10}", u):
        return "bilibili"
    if re.fullmatch(r"\d{15,25}", u):
        return "douyin"
    low = u.lower()
    if any(d in low for d in ("youtube.com", "youtu.be", "yt.be")):
        return "youtube"
    if any(d in low for d in ("bilibili.com", "b23.tv", "bili")):
        return "bilibili"
    if any(d in low for d in ("douyin.com", "iesdouyin.com", "douyin")):
        return "douyin"
    return "generic"


def normalize_url(url: str, platform: str) -> str:
    u = url.strip()
    if platform == "bilibili" and re.fullmatch(r"BV[0-9A-Za-z]{10}", u):
        return f"https://www.bilibili.com/video/{u}/"
    if platform == "douyin" and re.fullmatch(r"\d{15,25}", u):
        return f"https://www.douyin.com/video/{u}"
    return u


def detect_js_runtime():
    for name in ("deno", "node", "bun"):
        for candidate in _JS_RUNTIME_CANDIDATES[name]:
            if Path(candidate).exists():
                return {name: {"path": candidate}}
        on_path = shutil.which(name)
        if on_path:
            return {name: {"path": on_path}}
    return None


def _port_alive(host: str = "127.0.0.1", port: int = 7890, timeout: float = 0.3) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def detect_local_proxy():
    """返回可用的本机代理 URL；环境变量优先，其次探测常见端口，都没有返回 None。"""
    env = os.environ.get("MEDIA_FETCH_PROXY")
    if env:
        return env
    for port in PROXY_PORT_CANDIDATES:
        if _port_alive(port=port):
            return f"http://127.0.0.1:{port}"
    return None


def _progress_hook(status: dict) -> None:
    if status["status"] == "downloading":
        print(f"\r下载中 {status.get('_percent_str','').strip()}  "
              f"速度 {status.get('_speed_str','').strip()}", end="", flush=True)
    elif status["status"] == "finished":
        print("\n下载流完成，开始后处理（合并/转码）...")


def _base_opts(output_dir: Path, platform: str, proxy=None, no_proxy=False,
               browser=None, browser_profile=None, cookie_file=None,
               limit_rate=None, gentle=True, use_ejs=True) -> dict:
    output_dir.mkdir(parents=True, exist_ok=True)
    opts = {
        "outtmpl": str(output_dir / "%(title)s [%(id)s].%(ext)s"),
        "progress_hooks": [_progress_hook],
        "ignoreerrors": "only_download",
        "noprogress": True,
        "retries": 5,
        "fragment_retries": 5,
    }

    if no_proxy:
        opts["proxy"] = ""
    elif proxy is not None:
        opts["proxy"] = proxy
    elif platform == "youtube":
        found = detect_local_proxy()
        if found:
            opts["proxy"] = found
            print(f"[网络] YouTube 自动走本机代理 {found}")
        else:
            print("[网络] 未探测到本机代理，直连尝试；若被拦请开代理或用 --proxy / 环境变量 MEDIA_FETCH_PROXY")
    else:
        opts["proxy"] = ""
        print("[网络] 国内平台，强制直连（绕过系统代理）")

    if platform == "youtube":
        js_runtime = detect_js_runtime()
        if js_runtime:
            opts["js_runtimes"] = js_runtime
        if use_ejs:
            opts["remote_components"] = ("ejs:github",)
    elif platform == "bilibili":
        opts["http_headers"] = {
            "User-Agent": CHROME_UA,
            "Referer": "https://www.bilibili.com/",
        }
        opts["retries"] = 1
        opts["fragment_retries"] = 1
        if gentle:
            opts.update({"sleep_requests": 2, "sleep_interval": 3,
                         "max_sleep_interval": 8})
        if limit_rate is None:
            opts["ratelimit"] = 2 * 1024 * 1024
        elif limit_rate > 0:
            opts["ratelimit"] = limit_rate
    elif platform == "douyin":
        opts["http_headers"] = {
            "User-Agent": CHROME_UA,
            "Referer": "https://www.douyin.com/",
        }
        if gentle:
            opts.update({"sleep_requests": 2, "sleep_interval": 3,
                         "max_sleep_interval": 8})
        if limit_rate is not None and limit_rate > 0:
            opts["ratelimit"] = limit_rate

    if limit_rate is not None and limit_rate > 0 and "ratelimit" not in opts:
        opts["ratelimit"] = limit_rate

    if cookie_file:
        opts["cookiefile"] = cookie_file
    elif browser:
        opts["cookiesfrombrowser"] = (
            (browser, browser_profile) if browser_profile else (browser,))
    return opts


# --------------------------------------------------------------------------- #
# 抖音 Cookie 策略：匿名设备票据 ttwid 优先（公开视频免登录、免开 Chrome），
# 匿名不足时才回退复用 Chrome 登录态。2026-09-07 实测：公开视频仅需匿名 ttwid。
# --------------------------------------------------------------------------- #
_TTWID_URL = "https://ttwid.bytedance.com/ttwid/union/register/"
_TTWID_BODY = (b'{"region":"cn","aid":1768,"needFid":false,'
               b'"service":"https://www.douyin.com",'
               b'"migrate_info":{"ticket":"","source":"node"},'
               b'"cbUrlProtocol":"https","union":true}')
_TTWID_CACHE = Path(tempfile.gettempdir()) / ".mediafetch_douyin_ttwid.txt"
_TTWID_TTL = 30 * 86400  # ttwid 本身约一年有效，本地缓存 30 天主动刷新
# 会话/鉴权类错误（区别于 412/429 限流）：只有这类才值得回退到浏览器登录态
_SESSION_MARKERS = ("fresh cookies", "not necessarily logged in", "login required",
                    "sign in", "log in", "web detail", "403", "forbidden")


def _fetch_ttwid():
    """向字节票据端点匿名注册一枚 ttwid（国内直连、禁用环境代理，无需登录/浏览器）。"""
    try:
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        req = urllib.request.Request(
            _TTWID_URL, data=_TTWID_BODY, method="POST",
            headers={"Content-Type": "application/json", "User-Agent": CHROME_UA})
        with opener.open(req, timeout=15) as resp:
            for sc in (resp.headers.get_all("Set-Cookie") or []):
                if sc.startswith("ttwid="):
                    return sc.split(";", 1)[0][len("ttwid="):]
    except Exception as exc:  # 网络异常等静默降级，由上层决定备选路径
        print(f"[Cookie] 匿名 ttwid 获取失败：{exc}")
    return None


def _anonymous_ttwid_cookiefile():
    """返回匿名 ttwid 的 Netscape cookie 文件路径（带 30 天本地缓存）；失败返回 None。"""
    try:
        if _TTWID_CACHE.exists() and \
                time.time() - _TTWID_CACHE.stat().st_mtime < _TTWID_TTL:
            return str(_TTWID_CACHE)
    except OSError:
        pass
    ttwid = _fetch_ttwid()
    if not ttwid:
        return None
    try:
        expiry = int(time.time()) + 31536000
        _TTWID_CACHE.write_text(
            "# Netscape HTTP Cookie File (anonymous douyin ttwid, auto-generated)\n"
            f".douyin.com\tTRUE\t/\tFALSE\t{expiry}\tttwid\t{ttwid}\n")
        _TTWID_CACHE.chmod(0o600)  # 仅匿名设备票据、非账号凭据，仍收紧权限
        return str(_TTWID_CACHE)
    except OSError as exc:
        print(f"[Cookie] 写入匿名 ttwid 缓存失败：{exc}")
        return None


def _douyin_cookie_plan(browser, cookie_file, no_browser_cookies, browser_profile):
    """返回 (mode, effective_cookie_file, effective_browser)。
    user=用户显式指定，不干预；anon=匿名优先、会话类失败自动回退 Chrome；
    anon_only=只用匿名、绝不读浏览器；browser=匿名不可用时直接用 Chrome 兜底。"""
    if cookie_file or browser:
        return "user", cookie_file, browser
    anon = _anonymous_ttwid_cookiefile()
    if no_browser_cookies:
        return "anon_only", anon, None
    if anon:
        print("[Cookie] 抖音使用匿名设备票据 ttwid（公开视频免登录；需要登录的内容会自动回退 Chrome）")
        return "anon", anon, None
    print("[Cookie] 匿名 ttwid 不可用，回退复用 Chrome 登录态")
    return "browser", None, (browser or "chrome")


def _is_session_error(exc) -> bool:
    text = str(exc).lower()
    if any(code in text for code in RISK_STATUS_CODES):  # 412/429 限流不靠换 cookie 解决
        return False
    return any(marker in text for marker in _SESSION_MARKERS)


def _ydl_run(url, opts, platform, mode, browser_profile):
    """执行下载。抖音 anon（匿名 ttwid 优先）模式下：首试用严格模式强制抛出，
    若是会话/鉴权类失败则自动回退复用 Chrome 登录态重试一次；限流类不靠换 cookie。
    （_base_opts 的 ignoreerrors='only_download' 会把解析错误转成返回码而不抛出，
      故匿名首试必须显式关掉它，否则捕获不到、回退不生效。）"""
    def _run(local_opts):
        with yt_dlp.YoutubeDL(local_opts) as ydl:
            return ydl.download([url])

    if mode == "anon" and platform == "douyin":
        first = dict(opts)
        first["ignoreerrors"] = False  # 强制抛出，便于判断失败类型
        try:
            return _run(first)
        except DownloadError as exc:
            if not _is_session_error(exc):
                return _risk_advice(exc, platform)  # 412/429 等限流：换 cookie 无用
            print("[Cookie] 匿名票据不足（该视频可能需登录或被校验），自动回退复用 Chrome 登录态重试…")
            fallback = dict(opts)
            fallback.pop("cookiefile", None)
            fallback["cookiesfrombrowser"] = (
                ("chrome", browser_profile) if browser_profile else ("chrome",))
            try:
                return _run(fallback)
            except DownloadError as exc2:
                return _risk_advice(exc2, platform)

    try:
        return _run(opts)
    except DownloadError as exc:
        return _risk_advice(exc, platform)


def _resolve_browser(platform, browser, cookie_file, no_browser_cookies):
    # 非抖音平台：仅在用户显式指定时带浏览器 cookie；抖音默认策略见 _douyin_cookie_plan
    if browser or cookie_file:
        return browser
    return None


def _risk_advice(exc, platform) -> int:
    text = str(exc)
    if any(code in text for code in RISK_STATUS_CODES):
        print("\n" + "=" * 64)
        print("⚠️  触发平台风控（HTTP 412/429）。这是临时限流，不是封号。")
        if platform == "bilibili":
            print("  1) 立即停止，冷却 10~30 分钟（严重时数小时），勿反复重试；")
            print("  2) 确保下载器直连（本脚本已强制直连），代理软件应为 bilibili.com 配直连；")
            print("  3) 公开音视频不要加 --browser；大会员清晰度才需要。")
        else:
            print("  等待后重试；YouTube 可加 --browser chrome 并确认代理可用。")
        print("=" * 64)
        return 14
    print(f"\n下载失败：{text}")
    return 1


# --------------------------------------------------------------------------- #
# YouTube 多语言音轨：默认优选“原声 original”，避开 AI 自动配音(dubbed-auto)。
# 2026-09-07 实测：同一 itag 会有 251-0=en-US 自动配音、251-1=zh-Hant 原声，
# --smallest 只按体积挑会误中 -0 英文配音，转写出来成了英文。故先探格式再确定性选轨。
# --------------------------------------------------------------------------- #
def _audio_candidates(info):
    fmts = info.get("formats") or []
    audio_only = [f for f in fmts
                  if f.get("acodec") not in (None, "none")
                  and f.get("vcodec") in (None, "none")]
    # 没有纯音轨（个别合一流场景）时放宽到所有含音频的流
    return audio_only or [f for f in fmts if f.get("acodec") not in (None, "none")]


def _pick_youtube_audio(info, smallest=False, audio_lang=None):
    """确定性挑一条 YouTube 音轨，返回 (format_id, 带判定标记的候选行)；挑不出返回 (None, [])。
    指定 --audio-lang：该语言最优先；否则原声(original/default)优先、自动配音(dub/translated)靠后；
    同档内 --smallest 按体积/码率升序(最省流量)，否则按码率降序(质量最好)。"""
    rows = []
    for f in _audio_candidates(info):
        note = (f.get("format_note") or "").lower()
        lang = (f.get("language") or "").lower()
        rows.append({
            "id": f.get("format_id"),
            "lang": f.get("language") or "-",
            "note": f.get("format_note") or "-",
            "tbr": f.get("tbr") or f.get("abr") or 0,
            "size": f.get("filesize") or f.get("filesize_approx") or 0,
            "dub": ("dub" in note) or ("translat" in note),
            "orig": ("original" in note) or ("default" in note),
            "langmatch": bool(audio_lang) and lang.startswith(audio_lang.lower()),
        })
    if not rows:
        return None, []

    def lang_block(r):
        if audio_lang:
            return (0 if r["langmatch"] else 1,)
        return (1 if r["dub"] else 0, 0 if r["orig"] else 1)

    def quality(r):
        return (r["size"], r["tbr"]) if smallest else (-r["tbr"], -r["size"])

    rows.sort(key=lambda r: (lang_block(r), quality(r)))
    return rows[0]["id"], rows


def _probe_and_pick_youtube_audio(url, *, proxy, no_proxy, browser, browser_profile,
                                  cookie_file, use_ejs, smallest, audio_lang):
    """探测 YouTube 格式并选出音轨；任何异常都返回 (None, []) 让上层回退通用选流，不阻断下载。"""
    try:
        probe = _base_opts(Path("."), "youtube", proxy=proxy, no_proxy=no_proxy,
                           browser=browser, browser_profile=browser_profile,
                           cookie_file=cookie_file, gentle=False, use_ejs=use_ejs)
        probe.update({"quiet": True, "no_warnings": True, "skip_download": True})
        with yt_dlp.YoutubeDL(probe) as ydl:
            info = ydl.extract_info(url, download=False)
        fid, rows = _pick_youtube_audio(info, smallest=smallest, audio_lang=audio_lang)
        if not fid:
            return None, []
        print(f"[音轨] 检测到 {len(rows)} 条音轨：")
        for r in rows:
            tags = []
            if r["langmatch"]:
                tags.append("指定语言")
            if r["orig"]:
                tags.append("原声")
            if r["dub"]:
                tags.append("自动配音")
            print(f"   - {str(r['id']):<8} lang={str(r['lang']):<8} "
                  f"tbr={int(r['tbr']):<5} {r['note']} {'/'.join(tags)}")
        chosen = next(r for r in rows if r["id"] == fid)
        if audio_lang:
            why = f"指定语言 {audio_lang}"
        elif chosen["orig"] and not chosen["dub"]:
            why = "原声优先、避开自动配音"
        else:
            why = "无明确原声标注，取最优"
        multi = len({r["lang"] for r in rows}) > 1
        print(f"[音轨] 选中 {fid}（{why}）。" +
              ("该视频含多语言音轨，已默认选原声；要自动配音/其它语言用 --audio-lang（如 en）。"
               if multi and not audio_lang else ""))
        return fid, rows
    except Exception as exc:  # 探测失败不致命，回退到 format 选择器字符串
        print(f"[音轨] YouTube 音轨探测失败（{exc}），回退通用选流。")
        return None, []


def download_video(url, output_dir="downloads", quality="best", proxy=None,
                   no_proxy=False, playlist=False, browser=None,
                   browser_profile=None, cookie_file=None, limit_rate=None,
                   use_ejs=True, no_browser_cookies=False) -> int:
    platform = detect_platform(url)
    url = normalize_url(url, platform)
    output_dir = Path(output_dir).expanduser()
    print(f"[平台] 识别为 {platform}：{url}")
    if platform == "douyin":
        mode, cookie_file, browser = _douyin_cookie_plan(
            browser, cookie_file, no_browser_cookies, browser_profile)
    else:
        browser = _resolve_browser(platform, browser, cookie_file, no_browser_cookies)
        mode = "user" if (browser or cookie_file) else "none"
    fmt = ("bestvideo*+bestaudio/best" if quality == "best"
           else f"bestvideo[height<={quality}]+bestaudio/best[height<={quality}]/best")
    opts = _base_opts(output_dir, platform, proxy=proxy, no_proxy=no_proxy,
                      browser=browser, browser_profile=browser_profile,
                      cookie_file=cookie_file, limit_rate=limit_rate,
                      use_ejs=use_ejs)
    opts.update({"format": fmt, "merge_output_format": "mp4",
                 "noplaylist": not playlist})
    return _ydl_run(url, opts, platform, mode, browser_profile)


def download_audio(url, output_dir="downloads", audio_format=None,
                   audio_quality="0", smallest=False, proxy=None,
                   no_proxy=False, playlist=False, browser=None,
                   browser_profile=None, cookie_file=None, limit_rate=None,
                   no_browser_cookies=False, use_ejs=True,
                   audio_lang=None) -> int:
    platform = detect_platform(url)
    url = normalize_url(url, platform)
    output_dir = Path(output_dir).expanduser()
    print(f"[平台] 识别为 {platform}：{url}")
    if platform == "douyin":
        mode, cookie_file, browser = _douyin_cookie_plan(
            browser, cookie_file, no_browser_cookies, browser_profile)
    else:
        browser = _resolve_browser(platform, browser, cookie_file, no_browser_cookies)
        mode = "user" if (browser or cookie_file) else "none"
    if smallest:
        # 转写够用：先找纯音轨里最小的；没有纯音轨（抖音全是合一流）时，
        # 用 [acodec!=none] 取出"所有含音频流"候选，交给 format_sort 按体积/码率挑最小。
        # 注意不能用 worst——它直接锁定单项，format_sort 会无候选可排。
        fmt = "worstaudio/[acodec!=none]"
        print("[格式] 选择最小音轨（转写够用模式）")
    else:
        fmt = "bestaudio/best[acodec!=none]/best"
    # 抖音 web API 只给音视频合一 mp4、没有 audio-only 流：不抽轨就只会得到 mp4。
    # 用户未指定格式时，自动把合一流里的 aac 无损 remux 成 m4a（流复制、不重编码）。
    NO_AUDIO_ONLY_PLATFORMS = {"douyin"}
    eff_format = audio_format
    auto_extract = platform in NO_AUDIO_ONLY_PLATFORMS and eff_format is None
    if auto_extract:
        eff_format = "m4a"
        print("[格式] 抖音无独立音轨，自动从合一视频中无损抽取音轨 → m4a"
              "（要 mp3/wav 等用 --audio-format 指定）")
    # YouTube 多语言音轨：先探测并锁定"原声"format_id，避免 best/worst 跨语言误选自动配音。
    picked_id = None
    if platform == "youtube":
        picked_id, _ = _probe_and_pick_youtube_audio(
            url, proxy=proxy, no_proxy=no_proxy, browser=browser,
            browser_profile=browser_profile, cookie_file=cookie_file,
            use_ejs=use_ejs, smallest=smallest, audio_lang=audio_lang)
    opts = _base_opts(output_dir, platform, proxy=proxy, no_proxy=no_proxy,
                      browser=browser, browser_profile=browser_profile,
                      cookie_file=cookie_file, limit_rate=limit_rate,
                      use_ejs=use_ejs)
    # picked_id 是精确音轨 id；探测失败才回退到通用 format 选择器字符串
    opts.update({"format": picked_id or fmt, "noplaylist": not playlist})
    if smallest and not picked_id:
        # --smallest 服务转写（抖音等单语言平台）：在"含音频"的候选里按 体积→码率→分辨率 升序挑最省流量的。
        # 抖音全是音视频合一流，分辨率序 ≠ 体积序（720p 水印流反而比 540p h265 大），
        # 不显式按体积排会多下载流量。YouTube 已精确选定音轨时无需此排序。
        opts["format_sort"] = ["+filesize_approx", "+filesize", "+tbr", "+res"]
    if eff_format:
        if not shutil.which("ffmpeg"):
            print("[失败] 抽取音频需要 ffmpeg，但 PATH 中未找到。"
                  "请先安装（macOS: brew install ffmpeg）后重试。")
            return 127
        opts["postprocessors"] = [{
            "key": "FFmpegExtractAudio",
            "preferredcodec": eff_format,
            "preferredquality": audio_quality,
        }]
    else:
        print("[格式] 保留原始音频容器，不二次转码（需要 mp3 加 --audio-format mp3）")
    return _ydl_run(url, opts, platform, mode, browser_profile)


def list_formats(url, proxy=None, no_proxy=False, browser=None,
                 cookie_file=None, use_ejs=True, no_browser_cookies=False,
                 browser_profile=None):
    platform = detect_platform(url)
    url = normalize_url(url, platform)
    print(f"[平台] 识别为 {platform}：{url}")
    if platform == "douyin":
        mode, cookie_file, browser = _douyin_cookie_plan(
            browser, cookie_file, no_browser_cookies, browser_profile)
    else:
        browser = _resolve_browser(platform, browser, cookie_file, no_browser_cookies)
        mode = "user" if (browser or cookie_file) else "none"
    base = _base_opts(Path("."), platform, proxy=proxy, no_proxy=no_proxy,
                      browser=browser, browser_profile=browser_profile,
                      cookie_file=cookie_file, gentle=False,
                      use_ejs=use_ejs)
    allow = ("proxy", "js_runtimes", "remote_components", "cookiesfrombrowser",
             "cookiefile", "http_headers")
    opts = {"quiet": False, "listformats": True}
    opts.update({k: v for k, v in base.items() if k in allow})
    return _ydl_run(url, opts, platform, mode, browser_profile)


# --------------------------------------------------------------------------- #
# 字幕：探测 / 中文优先选轨 / 只下载字幕（不出媒体）
# 优先级：手动中文(简中>繁中) > 手动其他(en 优先) > 自动中文 > 自动其他
# --------------------------------------------------------------------------- #
SUBTITLE_ZH_PREF = ("zh-hans", "zh-cn", "zh-sg", "zh", "zh-hant", "zh-hk", "zh-tw")
SUBTITLE_OTHER_PREF = ("en", "en-us", "en-gb", "ja", "ko", "fr", "de", "es")
SUBTITLE_TEXT_EXTS = ("srt", "vtt", "ttml", "json3")


def _lang_rank(lang: str):
    l = (lang or "").lower()
    if l.startswith("zh"):
        order = {k: i for i, k in enumerate(SUBTITLE_ZH_PREF)}
        return (0, order.get(l, 3))
    for i, x in enumerate(SUBTITLE_OTHER_PREF):
        if l == x or l.startswith(x + "-"):
            return (1, i)
    return (2, l)


def probe_info(url, *, proxy=None, no_proxy=False, browser=None,
               browser_profile=None, cookie_file=None, use_ejs=True,
               no_browser_cookies=False):
    """只解析不下载，返回 (info, platform)，用于先看字幕/音轨/语言再决定下什么。"""
    platform = detect_platform(url)
    url = normalize_url(url, platform)
    if platform == "douyin":
        _mode, cookie_file, browser = _douyin_cookie_plan(
            browser, cookie_file, no_browser_cookies, browser_profile)
    else:
        browser = _resolve_browser(platform, browser, cookie_file, no_browser_cookies)
    base = _base_opts(Path("."), platform, proxy=proxy, no_proxy=no_proxy,
                      browser=browser, browser_profile=browser_profile,
                      cookie_file=cookie_file, gentle=False, use_ejs=use_ejs)
    base.update({"quiet": True, "no_warnings": True, "skip_download": True})
    with yt_dlp.YoutubeDL(base) as ydl:
        return ydl.extract_info(url, download=False), platform


def choose_subtitle(info: dict):
    """从 info 里按优先级选一条字幕，返回 {lang,kind(manual/auto),ext,all_exts} 或 None。"""
    def best(group, kind):
        if not group:
            return None
        for lg in sorted(group.keys(), key=_lang_rank):
            tracks = [t for t in (group[lg] or []) if t.get("url")]
            if not tracks:
                continue
            exts = [t.get("ext") for t in tracks]
            ext = next((e for e in SUBTITLE_TEXT_EXTS if e in exts), exts[0])
            return {"lang": lg, "kind": kind, "ext": ext, "all_exts": exts}
        return None

    # 手动中文 > 手动其他 > 自动中文 > 自动其他：对 manual/auto 各取最优后按规则比较
    cand_m = best(info.get("subtitles") or {}, "manual")
    cand_a = best(info.get("automatic_captions") or {}, "auto")
    cands = [c for c in (cand_m, cand_a) if c]
    if not cands:
        return None
    cands.sort(key=lambda c: (0 if c["kind"] == "manual" else 1, _lang_rank(c["lang"])))
    return cands[0]


def list_subtitles(url, **kw):
    """打印某视频可用的手动/自动字幕语言清单。"""
    info, platform = probe_info(url, **kw)
    manual, auto = info.get("subtitles") or {}, info.get("automatic_captions") or {}
    print(f"[字幕] {platform}｜{info.get('title','')}")
    print("  手动字幕：", ", ".join(sorted(manual.keys(), key=_lang_rank)) or "无")
    print("  自动字幕：", ", ".join(sorted(auto.keys(), key=_lang_rank)) or "无")
    pick = choose_subtitle(info)
    if pick:
        print(f"  → 默认会选：{pick['lang']}（{'手动' if pick['kind']=='manual' else '自动'}，{pick['ext']}）")
    else:
        print("  → 无任何字幕，将走音频转写分支")
    return pick


def download_subtitles(url, output_dir="downloads", *, proxy=None, no_proxy=False,
                       browser=None, browser_profile=None, cookie_file=None,
                       use_ejs=True, no_browser_cookies=False, to_srt=True):
    """只下载字幕、不下载媒体。返回 {pick, files:[...]}；无字幕返回 None。"""
    info, platform = probe_info(
        url, proxy=proxy, no_proxy=no_proxy, browser=browser,
        browser_profile=browser_profile, cookie_file=cookie_file,
        use_ejs=use_ejs, no_browser_cookies=no_browser_cookies)
    pick = choose_subtitle(info)
    if not pick:
        return None
    out = Path(output_dir).expanduser()
    out.mkdir(parents=True, exist_ok=True)
    before = {p.name for p in out.glob("*")}
    opts = _base_opts(out, platform, proxy=proxy, no_proxy=no_proxy,
                      browser=browser, browser_profile=browser_profile,
                      cookie_file=cookie_file, gentle=False, use_ejs=use_ejs)
    opts.update({
        "skip_download": True,
        "writesubtitles": True,
        "writeautomaticsub": True,
        "subtitleslangs": [pick["lang"]],
        "subtitlesformat": "srt/vtt/ttml/best",
        "quiet": False,
    })
    if to_srt:
        opts["postprocessors"] = [{
            "key": "FFmpegSubtitlesConvertor", "format": "srt"}]
    print(f"[字幕] 下载 {pick['lang']}（{'手动' if pick['kind']=='manual' else '自动生成'}），不下载音视频")
    with yt_dlp.YoutubeDL(opts) as ydl:
        ydl.download([info.get("webpage_url") or url])
    new_files = sorted((p for p in out.glob("*") if p.name not in before),
                       key=lambda p: p.stat().st_mtime, reverse=True)
    sub_files = [p for p in new_files if p.suffix.lower() in (".srt", ".vtt", ".ttml")]
    return {"pick": pick, "files": [str(p) for p in sub_files], "info": {
        "title": info.get("title"), "id": info.get("id"),
        "duration": info.get("duration"),
        "language": info.get("language")}}


def build_arg_parser():
    p = argparse.ArgumentParser(
        description="多平台音视频下载器（YouTube/B站/抖音自动防风控）",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter)
    p.add_argument("url", help="链接，或 B站裸 BV 号 / 抖音纯数字 ID")
    p.add_argument("-o", "--output-dir", default="downloads")
    p.add_argument("--quality", default="best",
                   help="视频清晰度上限 best 或 360/480/720/1080/1440/2160")
    p.add_argument("--audio", action="store_true", help="只下载音频")
    p.add_argument("--audio-format", default=None,
                   help="mp3/m4a/opus/wav/flac；不指定则保留原始容器")
    p.add_argument("--smallest", action="store_true", help="选最小音轨（转写够用）")
    p.add_argument("--audio-lang", default=None,
                   help="YouTube 多音轨时指定语言（如 en、zh-Hant）；默认优选原声、避开自动配音")
    p.add_argument("--proxy", default=None, help="显式代理，如 http://127.0.0.1:7890")
    p.add_argument("--no-proxy", action="store_true", help="强制直连")
    p.add_argument("--playlist", action="store_true", help="下载整个播放列表")
    p.add_argument("--browser", default=None,
                   help="复用浏览器 Cookie：chrome/edge/firefox/safari")
    p.add_argument("--browser-profile", default=None, help="浏览器配置名，如 'Profile 1'")
    p.add_argument("--no-browser-cookies", action="store_true",
                   help="关闭抖音默认的 Chrome Cookie 复用")
    p.add_argument("--cookies", dest="cookie_file", default=None,
                   help="Netscape cookies.txt 路径")
    p.add_argument("--limit-rate", type=int, default=None,
                   help="限速 KiB/s，默认 B站 2048；0=不限")
    p.add_argument("--list-formats", action="store_true", help="只列格式不下载")
    p.add_argument("--list-subs", action="store_true", help="只列出可用字幕语言（中文优先）不下载")
    p.add_argument("--subs", action="store_true",
                   help="只下载字幕（中文优先、自动转 srt），不下载音视频")
    p.add_argument("--no-ejs", action="store_true", help="关闭 YouTube ejs 远程组件")
    return p


def main():
    args = build_arg_parser().parse_args()
    quality = args.quality
    if quality != "best":
        try:
            quality = int(quality)
        except ValueError:
            sys.exit("--quality 必须是 best 或整数（如 1080）")
    limit_rate = None
    if args.limit_rate is not None:
        limit_rate = max(args.limit_rate, 0) * 1024
    use_ejs = not args.no_ejs

    if args.list_formats:
        list_formats(args.url, proxy=args.proxy, no_proxy=args.no_proxy,
                     browser=args.browser, cookie_file=args.cookie_file,
                     use_ejs=use_ejs,
                     no_browser_cookies=args.no_browser_cookies,
                     browser_profile=args.browser_profile)
        return

    sub_kw = dict(proxy=args.proxy, no_proxy=args.no_proxy, browser=args.browser,
                  browser_profile=args.browser_profile, cookie_file=args.cookie_file,
                  use_ejs=use_ejs, no_browser_cookies=args.no_browser_cookies)
    if args.list_subs:
        list_subtitles(args.url, **sub_kw)
        return
    if args.subs:
        got = download_subtitles(args.url, args.output_dir, **sub_kw)
        if not got:
            print("[字幕] 该视频没有可用字幕（请改走音频转写：去掉 --subs、加 --audio --smallest）")
            sys.exit(3)
        for f in got["files"]:
            print(f"[字幕] 已保存: {f}")
        return

    common = dict(output_dir=args.output_dir, proxy=args.proxy,
                  no_proxy=args.no_proxy, playlist=args.playlist,
                  browser=args.browser, browser_profile=args.browser_profile,
                  cookie_file=args.cookie_file, limit_rate=limit_rate,
                  use_ejs=use_ejs,
                  no_browser_cookies=args.no_browser_cookies)
    if args.audio:
        code = download_audio(args.url, audio_format=args.audio_format,
                              smallest=args.smallest, audio_lang=args.audio_lang,
                              **common)
    else:
        code = download_video(args.url, quality=quality, **common)
    sys.exit(code)


if __name__ == "__main__":
    main()
