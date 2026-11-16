"""Publisher URL of a Google News article link (the link carries an id; Google maps it to the publisher's URL).

Sync and async variants share the parsing; the article page is streamed only until its link signature appears.
"""
from __future__ import annotations

import json
import re

ARTICLE = 'https://news.google.com/rss/articles/{}'
BATCH = 'https://news.google.com/_/DotsSplashUi/data/batchexecute'
HEADERS = {'User-Agent': 'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) '
                         'Chrome/130.0 Safari/537.36'}
_SIG = re.compile(r'data-n-a-ts="(\d+)"[^>]*?data-n-a-sg="([^"]+)"|data-n-a-sg="([^"]+)"[^>]*?data-n-a-ts="(\d+)"')
MAX_BYTES = 2_000_000


def _sig(text: str):
    m = _SIG.search(text)
    if not m:
        return None
    return (m.group(1), m.group(2)) if m.group(1) else (m.group(4), m.group(3))


def _body(article_id: str, ts: str, sg: str) -> dict:
    req = (f'["garturlreq",[["X","X",["X","X"],null,null,1,1,"US:en",null,1,null,null,null,null,null,0,1],'
           f'"X","X",1,[1,1,1],1,1,null,0,0,null,0],"{article_id}",{ts},"{sg}"]')
    return {'f.req': json.dumps([[['Fbv4je', req]]])}


def _parse(text: str) -> tuple[str | None, str | None]:
    for line in text.split('\n'):
        if line.startswith('[['):
            for e in json.loads(line):
                if e[0] == 'wrb.fr' and e[2]:
                    res = json.loads(e[2])
                    return res[1], (res[3] if len(res) > 3 else None)
    return None, None


def resolve_one(client, article_id: str) -> dict:
    """Sync (httpx.Client): {'url', 'ampUrl', 'bytes'} or {'error', 'bytes'}."""
    got, size = '', 0
    with client.stream('GET', ARTICLE.format(article_id), headers=HEADERS) as r:
        for chunk in r.iter_text():
            got += chunk
            size += len(chunk.encode())
            sig = _sig(got)
            if sig or size > MAX_BYTES:
                break
    if not sig:
        return {'error': 'no link signature on the Google News page', 'bytes': size}
    r = client.post(BATCH, data=_body(article_id, *sig), headers=HEADERS)
    url, amp = _parse(r.text)
    return {'url': url, 'ampUrl': amp, 'bytes': size + len(r.content)} if url else \
        {'error': f'Google News did not resolve the link (HTTP {r.status_code})', 'bytes': size}


async def resolve_async(client, article_id: str) -> dict:
    """Async (httpx.AsyncClient) twin of resolve_one."""
    got, size, sig = '', 0, None
    async with client.stream('GET', ARTICLE.format(article_id), headers=HEADERS) as r:
        if r.status_code != 200:
            return {'error': f'Google News answered HTTP {r.status_code}', 'status': r.status_code, 'bytes': 0}
        async for chunk in r.aiter_text():
            got += chunk
            size += len(chunk.encode())
            sig = _sig(got)
            if sig or size > MAX_BYTES:
                break
    if not sig:
        return {'error': 'no link signature on the Google News page', 'bytes': size}
    r = await client.post(BATCH, data=_body(article_id, *sig), headers=HEADERS)
    url, amp = _parse(r.text)
    return {'url': url, 'ampUrl': amp, 'bytes': size + len(r.content)} if url else \
        {'error': f'Google News did not resolve the link (HTTP {r.status_code})', 'status': r.status_code,
         'bytes': size}
