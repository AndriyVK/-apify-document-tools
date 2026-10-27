"""Apify Actor: convert documents (PDF, scans, Office, HTML, images) to Markdown, tables and RAG chunks."""
from __future__ import annotations

import asyncio
import contextlib
import ipaddress
import os
import socket
import tempfile
import time
import urllib.parse
from decimal import Decimal

import httpx
from apify import Actor

from .convert import ConversionError, chunk_markdown, convert, detect_ext, extract_tables

EVENT_PAGE = 'page'
EVENT_OCR_PAGE = 'ocr-page'
MAX_DOWNLOAD_BYTES = 200 * 1024 * 1024
MAX_REDIRECTS = 5
# Dataset items are limited to 9 MB; longer Markdown goes to the key-value store
MAX_INLINE_MARKDOWN = 4_000_000


def _is_public_host(host: str) -> bool:
    """False if the host resolves to a private address. Unresolvable hosts are left to the HTTP client to fail
    (behind an HTTP proxy only the proxy resolves names)."""
    try:
        infos = socket.getaddrinfo(host, None)
    except socket.gaierror:
        return True
    for info in infos:
        ip = ipaddress.ip_address(info[4][0])
        if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved or ip.is_multicast:
            return False
    return True


async def _download(client: httpx.AsyncClient, url: str, dest: str) -> tuple[str, str]:
    """Returns (file name hint, content type). Redirects are followed by hand so every hop is checked."""
    for _ in range(MAX_REDIRECTS + 1):
        parsed = urllib.parse.urlparse(url)
        if parsed.scheme not in ('http', 'https') or not parsed.hostname:
            raise ConversionError('only http(s) URLs are supported')
        if not await asyncio.to_thread(_is_public_host, parsed.hostname):
            raise ConversionError('the URL points to a private address')
        resp = await client.send(client.build_request('GET', url), stream=True)
        if resp.is_redirect and resp.headers.get('location'):
            await resp.aclose()
            url = urllib.parse.urljoin(url, resp.headers['location'])
            continue
        break
    else:
        raise ConversionError('too many redirects')
    async with contextlib.aclosing(resp) as r:
        if r.status_code >= 400:
            raise ConversionError(f'download failed: HTTP {r.status_code}')
        size = 0
        with open(dest, 'wb') as f:
            async for chunk in r.aiter_bytes(1 << 16):
                size += len(chunk)
                if size > MAX_DOWNLOAD_BYTES:
                    raise ConversionError(f'file is larger than {MAX_DOWNLOAD_BYTES // (1024 * 1024)} MB')
                f.write(chunk)
        name = ''
        cd = r.headers.get('content-disposition', '')
        if 'filename=' in cd:
            name = cd.split('filename=')[-1].strip('"\' ;')
        if not name:
            name = os.path.basename(urllib.parse.unquote(str(r.url.path)))
        return name, r.headers.get('content-type', '')


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
            await Actor.fail(status_message='Input "sources" is empty: add at least one document URL.')
            return
        ocr_mode = inp.get('ocrMode', 'auto')
        langs = '+'.join(inp.get('ocrLanguages') or ['eng'])
        max_pages = int(inp.get('maxPagesPerDocument') or 500)
        chunk_size = int(inp.get('chunkSize') or 0)
        include_tables = inp.get('includeTables', True)

        charging = Actor.get_charging_manager()
        pricing = charging.get_pricing_info()
        prices = pricing.per_event_prices if pricing.is_pay_per_event else {}
        limit = pricing.max_total_charge_usd
        store = await Actor.open_key_value_store()
        ok = failed = 0
        async with httpx.AsyncClient(timeout=httpx.Timeout(120, connect=20),
                                     headers={'User-Agent': 'document-to-markdown (Apify Actor)'}) as client:
            for idx, url in enumerate(urls):
                started = time.monotonic()
                item = {'url': url}
                if prices and charging.calculate_max_event_charge_count_within_limit(EVENT_PAGE) == 0:
                    Actor.log.warning('Maximum charge per run reached, remaining documents were skipped.')
                    break
                with tempfile.TemporaryDirectory() as tmp:
                    try:
                        name, ctype = await _download(client, url, os.path.join(tmp, 'input.bin'))
                        ext = detect_ext(os.path.join(tmp, 'input.bin'), name, ctype)
                        path = os.path.join(tmp, 'input' + ext)
                        os.rename(os.path.join(tmp, 'input.bin'), path)

                        # Would this document's pages so far, plus the next one, still fit under the run's charge limit?
                        def budget(text_pages: int, ocr_pages: int) -> bool:
                            budget.cost += text_pages * prices.get(EVENT_PAGE, 0) + ocr_pages * prices.get(EVENT_OCR_PAGE, 0)
                            return not budget.cost or charging.calculate_total_charged_amount() + budget.cost <= limit
                        budget.cost = Decimal(0)

                        res = await asyncio.to_thread(convert, path, ext, ocr_mode=ocr_mode, ocr_languages=langs,
                                                      max_pages=max_pages, page_budget=budget)
                    except (ConversionError, httpx.HTTPError) as e:
                        failed += 1
                        item.update(error=str(e) or type(e).__name__)
                        Actor.log.warning(f'{url}: {e}')
                        await Actor.push_data(item)
                        continue
                md = res.markdown
                item.update(fileName=name or None, format=ext.lstrip('.'), sourcePages=res.source_pages,
                            textPages=res.page_count, ocrPages=res.ocr_pages, metadata=res.metadata,
                            warnings=res.warnings, characters=len(md))
                if include_tables:
                    item['tables'] = extract_tables(md)
                if chunk_size > 0:
                    item['chunks'] = chunk_markdown(md, chunk_size)
                if len(md) > MAX_INLINE_MARKDOWN:
                    key = f'markdown-{idx:05d}'
                    await store.set_value(key, md, content_type='text/markdown; charset=utf-8')
                    item['markdownKey'] = key
                    item['markdown'] = md[:MAX_INLINE_MARKDOWN]
                    item['warnings'].append(f'Markdown truncated here; full text is in the key-value store record {key!r}')
                else:
                    item['markdown'] = md
                item['seconds'] = round(time.monotonic() - started, 2)
                # Charge only for successfully converted pages, after the result is saved
                await Actor.push_data(item)
                if res.page_count:
                    await Actor.charge(EVENT_PAGE, count=res.page_count)
                if res.ocr_pages:
                    await Actor.charge(EVENT_OCR_PAGE, count=res.ocr_pages)
                ok += 1
                Actor.log.info(f'{url}: {ext} {res.page_count} text + {res.ocr_pages} OCR pages, {len(md)} chars')
        await Actor.set_status_message(f'Converted {ok} document(s), failed {failed}.')
