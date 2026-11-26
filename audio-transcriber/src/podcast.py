"""Podcast RSS feeds -> the newest episodes' audio URLs (enclosures) with titles and dates."""
from __future__ import annotations

import xml.etree.ElementTree as ET
from email.utils import parsedate_to_datetime

import httpx

ITUNES = '{http://www.itunes.com/dtds/podcast-1.0.dtd}'


class FeedError(Exception):
    pass


def parse_feed(xml: bytes, max_episodes: int) -> tuple[str | None, list[dict]]:
    """(podcast title, [{'url', 'episodeTitle', 'publishedAt', 'episodeDurationSeconds'}]) newest first."""
    try:
        root = ET.fromstring(xml)
    except ET.ParseError as e:
        raise FeedError(f'not an RSS feed: {e}') from e
    channel = root.find('channel')
    if channel is None:
        raise FeedError('not an RSS podcast feed (no <channel>)')
    episodes = []
    for it in channel.findall('item'):
        enc = it.find('enclosure')
        url = enc.get('url') if enc is not None else None
        if not url or not (enc.get('type', 'audio') or 'audio').startswith(('audio', 'video')):
            continue
        when = None
        try:
            when = parsedate_to_datetime(it.findtext('pubDate') or '')
        except (TypeError, ValueError):
            pass
        dur = (it.findtext(ITUNES + 'duration') or '').strip()
        secs = None
        if dur:
            try:
                parts = [float(x) for x in dur.split(':')]
                secs = sum(p * 60 ** i for i, p in enumerate(reversed(parts)))
            except ValueError:
                secs = None
        episodes.append({'url': url, 'episodeTitle': (it.findtext('title') or '').strip() or None,
                         'publishedAt': when.isoformat() if when else None, '_when': when.timestamp() if when else 0,
                         'episodeDurationSeconds': secs})
    episodes.sort(key=lambda e: e['_when'], reverse=True)
    for e in episodes:
        e.pop('_when')
    return (channel.findtext('title') or '').strip() or None, episodes[:max_episodes]


async def episodes(client: httpx.AsyncClient, feed_url: str, max_episodes: int) -> tuple[str | None, list[dict]]:
    try:
        r = await client.get(feed_url, follow_redirects=True)
    except httpx.HTTPError as e:
        raise FeedError(f'feed download failed: {e}') from e
    if r.status_code != 200:
        raise FeedError(f'feed answered HTTP {r.status_code}')
    return parse_feed(r.content, max_episodes)
