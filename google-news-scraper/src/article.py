"""Publisher page details: image, description, author, publication date, language and the article text."""
from __future__ import annotations

import asyncio

import httpx
import trafilatura

from .resolve import HEADERS

MAX_BYTES = 5_000_000


def _extract(html: str, url: str, full_text: bool) -> dict:
    d = {}
    for precise in (True, False):  # precise first; when it finds no text, retry favouring recall
        doc = trafilatura.bare_extraction(html, url=url, with_metadata=True, include_comments=False,
                                          include_tables=False, favor_precision=precise, favor_recall=not precise)
        if doc is not None:
            d = doc.as_dict() if hasattr(doc, 'as_dict') else dict(doc)
            if (d.get('text') or '').strip():
                break
    if not d:
        return {}
    out = {'imageUrl': d.get('image'), 'description': d.get('description'), 'author': d.get('author'),
           'pageDate': d.get('date'), 'language': d.get('language'), 'siteName': d.get('sitename')}
    text = (d.get('text') or '').strip()
    if full_text:
        out['text'] = text or None
    out['wordCount'] = len(text.split()) if text else 0
    return {k: v for k, v in out.items() if v not in (None, '')}


async def details(client, url: str, full_text: bool) -> dict:
    """{'details': {...}} or {'detailsError': '...'}; never raises for site problems."""
    try:
        r = await client.get(url, headers={**HEADERS, 'Accept-Language': 'en;q=0.8,*;q=0.5'},
                             timeout=httpx.Timeout(45, connect=15))
        if r.status_code != 200:
            return {'detailsError': f'publisher site answered HTTP {r.status_code}'}
        if 'html' not in r.headers.get('content-type', 'text/html'):
            return {'detailsError': f'not an HTML page ({r.headers.get("content-type")})'}
        if len(r.content) > MAX_BYTES:
            return {'detailsError': 'page too large'}
        d = await asyncio.to_thread(_extract, r.text, str(r.url), full_text)
        return {'details': d} if d else {'detailsError': 'no article content found on the page'}
    except Exception as e:  # noqa: BLE001 - any site failure is reported on the item, the run goes on
        return {'detailsError': f'{type(e).__name__}: {e}'[:200]}
