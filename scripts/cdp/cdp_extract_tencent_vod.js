#!/usr/bin/env node
/**
 * cdp_extract_tencent_vod.js
 *
 * 通过会计知识库的 connectDailyChrome 连接用户 Chrome，
 * 从腾讯云 VOD SimpleAES 加密的 HLS 播放页提取解密参数。
 *
 * 弹窗处理：connectDailyChrome 内部已集成 startPressLoop（后台 800ms
 * 串行点授权弹窗，AXPress，跨进程锁，点中后还焦）。
 *
 * 用法:
 *   node cdp_extract_tencent_vod.js <url_substring> [--out params.json] [--quality 720p|1080p]
 *
 * --quality: 720p(默认,_1.m3u8) 或 1080p(_2.m3u8)
 *
 * 前置:
 *   - Chrome 已开启远程调试 (chrome://inspect/#remote-debugging)
 *   - 视频页面已打开并点过播放
 *   - 会计知识库 connect_browser.js 路径:
 *     ~/Desktop/accounting-kb/code/scripts/cdp/connect_browser.js
 *   - 该仓库 node_modules 已安装 (puppeteer-core)
 */
const fs = require('fs'), os = require('os'), path = require('path');

const args = process.argv.slice(2);
if (args.length < 1) {
  console.error('用法: node cdp_extract_tencent_vod.js <url_substring> [--out params.json]');
  process.exit(1);
}
const urlSubstring = args[0];
let outFile = null;
let quality = '720p';
const outIdx = args.indexOf('--out');
if (outIdx !== -1) outFile = args[outIdx + 1];
const qIdx = args.indexOf('--quality');
if (qIdx !== -1) quality = args[qIdx + 1];

// 复用会计知识库的 CDP 连接模块
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
    console.error('找到页面:', page.url().substring(0, 80));

    const params = await page.evaluate(async (quality) => {
      let hls = null;
      const findHls = (obj, depth) => {
        if (!obj || depth > 5) return null;
        if (obj.hls && obj.hls.config && obj.hls.config.overlayKey !== undefined) return obj.hls;
        for (const k of Object.keys(obj)) {
          try { if (typeof obj[k] === 'object') { const r = findHls(obj[k], depth + 1); if (r) return r; } } catch(e) {}
        }
        return null;
      };
      hls = findHls(window.sfePlayers, 0);
      if (!hls) return { error: 'no hls instance - please click play on the video first' };

      const overlayKey = hls.config.overlayKey;
      const overlayIv = hls.config.overlayIv;

      // 选择码率：720p=_1, 1080p=_2
      const wantTag = quality === '1080p' ? '_2.m3u8' : '_1.m3u8';
      const fallbackTag = quality === '1080p' ? '_1.m3u8' : '_2.m3u8';
      let m3u8Url = null;
      for (const lvl of hls.levels) {
        const u = String(lvl.url || lvl.uri || '');
        if (u.includes(wantTag)) { m3u8Url = u; break; }
      }
      if (!m3u8Url) {
        for (const lvl of hls.levels) {
          const u = String(lvl.url || lvl.uri || '');
          if (u.includes(fallbackTag)) { m3u8Url = u; break; }
        }
      }
      if (!m3u8Url) {
        const l = hls.levels[hls.levels.length - 1];
        m3u8Url = String(l.url || l.uri || '');
      }

      const m3u8Text = await (await fetch(m3u8Url)).text();
      const keyLine = m3u8Text.split('\n').find(l => l.includes('EXT-X-KEY'));
      const uriM = keyLine.match(/URI="([^"]+)"/);
      const ivM = keyLine.match(/IV=0x([a-f0-9]+)/);

      const kr = await fetch(uriM[1]);
      const rk = new Uint8Array(await kr.arrayBuffer());

      const segs = m3u8Text.split('\n').filter(l => l && !l.startsWith('#'));
      const cdnBase = m3u8Url.substring(0, m3u8Url.lastIndexOf('/') + 1);

      return {
        overlayKey, overlayIv,
        responseKey: Array.from(rk).map(b => b.toString(16).padStart(2,'0')).join(''),
        m3u8Iv: ivM[1],
        m3u8Url, cdnBase,
        segments: segs, segmentCount: segs.length,
      };
    }, quality);

    if (outFile) {
      fs.writeFileSync(outFile, JSON.stringify(params, null, 2));
      console.error('参数已写入:', outFile);
    } else {
      console.log(JSON.stringify(params, null, 2));
    }
  } finally {
    await safeDisconnect(browser);
  }
  process.exit(0);
}

main().catch(e => { console.error('错误:', e.message); process.exit(1); });
