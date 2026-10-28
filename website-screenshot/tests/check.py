"""Local checks of src.shot against a local test site. Usage (from the Actor folder): python -m tests.check

Set LOCAL_CHROME to a Chromium binary if Playwright's own browser is not installed.
"""
import asyncio
import functools
import http.server
import io
import os
import sys
import threading

import pypdfium2 as pdfium
from PIL import Image
from playwright.async_api import async_playwright

from src.shot import ShotError, capture, device_options

PAGES = {
    '/long.html': """<html><body style="margin:0">
        <div id="hero" style="height:600px;background:#00f">hero</div>
        <div style="height:3000px;background:linear-gradient(#0f0,#ff0)"></div>
        <div id="cookie-banner" style="position:fixed;bottom:0;left:0;right:0;height:120px;background:#f00">We use cookies</div>
        <img id="lazy" loading="lazy" src="/pixel.png" style="width:50px;height:50px">
        </body></html>""",
    '/dark.html': """<html><head><style>body{background:#fff} @media (prefers-color-scheme: dark){body{background:#000}}
        </style></head><body style="height:400px"></body></html>""",
    '/embeds-private.html': """<html><body style="background:#0f0"><img src="http://10.0.0.1/x.png">
        <img src="http://169.254.169.254/latest/meta-data/"></body></html>""",
}
PRIVATE = {'10.0.0.1', '169.254.169.254', 'private.test'}


class Handler(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == '/pixel.png':
            buf = io.BytesIO()
            Image.new('RGB', (1, 1), 'white').save(buf, 'PNG')
            body, ctype = buf.getvalue(), 'image/png'
        elif self.path in PAGES:
            body, ctype = PAGES[self.path].encode(), 'text/html'
        else:
            self.send_error(404)
            return
        self.send_response(200)
        self.send_header('Content-Type', ctype)
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *a):
        pass


async def host_ok(host):
    return host not in PRIVATE


OPTS = {'format': 'png', 'fullPage': True, 'selector': '', 'waitUntil': 'load', 'delayMs': 0, 'scroll': True,
        'hideBanners': True, 'css': '', 'quality': 85, 'timeoutSecs': 20, 'pdfFormat': 'A4', 'pdfLandscape': False,
        'pdfScreenMedia': False, 'pdfMargin': '10mm'}


async def main():
    srv = http.server.ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    base = f'http://127.0.0.1:{srv.server_address[1]}'
    bad = 0

    def check(name, cond, info=''):
        nonlocal bad
        bad += not cond
        print(f"{'OK ' if cond else 'BAD'} {name} {info}")

    async with async_playwright() as pw:
        kw = {'executable_path': os.environ['LOCAL_CHROME']} if os.environ.get('LOCAL_CHROME') else {}
        browser = await pw.chromium.launch(**kw)
        desk = device_options(pw, 'desktop', 0, 0, False)
        shot = functools.partial(capture, browser, desk, host_ok=host_ok)
        img = lambda r: Image.open(io.BytesIO(r['data'])).convert('RGB')  # noqa: E731

        r = await shot({'url': base + '/long.html'}, OPTS)
        im = img(r)
        check('full page png', r['contentType'] == 'image/png' and im.height >= 3600 and im.width == 1920,
              f'{im.size}, status {r["status"]}')
        check('cookie banner hidden', r['bannersHidden'] == 1 and im.getpixel((960, 1020))[0] < 200,
              f'pixel {im.getpixel((960, 1020))}')
        r = await shot({'url': base + '/long.html'}, {**OPTS, 'fullPage': False, 'hideBanners': False})
        im = img(r)
        check('viewport only, banner kept', im.size == (1920, 1080) and im.getpixel((960, 1020)) == (255, 0, 0),
              f'{im.size} {im.getpixel((960, 1020))}')
        r = await shot({'url': base + '/long.html'}, {**OPTS, 'selector': '#hero', 'format': 'jpeg'})
        im = img(r)
        check('selector #hero as jpeg', r['contentType'] == 'image/jpeg' and im.size == (1920, 600), str(im.size))
        try:
            await shot({'url': base + '/long.html'}, {**OPTS, 'selector': '#nope'})
            check('missing selector -> error', False)
        except ShotError as e:
            check('missing selector -> error', True, str(e))
        r = await shot({'url': base + '/long.html'}, {**OPTS, 'format': 'webp', 'fullPage': False})
        check('webp', r['data'][:4] == b'RIFF' and r['data'][8:12] == b'WEBP')
        r = await shot({'url': base + '/long.html'}, {**OPTS, 'format': 'pdf'})
        pdf = pdfium.PdfDocument(r['data'])
        check('pdf A4, several pages', r['data'][:4] == b'%PDF' and len(pdf) >= 3
              and abs(pdf[0].get_width() - 595) < 2, f'{len(pdf)} pages, width {pdf[0].get_width():.0f}')
        mob = device_options(pw, 'mobile', 0, 0, False)
        r = await capture(browser, mob, {'url': base + '/long.html'}, {**OPTS, 'fullPage': False}, host_ok)
        check('mobile iPhone 15 Pro (393 css px x3)', img(r).width == 1179, str(img(r).size))
        dark = device_options(pw, 'desktop', 800, 600, True)
        r = await capture(browser, dark, {'url': base + '/dark.html'}, {**OPTS, 'fullPage': False}, host_ok)
        check('dark mode + custom viewport', img(r).getpixel((10, 10)) == (0, 0, 0) and img(r).size == (800, 600))
        r = await shot({'html': '<h1 style="color:#f00">Hello</h1><title>T1</title>'}, {**OPTS, 'fullPage': False})
        check('raw HTML input', r['title'] == 'T1' and r['status'] is None)
        r = await shot({'url': base + '/embeds-private.html'}, OPTS)
        check('private sub-requests blocked', r['blockedRequests'] == 2, f'{r["blockedRequests"]}')
        r = await shot({'html': '<img src="http://169.254.169.254/latest/meta-data/">'}, OPTS)
        check('private request from raw HTML blocked', r['blockedRequests'] == 1)
        for url, why in (('http://private.test/', 'private address'), (base + '/missing', None),
                         ('http://no-such-host.invalid/', 'did not load')):
            try:
                r = await shot({'url': url}, {**OPTS, 'timeoutSecs': 10})
                check(f'{url}', why is None and r['status'] == 404, f'status {r["status"]}')
            except ShotError as e:
                check(f'{url} -> error', why is not None and why in str(e), str(e)[:80])
        await browser.close()
    srv.shutdown()
    print('FAILED' if bad else 'ALL OK', bad)
    sys.exit(1 if bad else 0)


if __name__ == '__main__':
    asyncio.run(main())
