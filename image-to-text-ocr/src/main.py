"""Apify Actor: bulk OCR of images and scanned PDFs (Tesseract), text + lines + words with confidence."""
from __future__ import annotations

import asyncio
import os
import tempfile

import httpx
from apify import Actor

from .download import DownloadError, download
from .ocr import OcrError, detect_kind, iter_pages, ocr, rotate_upright

EVENT_IMAGE = 'image'
LANGS = {'eng', 'ukr', 'rus', 'deu', 'fra', 'spa', 'ita', 'por', 'pol', 'nld', 'ces', 'slk', 'tur', 'ron', 'hun',
         'bul', 'ell', 'swe', 'nor', 'dan', 'fin', 'lit', 'lav', 'est', 'hrv', 'srp', 'slv', 'bel', 'kaz', 'vie',
         'ind', 'heb', 'ara', 'hin', 'chi_sim', 'chi_tra', 'jpn', 'kor'}


def _sources(inp: dict) -> list[str]:
    urls = []
    for item in inp.get('sources') or []:
        url = item.get('url') if isinstance(item, dict) else item
        if isinstance(url, str) and url.strip():
            urls.append(url.strip())
    return urls


async def main() -> None:
    async with Actor:
        inp = await Actor.get_input() or {}
        urls = _sources(inp)
        if not urls:
            await Actor.fail(status_message='Input "sources" is empty: add at least one image or PDF URL.')
            return
        langs = [str(x).strip() for x in (inp.get('languages') or ['eng']) if str(x).strip()]
        unknown = [x for x in langs if x not in LANGS]
        if unknown or not langs:
            await Actor.fail(status_message=f'Unknown language code(s): {", ".join(unknown) or "none given"}.')
            return
        lang = '+'.join(langs)
        psm = str(inp.get('layout') or 'auto')
        pages = str(inp.get('pages') or '')
        with_lines = bool(inp.get('includeLines', True))
        with_words = bool(inp.get('includeWords', False))
        auto_rotate = bool(inp.get('autoRotate', False))

        charging = Actor.get_charging_manager()
        ok = failed = done = 0
        with tempfile.TemporaryDirectory() as tmp:
            async with httpx.AsyncClient(timeout=httpx.Timeout(120, connect=20),
                                         headers={'User-Agent': 'image-to-text-ocr (Apify Actor)'}) as client:
                for idx, url in enumerate(urls, 1):
                    left = charging.calculate_max_event_charge_count_within_limit(EVENT_IMAGE)
                    if left == 0:
                        Actor.log.warning('Maximum charge per run reached, remaining files were skipped.')
                        break
                    src = os.path.join(tmp, f'in-{idx:04d}')
                    try:
                        name, _ = await download(client, url, src)
                        kind = await asyncio.to_thread(detect_kind, src)
                        page_iter = iter_pages(src, kind, pages, left)
                        while True:
                            nxt = await asyncio.to_thread(next, page_iter, None)
                            if nxt is None:
                                break
                            page, total, img = nxt
                            rotated = 0
                            if auto_rotate:
                                img, rotated = await asyncio.to_thread(rotate_upright, img)
                            res = await asyncio.to_thread(ocr, img, lang, psm, with_words)
                            item = {'url': url, 'fileName': name or None, 'kind': kind, 'page': page,
                                    'totalPages': total, 'languages': langs, **res}
                            if auto_rotate:
                                item['rotated'] = rotated
                            if not with_lines:
                                item.pop('lines')
                            await Actor.push_data(item)
                            # One event per OCR'd image or page, after the result is saved
                            await Actor.charge(EVENT_IMAGE)
                            done += 1
                    except (DownloadError, OcrError, httpx.HTTPError) as e:
                        failed += 1
                        await Actor.push_data({'url': url, 'error': str(e) or type(e).__name__})
                        continue
                    ok += 1
        await Actor.set_status_message(f'OCR done: {done} image(s)/page(s) from {ok} file(s), failed {failed}.')
