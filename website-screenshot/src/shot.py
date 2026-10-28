"""Website screenshots and PDFs with Playwright (Chromium)."""
from __future__ import annotations

import asyncio
import io
import urllib.parse
from typing import Awaitable, Callable

from PIL import Image
from playwright.async_api import Browser, Error as PlaywrightError, Route

DEVICES = {
    'desktop': {'viewport': {'width': 1920, 'height': 1080}},
    'laptop': {'viewport': {'width': 1366, 'height': 768}},
    'tablet': 'iPad Pro 11',
    'mobile': 'iPhone 15 Pro',
    'android': 'Galaxy S24',
}
# Cookie and consent banners: hidden only when they float over the page (fixed or sticky)
HIDE_BANNERS_JS = r"""
() => {
  const re = /(cookie|consent|gdpr|cmp|onetrust|cookiebot|didomi|usercentrics|privacy-banner|cc-window|qc-cmp)/i;
  let n = 0;
  for (const el of document.querySelectorAll('body *')) {
    const s = getComputedStyle(el);
    if (s.position !== 'fixed' && s.position !== 'sticky') continue;
    const tag = `${el.id} ${typeof el.className === 'string' ? el.className : ''} ${el.getAttribute('aria-label') || ''}`;
    if (re.test(tag)) { el.style.setProperty('display', 'none', 'important'); n++; }
  }
  document.documentElement.style.overflow = 'auto';
  document.body && (document.body.style.overflow = 'auto');
  return n;
}
"""
SCROLL_JS = r"""
async (maxHeight) => {
  const step = Math.max(window.innerHeight * 0.8, 400);
  for (let y = 0; y < Math.min(document.body.scrollHeight, maxHeight); y += step) {
    window.scrollTo(0, y);
    await new Promise(r => setTimeout(r, 150));
  }
  window.scrollTo(0, 0);
  await new Promise(r => setTimeout(r, 300));
}
"""
MAX_FULL_HEIGHT = 20000


class ShotError(Exception):
    pass


def device_options(playwright, device: str, width: int, height: int, dark: bool) -> dict:
    spec = DEVICES.get(device, DEVICES['desktop'])
    opts = dict(playwright.devices[spec]) if isinstance(spec, str) else dict(spec)
    opts.pop('default_browser_type', None)
    if device in ('desktop', 'laptop') and width:
        opts['viewport'] = {'width': width, 'height': height or opts['viewport']['height']}
    opts['color_scheme'] = 'dark' if dark else 'light'
    opts['ignore_https_errors'] = True
    return opts


async def capture(browser: Browser, ctx_opts: dict, target: dict, opts: dict,
                  host_ok: Callable[[str], Awaitable[bool]]) -> dict:
    """target: {'url': ...} or {'html': ...}. Returns {'data': bytes, 'contentType', 'title', 'finalUrl', 'status',
    'width', 'height', 'bannersHidden'}."""
    context = await browser.new_context(**ctx_opts)
    blocked = []

    async def guard(route: Route) -> None:
        url = route.request.url
        scheme = urllib.parse.urlparse(url).scheme
        if scheme in ('data', 'blob', 'about'):
            return await route.continue_()
        host = urllib.parse.urlparse(url).hostname or ''
        if scheme not in ('http', 'https') or not await host_ok(host):
            blocked.append(url[:200])
            return await route.abort('blockedbyclient')
        await route.continue_()

    await context.route('**/*', guard)
    page = await context.new_page()
    page.set_default_timeout(opts['timeoutSecs'] * 1000)
    try:
        status = None
        if 'url' in target:
            try:
                resp = await page.goto(target['url'], wait_until=opts['waitUntil'])
            except PlaywrightError as e:
                if blocked and blocked[0].split('#')[0] == target['url'].split('#')[0]:
                    raise ShotError('the URL points to a private address') from e
                if 'Timeout' in str(e) and opts['waitUntil'] == 'networkidle':
                    resp = None  # pages that never go idle (chat widgets, analytics) still get captured
                else:
                    raise ShotError('page did not load: ' + str(e).splitlines()[0][:200]) from e
            status = resp.status if resp else None
        else:
            await page.set_content(target['html'], wait_until='load')
        if opts['scroll']:
            await page.evaluate(SCROLL_JS, MAX_FULL_HEIGHT)
        hidden = await page.evaluate(HIDE_BANNERS_JS) if opts['hideBanners'] else 0
        if opts['css']:
            await page.add_style_tag(content=opts['css'])
        if opts['delayMs']:
            await asyncio.sleep(opts['delayMs'] / 1000)
        fmt = opts['format']
        if fmt == 'pdf':
            await page.emulate_media(media='screen' if opts['pdfScreenMedia'] else 'print')
            margin = opts['pdfMargin']
            data = await page.pdf(format=opts['pdfFormat'], landscape=opts['pdfLandscape'], print_background=True,
                                  margin={k: margin for k in ('top', 'right', 'bottom', 'left')})
            ctype = 'application/pdf'
        else:
            shot_fmt = 'jpeg' if fmt == 'jpeg' else 'png'
            kw = {'type': shot_fmt}
            if shot_fmt == 'jpeg':
                kw['quality'] = opts['quality']
            if opts['selector']:
                el = await page.query_selector(opts['selector'])
                if not el:
                    raise ShotError(f'selector "{opts["selector"]}" was not found on the page')
                data = await el.screenshot(**kw)
            else:
                full = opts['fullPage']
                if full:
                    h = await page.evaluate('() => document.documentElement.scrollHeight')
                    if h > MAX_FULL_HEIGHT:  # very long pages: clip instead of a giant image
                        vw = page.viewport_size['width']
                        kw['clip'] = {'x': 0, 'y': 0, 'width': vw, 'height': MAX_FULL_HEIGHT}
                data = await page.screenshot(full_page=full, **kw)
            ctype = f'image/{shot_fmt}'
            if fmt == 'webp':
                buf = io.BytesIO()
                Image.open(io.BytesIO(data)).save(buf, 'WEBP', quality=opts['quality'])
                data, ctype = buf.getvalue(), 'image/webp'
        size = None
        if fmt != 'pdf':
            with Image.open(io.BytesIO(data)) as im:
                size = im.size
        return {'data': data, 'contentType': ctype, 'title': await page.title(), 'finalUrl': page.url,
                'status': status, 'width': size[0] if size else None, 'height': size[1] if size else None,
                'bannersHidden': hidden, 'blockedRequests': len(blocked)}
    except PlaywrightError as e:
        raise ShotError(str(e).splitlines()[0][:300]) from e
    finally:
        await context.close()
