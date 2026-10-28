"""Apify Actor: website screenshots (PNG/JPEG/WebP, full page, devices) and URL/HTML to PDF."""
from __future__ import annotations

import asyncio
import re
import urllib.parse

from apify import Actor
from playwright.async_api import async_playwright

from .netguard import is_public_host
from .shot import DEVICES, ShotError, capture, device_options

EVENT_SHOT = 'screenshot'
FORMATS = ('png', 'jpeg', 'webp', 'pdf')
EXT = {'png': 'png', 'jpeg': 'jpg', 'webp': 'webp', 'pdf': 'pdf'}


def _targets(inp: dict) -> list[dict]:
    out = []
    for item in inp.get('urls') or []:
        url = item.get('url') if isinstance(item, dict) else item
        if isinstance(url, str) and url.strip():
            url = url.strip()
            if not re.match(r'^[a-z][a-z0-9+.-]*://', url, re.I):
                url = 'https://' + url
            out.append({'url': url})
    html = inp.get('html')
    if isinstance(html, str) and html.strip():
        out.append({'html': html})
    return out


def _key(target: dict, idx: int, ext: str) -> str:
    if 'html' in target:
        return f'{idx:04d}-html.{ext}'
    p = urllib.parse.urlparse(target['url'])
    slug = re.sub(r'[^A-Za-z0-9.-]+', '-', f'{p.hostname or ""}{p.path}').strip('-.')[:60]
    return f'{idx:04d}-{slug or "page"}.{ext}'


async def main() -> None:
    async with Actor:
        inp = await Actor.get_input() or {}
        targets = _targets(inp)
        if not targets:
            await Actor.fail(status_message='Add at least one URL in "urls" or HTML in "html".')
            return
        fmt = str(inp.get('format') or 'png').lower()
        device = str(inp.get('device') or 'desktop')
        if fmt not in FORMATS or device not in DEVICES:
            await Actor.fail(status_message=f'format must be one of {", ".join(FORMATS)}; '
                                            f'device one of {", ".join(DEVICES)}.')
            return
        opts = {
            'format': fmt,
            'fullPage': bool(inp.get('fullPage', True)),
            'selector': (inp.get('selector') or '').strip(),
            'waitUntil': inp.get('waitUntil') if inp.get('waitUntil') in ('load', 'domcontentloaded', 'networkidle')
            else 'load',
            'delayMs': min(max(int(inp.get('delayMs') or 0), 0), 30000),
            'scroll': bool(inp.get('scrollToBottom', True)),
            'hideBanners': bool(inp.get('hideCookieBanners', True)),
            'css': inp.get('css') or '',
            'quality': min(max(int(inp.get('quality') or 85), 10), 100),
            'timeoutSecs': min(max(int(inp.get('timeoutSecs') or 60), 10), 180),
            'pdfFormat': inp.get('pdfFormat') if inp.get('pdfFormat') in ('A4', 'Letter', 'Legal', 'A3', 'A5')
            else 'A4',
            'pdfLandscape': bool(inp.get('pdfLandscape', False)),
            'pdfScreenMedia': bool(inp.get('pdfScreenMedia', False)),
            'pdfMargin': inp.get('pdfMargin') or '10mm',
        }
        width = int(inp.get('viewportWidth') or 0)
        height = int(inp.get('viewportHeight') or 0)
        dark = bool(inp.get('darkMode', False))
        cache: dict[str, bool] = {}

        async def host_ok(host: str) -> bool:
            if host not in cache:
                cache[host] = await asyncio.to_thread(is_public_host, host)
            return cache[host]

        charging = Actor.get_charging_manager()
        store = await Actor.open_key_value_store()
        ok = failed = 0
        async with async_playwright() as pw:
            browser = await pw.chromium.launch(args=['--disable-dev-shm-usage'])
            ctx_opts = device_options(pw, device, width, height, dark)
            for idx, target in enumerate(targets, 1):
                if charging.calculate_max_event_charge_count_within_limit(EVENT_SHOT) == 0:
                    Actor.log.warning('Maximum charge per run reached, remaining pages were skipped.')
                    break
                label = target.get('url', 'html')
                try:
                    res = await capture(browser, ctx_opts, target, opts, host_ok)
                except ShotError as e:
                    failed += 1
                    await Actor.push_data({'url': label, 'error': str(e)})
                    continue
                key = _key(target, idx, EXT[fmt])
                await store.set_value(key, res.pop('data'), content_type=res.pop('contentType'))
                await Actor.push_data({'url': label, 'format': fmt, 'device': device, 'key': key,
                                       'fileUrl': await store.get_public_url(key), **res})
                # One event per produced screenshot or PDF, after it is saved
                await Actor.charge(EVENT_SHOT)
                ok += 1
            await browser.close()
        await Actor.set_status_message(f'Captured {ok} page(s), failed {failed}.')
