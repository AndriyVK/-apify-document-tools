"""Apify Actor: convert Word, Excel, PowerPoint, OpenDocument, RTF, HTML and images to PDF or PDF/A."""
from __future__ import annotations

import asyncio
import os
import re
import tempfile
import time

import httpx
from apify import Actor

from .convert import ConversionError, check_signature, convert_all, detect_ext, merge, pdf_pages
from .download import DownloadError, download

EVENT_DOCUMENT = 'document'


def _sources(inp: dict) -> list[str]:
    urls = []
    for item in inp.get('sources') or []:
        url = item.get('url') if isinstance(item, dict) else item
        if isinstance(url, str) and url.strip():
            urls.append(url.strip())
    return urls


def _safe_stem(name: str, idx: int) -> str:
    stem = re.sub(r'[^A-Za-z0-9._-]+', '-', os.path.splitext(name or '')[0]).strip('-.')[:60]
    return f'{idx:04d}-{stem or "document"}'


async def main() -> None:
    async with Actor:
        inp = await Actor.get_input() or {}
        urls = _sources(inp)
        if not urls:
            await Actor.fail(status_message='Input "sources" is empty: add at least one document URL.')
            return
        pdfa = bool(inp.get('pdfA', False))
        merge_all = bool(inp.get('mergeIntoOne', False))

        charging = Actor.get_charging_manager()
        left = charging.calculate_max_event_charge_count_within_limit(EVENT_DOCUMENT)
        if left is not None and left < len(urls):
            Actor.log.warning(f'Maximum charge per run allows {left} of {len(urls)} documents; the rest is skipped.')
            urls = urls[:left]
        store = await Actor.open_key_value_store()

        with tempfile.TemporaryDirectory() as tmp:
            indir, outdir = os.path.join(tmp, 'in'), os.path.join(tmp, 'out')
            os.makedirs(indir)
            os.makedirs(outdir)
            jobs, failed_items = [], []
            started = time.monotonic()
            async with httpx.AsyncClient(timeout=httpx.Timeout(120, connect=20),
                                         headers={'User-Agent': 'office-to-pdf (Apify Actor)'}) as client:
                for idx, url in enumerate(urls, 1):
                    raw = os.path.join(indir, f'{idx:04d}.bin')
                    try:
                        name, ctype = await download(client, url, raw)
                        ext = detect_ext(raw, name, ctype)
                        check_signature(raw, ext)
                    except (DownloadError, ConversionError, httpx.HTTPError) as e:
                        failed_items.append({'url': url, 'error': str(e) or type(e).__name__})
                        continue
                    path = os.path.join(indir, _safe_stem(name, idx) + ext)
                    os.rename(raw, path)
                    jobs.append({'url': url, 'fileName': name or None, 'format': ext.lstrip('.'), 'path': path})

            results = await asyncio.to_thread(convert_all, [(j['path'], '.' + j['format']) for j in jobs], outdir,
                                              pdfa=pdfa)
            converted = []
            for j in jobs:
                res = results[j['path']]
                item = {'url': j['url'], 'fileName': j['fileName'], 'format': j['format']}
                if isinstance(res, ConversionError):
                    item['error'] = str(res)
                    await Actor.push_data(item)
                    continue
                key = os.path.basename(res)
                with open(res, 'rb') as f:
                    await store.set_value(key, f.read(), content_type='application/pdf')
                item.update(pdfKey=key, pdfUrl=await store.get_public_url(key), pages=pdf_pages(res),
                            bytes=os.path.getsize(res), pdfA=pdfa)
                await Actor.push_data(item)
                # Charge after the PDF is saved and listed
                await Actor.charge(EVENT_DOCUMENT)
                converted.append(res)
            for item in failed_items:
                await Actor.push_data(item)

            if merge_all and len(converted) > 1:
                dest = os.path.join(outdir, 'merged.pdf')
                pages = await asyncio.to_thread(merge, converted, dest)
                with open(dest, 'rb') as f:
                    await store.set_value('merged.pdf', f.read(), content_type='application/pdf')
                await Actor.push_data({'url': None, 'merged': True, 'pdfKey': 'merged.pdf',
                                       'pdfUrl': await store.get_public_url('merged.pdf'), 'pages': pages,
                                       'bytes': os.path.getsize(dest), 'documents': len(converted)})
            if pdfa and merge_all and len(converted) > 1:
                Actor.log.info('Note: the merged file is a plain PDF; the individual files are PDF/A.')
            failed = len(failed_items) + sum(isinstance(r, ConversionError) for r in results.values())
            await Actor.set_status_message(
                f'Converted {len(converted)} document(s) to PDF{"/A" if pdfa else ""}, failed {failed}, '
                f'{time.monotonic() - started:.0f}s.')
