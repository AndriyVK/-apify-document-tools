"""Google News RSS: feed URLs, date windows and item parsing (no network here, so it is testable offline)."""
from __future__ import annotations

import html
import re
import xml.etree.ElementTree as ET
from datetime import date, datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from urllib.parse import urlencode, urlparse

BASE = 'https://news.google.com/rss'
FEED_CAP = 100  # Google News returns at most 100 items per feed
TOPICS = ('WORLD', 'NATION', 'BUSINESS', 'TECHNOLOGY', 'ENTERTAINMENT', 'SCIENCE', 'SPORTS', 'HEALTH')
TIMEFRAMES = {'1h': '1h', '1d': '1d', '7d': '7d', '30d': '30d', '1y': '1y'}


class InputError(ValueError):
    pass


def edition(value: str | None) -> dict:
    """'UA:uk' (country:language, as in Google's ceid) -> the hl/gl/ceid query parameters."""
    value = (value or 'US:en').strip()
    m = re.fullmatch(r'([A-Za-z]{2}):([A-Za-z]{2,3}(?:-[A-Za-z0-9]{2,4})?)', value)
    if not m:
        raise InputError(f'Edition "{value}" is not in the form COUNTRY:language, e.g. US:en, UA:uk, DE:de.')
    country, lang = m.group(1).upper(), m.group(2)
    hl = f'{lang}-{country}' if lang in ('en', 'es', 'pt', 'fr', 'zh') and '-' not in lang else lang
    return {'hl': hl, 'gl': country, 'ceid': f'{country}:{lang}'}


def parse_day(value: str | None, name: str) -> date | None:
    if not value:
        return None
    value = str(value).strip()
    m = re.fullmatch(r'(\d+)\s*(day|days|week|weeks|month|months)', value)
    if m:  # relative, e.g. "7 days" (Apify date pickers also produce this form)
        n = int(m.group(1)) * {'d': 1, 'w': 7, 'm': 30}[m.group(2)[0]]
        return datetime.now(timezone.utc).date() - timedelta(days=n)
    try:
        return date.fromisoformat(value[:10])
    except ValueError:
        raise InputError(f'{name} "{value}" is not a date like 2026-11-01 or "7 days".') from None


def search_url(query: str, ed: dict, timeframe: str | None = None, day_from: date | None = None,
               day_to: date | None = None) -> str:
    """Search feed. day_to is inclusive; Google's before: is exclusive, hence +1 day."""
    q = query.strip()
    if day_from:
        q += f' after:{day_from.isoformat()}'
    if day_to:
        q += f' before:{(day_to + timedelta(days=1)).isoformat()}'
    if not day_from and not day_to and timeframe in TIMEFRAMES and 'when:' not in q:
        q += f' when:{TIMEFRAMES[timeframe]}'
    return f'{BASE}/search?{urlencode({"q": q, **ed})}'


def topic_url(topic: str, ed: dict) -> str:
    topic = topic.strip().upper()
    if topic in ('TOP', 'TOP STORIES', 'HEADLINES'):
        return f'{BASE}?{urlencode(ed)}'
    if topic not in TOPICS:
        raise InputError(f'Topic "{topic}" is not one of TOP, {", ".join(TOPICS)}.')
    return f'{BASE}/headlines/section/topic/{topic}?{urlencode(ed)}'


def windows(day_from: date, day_to: date, days: int) -> list[tuple[date, date]]:
    """Splits [day_from, day_to] into windows of `days` days, newest first."""
    out, end = [], day_to
    while end >= day_from:
        start = max(day_from, end - timedelta(days=days - 1))
        out.append((start, end))
        end = start - timedelta(days=1)
    return out


_LINK = re.compile(r'<a href="([^"]+)"[^>]*>(.*?)</a>(?:&nbsp;|\s)*<font[^>]*>(.*?)</font>', re.S)


def _text(s: str) -> str:
    return html.unescape(re.sub(r'<[^>]+>', '', s or '')).replace('\xa0', ' ').strip()


def _domain(url: str | None) -> str | None:
    host = urlparse(url or '').hostname
    return host[4:] if host and host.startswith('www.') else host


def parse_feed(xml: bytes | str) -> list[dict]:
    """RSS -> articles. The description of a story cluster lists related coverage from other sources."""
    try:
        root = ET.fromstring(xml)
    except ET.ParseError:
        return []
    out = []
    for it in root.findall('./channel/item'):
        src = it.find('source')
        source = (src.text or '').strip() if src is not None else None
        source_url = src.get('url') if src is not None else None
        title = (it.findtext('title') or '').strip()
        if source and title.endswith(' - ' + source):
            title = title[:-len(source) - 3].rstrip()
        published = None
        try:
            published = parsedate_to_datetime(it.findtext('pubDate') or '').astimezone(timezone.utc)
        except (TypeError, ValueError):
            pass
        link = (it.findtext('link') or '').strip()
        related = []
        for href, rtitle, rsource in _LINK.findall(html.unescape(it.findtext('description') or '')):
            if href == link:
                continue
            related.append({'title': _text(rtitle), 'source': _text(rsource), 'googleNewsUrl': html.unescape(href)})
        out.append({
            'title': html.unescape(title),
            'source': source,
            'sourceUrl': source_url,
            'sourceDomain': _domain(source_url),
            'publishedAt': published.isoformat().replace('+00:00', 'Z') if published else None,
            'googleNewsUrl': link,
            'articleId': (it.findtext('guid') or '').strip() or None,
            'relatedCoverage': related,
        })
    return out
