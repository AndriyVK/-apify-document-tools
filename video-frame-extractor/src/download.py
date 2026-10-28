"""Safe download of user-supplied URLs (same rules as the other Actors in this repo)."""
from __future__ import annotations

import asyncio
import contextlib
import ipaddress
import os
import socket
import urllib.parse

import httpx

MAX_DOWNLOAD_BYTES = 2 * 1024 * 1024 * 1024
MAX_REDIRECTS = 5


class DownloadError(Exception):
    pass


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


async def download(client: httpx.AsyncClient, url: str, dest: str) -> tuple[str, str]:
    """Returns (file name hint, content type). Redirects are followed by hand so every hop is checked."""
    for _ in range(MAX_REDIRECTS + 1):
        parsed = urllib.parse.urlparse(url)
        if parsed.scheme not in ('http', 'https') or not parsed.hostname:
            raise DownloadError('only http(s) URLs are supported')
        if not await asyncio.to_thread(_is_public_host, parsed.hostname):
            raise DownloadError('the URL points to a private address')
        resp = await client.send(client.build_request('GET', url), stream=True)
        if resp.is_redirect and resp.headers.get('location'):
            await resp.aclose()
            url = urllib.parse.urljoin(url, resp.headers['location'])
            continue
        break
    else:
        raise DownloadError('too many redirects')
    async with contextlib.aclosing(resp) as r:
        if r.status_code >= 400:
            raise DownloadError(f'download failed: HTTP {r.status_code}')
        size = 0
        with open(dest, 'wb') as f:
            async for chunk in r.aiter_bytes(1 << 16):
                size += len(chunk)
                if size > MAX_DOWNLOAD_BYTES:
                    raise DownloadError(f'file is larger than {MAX_DOWNLOAD_BYTES // (1024 * 1024)} MB')
                f.write(chunk)
        name = ''
        cd = r.headers.get('content-disposition', '')
        if 'filename=' in cd:
            name = cd.split('filename=')[-1].strip('"\' ;')
        if not name:
            name = os.path.basename(urllib.parse.unquote(str(r.url.path)))
        return name, r.headers.get('content-type', '')
