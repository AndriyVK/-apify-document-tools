"""Apify Actor: Google News articles by keyword or topic, for any country and language, from the public RSS feeds."""
from __future__ import annotations

import asyncio
import random
from datetime import datetime, timedelta, timezone

import httpx
from apify import Actor

from .news import (FEED_CAP, InputError, edition, parse_day, parse_feed, search_url, topic_url, windows)

EVENT_ARTICLE = 'article'
CONCURRENCY = 4
TIMEFRAME_DAYS = {'1h': 1, '1d': 1, '7d': 7, '30d': 30, '1y': 365}
HEADERS = {'User-Agent': 'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) '
                         'Chrome/130.0 Safari/537.36', 'Accept-Language': 'en;q=0.8'}


async def fetch(client: httpx.AsyncClient, url: str) -> list[dict]:
    """One feed, with retries on rate limits and server errors."""
    for attempt in range(5):
        try:
            r = await client.get(url)
            if r.status_code == 200:
                return parse_feed(r.content)
            if r.status_code not in (429, 500, 502, 503, 504):
                raise RuntimeError(f'Google News answered HTTP {r.status_code}')
        except httpx.HTTPError as e:
            if attempt == 4:
                raise RuntimeError(f'network error: {e}') from e
        await asyncio.sleep(2 ** attempt + random.random())
    raise RuntimeError('Google News keeps answering "too many requests"; try again later or use a proxy')


class Run:
    def __init__(self, client: httpx.AsyncClient, max_per_query: int, include_related: bool):
        self.client, self.max_per_query, self.include_related = client, max_per_query, include_related
        self.charging = Actor.get_charging_manager()
        self.seen: set[str] = set()
        self.pushed = 0
        self.limit_hit = False
        self.sem = asyncio.Semaphore(CONCURRENCY)

    def _left(self) -> int | None:
        return self.charging.calculate_max_event_charge_count_within_limit(EVENT_ARTICLE)

    async def _feed(self, url: str) -> list[dict]:
        async with self.sem:
            return await fetch(self.client, url)

    async def push(self, articles: list[dict], extra: dict, budget: int) -> int:
        """Pushes new (not yet seen) articles, newest first, up to budget and the user's charge limit."""
        articles.sort(key=lambda a: a['publishedAt'] or '', reverse=True)
        n = 0
        for a in articles:
            if n >= budget:
                break
            key = a['articleId'] or a['googleNewsUrl']
            if key in self.seen:
                continue
            left = self._left()
            if left is not None and left <= 0:
                self.limit_hit = True
                break
            self.seen.add(key)
            if not self.include_related:
                a = {k: v for k, v in a.items() if k != 'relatedCoverage'}
            await Actor.push_data({**extra, 'position': n + 1, **a}, charged_event_name=EVENT_ARTICLE)
            n += 1
        self.pushed += n
        return n

    async def query(self, q: str, ed_name: str, ed: dict, timeframe: str | None, day_from, day_to) -> dict:
        extra = {'query': q, 'edition': ed['ceid']}
        if self.max_per_query <= FEED_CAP:
            got = await self._feed(search_url(q, ed, timeframe, day_from, day_to))
            return {'found': await self.push(got, extra, self.max_per_query)}
        # More than one feed can hold: walk back one day at a time (each day is its own feed of up to 100)
        today = datetime.now(timezone.utc).date()
        end = day_to or today
        start = day_from or end - timedelta(days=TIMEFRAME_DAYS.get(timeframe or '', 30) - 1)
        found, days = 0, windows(start, end, 1)
        for i in range(0, len(days), CONCURRENCY):
            if found >= self.max_per_query or self.limit_hit:
                break
            batch = await asyncio.gather(*(self._feed(search_url(q, ed, None, a, b)) for a, b in days[i:i + CONCURRENCY]))
            for got in batch:
                found += await self.push(got, extra, self.max_per_query - found)
        return {'found': found}

    async def topic(self, t: str, ed: dict) -> dict:
        got = await self._feed(topic_url(t, ed))
        return {'found': await self.push(got, {'topic': t.upper(), 'edition': ed['ceid']},
                                         min(self.max_per_query, FEED_CAP))}


async def main() -> None:
    async with Actor:
        inp = await Actor.get_input() or {}
        queries = [str(q).strip() for q in inp.get('queries') or [] if str(q).strip()]
        topics = [str(t).strip() for t in inp.get('topics') or [] if str(t).strip()]
        if not queries and not topics:
            await Actor.fail(status_message='Add at least one search query or topic.')
            return
        try:
            eds = [(e, edition(e)) for e in dict.fromkeys(inp.get('editions') or ['US:en'])]
            day_from = parse_day(inp.get('dateFrom'), 'dateFrom')
            day_to = parse_day(inp.get('dateTo'), 'dateTo')
        except InputError as e:
            await Actor.fail(status_message=str(e))
            return
        if day_from and day_to and day_from > day_to:
            await Actor.fail(status_message='dateFrom is after dateTo.')
            return
        timeframe = inp.get('timeframe') or None
        max_per_query = max(1, min(int(inp.get('maxArticlesPerQuery') or 100), 5000))

        proxy_url = None
        if (inp.get('proxyConfiguration') or {}).get('useApifyProxy'):
            proxy = await Actor.create_proxy_configuration(actor_proxy_input=inp['proxyConfiguration'])
            proxy_url = await proxy.new_url() if proxy else None
        async with httpx.AsyncClient(timeout=httpx.Timeout(30, connect=10), headers=HEADERS, follow_redirects=True,
                                     proxy=proxy_url) as client:
            run = Run(client, max_per_query, bool(inp.get('includeRelatedCoverage', True)))
            failed = []
            for name, ed in eds:
                for q in queries:
                    if run.limit_hit:
                        break
                    try:
                        res = await run.query(q, name, ed, timeframe, day_from, day_to)
                        Actor.log.info(f'"{q}" [{ed["ceid"]}]: {res["found"]} articles')
                    except (RuntimeError, InputError) as e:
                        failed.append(f'"{q}" [{ed["ceid"]}]: {e}')
                for t in topics:
                    if run.limit_hit:
                        break
                    try:
                        res = await run.topic(t, ed)
                        Actor.log.info(f'topic {t} [{ed["ceid"]}]: {res["found"]} articles')
                    except (RuntimeError, InputError) as e:
                        failed.append(f'topic {t} [{ed["ceid"]}]: {e}')
            for f in failed:
                Actor.log.warning(f)
            msg = f'{run.pushed} articles'
            if run.limit_hit:
                msg += '; stopped at the maximum charge per run'
            if failed:
                msg += f'; {len(failed)} feed(s) failed: {failed[0]}'
            await Actor.set_status_message(msg, is_terminal=True)
            if failed and not run.pushed:
                await Actor.fail(status_message=msg)
