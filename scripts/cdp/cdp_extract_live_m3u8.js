#!/usr/bin/env node
/**
 * cdp_extract_live_m3u8.js
 *
 * 通过 CDP 连接外部 Chrome，从任意 HLS 直播/点播页面提取 m3u8 播放地址。
 * 通用方法：不依赖特定播放器对象，通过 performance entries 找 m3u8 请求。
 *
 * 适用场景：
 *   - 直播流（blob: URL + MSE，无 sfePlayers）
 *   - 普通 HLS 点播（无 DRM 加密）
 *   - 需要从已登录的 Chrome 标签页提取带鉴权的流地址
 *
 * 用法:
 *   node cdp_extract_live_m3u8.js <url_substring> [--out params.json]
 *
 * 输出 JSON:
 *   { m3u8Url, encrypted, headers, cookies, segmentCount }
 */
const fs = require('fs'), os = require('os'), path = require('path');

const args = process.argv.slice(2);
if (args.length < 1) {
  console.error('用法: node cdp_extract_live_m3u8.js <url_substring> [--out params.json]');
  process.exit(1);
}
const urlSubstring = args[0];
let outFile = null;
const outIdx = args.indexOf('--out');
if (outIdx !== -1) outFile = args[outIdx + 1];

const CONNECT_PATH = path.join(
  os.homedir(),
  'Desktop/accounting-kb/code/scripts/cdp/connect_browser.js'
);

async function main() {
  const { connectDailyChrome, findPage, safeDisconnect } = require(CONNECT_PATH);

  console.error('连接 Chrome...');
  const browser = await connectDailyChrome({ ensureRunning: false, timeoutMs: 30000 });

  try {
    const page = await findPage(browser, urlSubstring);
    if (!page) {
      console.error('未找到包含 "' + urlSubstring + '" 的标签页');
      const pages = await browser.pages();
      for (const p of pages) {
        try { console.error('  -', p.url()); } catch (e) {}
      }
      process.exit(1);
    }
    console.error('找到页面:', page.url().substring(0, 100));

    // 触发播放
    await page.evaluate(() => {
      const videos = document.querySelectorAll('video');
      videos.forEach(v => { v.muted = true; v.play().catch(() => {}); });
      const btns = document.querySelectorAll('.vjs-big-play-button, .play-button, [class*="play"]');
      btns.forEach(b => b.click());
    });
    console.error('已触发播放，等待 5 秒...');
    await new Promise(r => setTimeout(r, 5000));

    // 提取 m3u8 URL 和必要的请求头
    const result = await page.evaluate(() => {
      // 1. 从 performance entries 找 m3u8
      const entries = performance.getEntriesByType('resource');
      const m3u8Urls = entries
        .map(e => e.name)
        .filter(u => u.includes('.m3u8'));

      // 2. 获取当前页面的 cookie 和 referer
      const cookies = document.cookie;
      const referer = window.location.href;
      const userAgent = navigator.userAgent;

      return { m3u8Urls, cookies, referer, userAgent };
    });

    if (!result.m3u8Urls || result.m3u8Urls.length === 0) {
      console.error('未找到 m3u8 请求。请确认视频已在播放。');
      process.exit(1);
    }

    // 取最新的 m3u8（通常是媒体播放列表，不是 master playlist）
    const m3u8Url = result.m3u8Urls[result.m3u8Urls.length - 1];

    // fetch m3u8 内容判断是否加密
    const m3u8Text = await page.evaluate(async (url) => {
      try {
        const r = await fetch(url);
        return await r.text();
      } catch(e) {
        return 'FETCH_ERROR:' + e.message;
      }
    }, m3u8Url);

    const hasKey = m3u8Text.includes('EXT-X-KEY');
    const lines = m3u8Text.split('\n');
    const segs = lines.filter(l => l && !l.startsWith('#'));

    const output = {
      m3u8Url,
      allM3u8Urls: result.m3u8Urls,
      encrypted: hasKey,
      cookies: result.cookies,
      referer: result.referer,
      userAgent: result.userAgent,
      segmentCount: segs.length,
      segments: segs.slice(0, 5),
      m3u8Preview: lines.slice(0, 15)
    };

    if (outFile) {
      fs.writeFileSync(outFile, JSON.stringify(output, null, 2));
      console.error('参数已写入:', outFile);
    } else {
      console.log(JSON.stringify(output, null, 2));
    }
  } finally {
    await safeDisconnect(browser);
  }
  process.exit(0);
}

main().catch(e => { console.error('错误:', e.message); process.exit(1); });
