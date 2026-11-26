"""Apify Actor: Google News articles by keyword or topic, for any country and language, with publisher URLs and
(optionally) the article page details and text."""
from __future__ import annotations

import asyncio
import random
from datetime import datetime, timedelta, timezone

import httpx
from apify import Actor

from .article import details
from .resolve import resolve_async
from .news import (FEED_CAP, InputError, edition, parse_day, parse_feed, search_url, topic_url, windows)

EVENT_ARTICLE = 'article'
EVENT_PAGE = 'article-page'  # add-on: charged only when the publisher page gave its details / text
SORTS = ('newest', 'relevance')
CONCURRENCY = 4
ENRICH_CONCURRENCY = 8
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
    def __init__(self, client: httpx.AsyncClient, max_per_query: int, include_related: bool,
                 resolve_urls: bool = True, details: bool = False, full_text: bool = False, sort: str = 'newest'):
        self.client, self.max_per_query, self.include_related = client, max_per_query, include_related
        self.sort = sort
        self.resolve_urls, self.details, self.full_text = resolve_urls or details or full_text, \
            details or full_text, full_text
        self.charging = Actor.get_charging_manager()
        # the add-on exists only once the Actor's pricing has the event (before that, the page is in the article price)
        self.page_priced = EVENT_PAGE in (self.charging.get_pricing_info().per_event_prices or {})
        self.seen: set[str] = set()
        self.pushed = 0
        self.limit_hit = False
        self.sem = asyncio.Semaphore(CONCURRENCY)
        self.enrich_sem = asyncio.Semaphore(ENRICH_CONCURRENCY)

    def _left(self) -> int | None:
        """How many more articles fit into the user's maximum charge (with the page add-on when it is on)."""
        if not self.details:
            return self.charging.calculate_max_event_charge_count_within_limit(EVENT_ARTICLE)
        info = self.charging.get_pricing_info()
        unit = sum(info.per_event_prices.get(e) or 0 for e in (EVENT_ARTICLE, EVENT_PAGE))  # 0 if not priced
        if not unit or info.max_total_charge_usd.is_infinite():
            return None
        return max(0, int((info.max_total_charge_usd - self.charging.calculate_total_charged_amount()) // unit))

    def _page_ok(self, a: dict) -> bool:
        """The page add-on is charged only for articles whose page was read (and, with fullText, gave the text)."""
        if not self.details or a.get('detailsError') or not self.page_priced:
            return False
        return bool(a.get('text')) if self.full_text else any(
            a.get(k) for k in ('imageUrl', 'description', 'author', 'pageDate', 'siteName', 'wordCount'))

    async def _feed(self, url: str) -> list[dict]:
        async with self.sem:
            return await fetch(self.client, url)

    async def _enrich(self, a: dict) -> dict:
        """Publisher URL (and page details) for one article; problems are noted on the item, never fatal."""
        async with self.enrich_sem:
            if self.resolve_urls and a.get('articleId'):
                for attempt in range(3):
                    res = await resolve_async(self.client, a['articleId'])
                    if res.get('status') not in (429, 503):
                        break
                    await asyncio.sleep(2 ** attempt * 2 + random.random())
                if res.get('url'):
                    a['url'] = res['url']
                    if res.get('ampUrl'):
                        a['ampUrl'] = res['ampUrl']
                else:
                    a['urlError'] = res.get('error')
            if self.details and a.get('url'):
                got = await details(self.client, a['url'], self.full_text)
                a.update(got.get('details') or {})
                if got.get('detailsError'):
                    a['detailsError'] = got['detailsError']
        return a

    async def push(self, articles: list[dict], extra: dict, budget: int) -> int:
        """Pushes new (not yet seen) articles, newest first, up to budget and the user's charge limit."""
        if self.sort == 'newest':
            articles.sort(key=lambda a: a['publishedAt'] or '', reverse=True)
        # 'relevance' keeps Google News' own order
        picked = []
        left = self._left()
        for a in articles:
            if len(picked) >= budget:
                break
            key = a['articleId'] or a['googleNewsUrl']
            if key in self.seen:
                continue
            if left is not None and left <= len(picked):
                self.limit_hit = True
                break
            self.seen.add(key)
            if not self.include_related:
                a = {k: v for k, v in a.items() if k != 'relatedCoverage'}
            picked.append(a)
        if self.resolve_urls:
            picked = await asyncio.gather(*(self._enrich(a) for a in picked))
        for n, a in enumerate(picked):
            await Actor.push_data({**extra, 'position': n + 1, **a}, charged_event_name=EVENT_ARTICLE)
            if self._page_ok(a):
                await Actor.charge(EVENT_PAGE)
        self.pushed += len(picked)
        return len(picked)

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
            sort = inp.get('sortBy') or 'newest'
            if sort not in SORTS:
                await Actor.fail(status_message=f'sortBy must be one of {", ".join(SORTS)}.')
                return
            run = Run(client, max_per_query, bool(inp.get('includeRelatedCoverage', True)),
                      bool(inp.get('resolveUrls', True)), bool(inp.get('articleDetails', False)),
                      bool(inp.get('fullText', False)), sort)
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
