"""Runs the deployed Actor on Apify with live Google News feeds and checks the results and charges.

Usage: python tools/test_on_apify.py
"""
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from deploy import call  # noqa: E402

ACTOR = 'google-news-scraper'


def run(act_id, inp):
    r = call('POST', f'/acts/{act_id}/runs?waitForFinish=60', inp)
    while r['status'] in ('READY', 'RUNNING'):
        time.sleep(5)
        r = call('GET', f"/actor-runs/{r['id']}?waitForFinish=60")
    time.sleep(10)
    r = call('GET', f"/actor-runs/{r['id']}")
    return r, call('GET', f"/datasets/{r['defaultDatasetId']}/items?clean=1&format=json") or []


def main():
    act = next(a for a in call('GET', '/acts?my=1&limit=1000')['items'] if a['name'] == ACTOR)
    bad = 0

    def check(name, cond):
        nonlocal bad
        bad += not cond
        print(f"{'OK ' if cond else 'BAD'} {name}")

    def cost(r):
        return (f"{r['stats'].get('runTimeSecs', 0):.0f}s, ${r.get('usageTotalUsd') or 0:.5f}, "
                f"charged={r.get('chargedEventCounts')}")

    r, items = run(act['id'], {})
    check(f"default input: {r['status']}, {len(items)} items ({cost(r)})", r['status'] == 'SUCCEEDED' and len(items) > 50)
    r, items = run(act['id'], {'queries': ['Укренерго'], 'editions': ['UA:uk', 'UA:ru'], 'timeframe': '7d',
                               'maxArticlesPerQuery': 30, 'topics': ['BUSINESS']})
    check(f"2 editions + topic: {len(items)} items ({cost(r)})", 60 <= len(items) <= 260)
    check('charged = items', (r.get('chargedEventCounts') or {}).get('article') == len(items))
    urls = sum(1 for i in items if (i.get('url') or '').startswith('http') and 'news.google.com' not in i['url'])
    check(f'publisher URLs {urls}/{len(items)}', urls >= 0.9 * len(items))
    r, items = run(act['id'], {'queries': ['artificial intelligence'], 'maxArticlesPerQuery': 50, 'fullText': True})
    texts = sum(1 for i in items if i.get('text'))
    check(f"full text {texts}/{len(items)}, images {sum(1 for i in items if i.get('imageUrl'))} ({cost(r)})",
          len(items) == 50 and texts >= 30)
    print('   details errors:', sorted({(i.get('detailsError') or '')[:40] for i in items if i.get('detailsError')})[:6])
    print('  ', items[0]['edition'], items[0]['publishedAt'], items[0]['title'][:70], '|', items[0]['source'])
    r, items = run(act['id'], {'queries': ['bitcoin'], 'dateFrom': '2026-10-01', 'dateTo': '2026-10-31',
                               'maxArticlesPerQuery': 1000, 'includeRelatedCoverage': False,
                               'resolveUrls': False})
    check(f"30-day split: {len(items)} items, unique {len({i['articleId'] for i in items})} ({cost(r)})",
          len(items) > 150 and len({i['articleId'] for i in items}) == len(items))
    print('FAILED' if bad else 'ALL OK', bad)
    sys.exit(1 if bad else 0)


if __name__ == '__main__':
    main()
