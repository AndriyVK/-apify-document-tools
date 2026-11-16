"""Offline parser checks plus a local run against live Google News feeds: python -m tests.check [--live]"""
import json
import os
import shutil
import subprocess
import sys
from datetime import date

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from src.news import edition, parse_feed, search_url, windows  # noqa: E402

bad = 0


def check(name, cond):
    global bad
    bad += not cond
    print(f"{'OK ' if cond else 'BAD'} {name}")


SAMPLE = b'''<?xml version="1.0"?><rss><channel><item><title>Big news - Example Times</title>
<link>https://news.google.com/rss/articles/AAA?oc=5</link><guid isPermaLink="false">AAA</guid>
<pubDate>Wed, 11 Nov 2026 17:28:09 GMT</pubDate>
<description>&lt;ol&gt;&lt;li&gt;&lt;a href="https://news.google.com/rss/articles/AAA?oc=5"&gt;Big news&lt;/a&gt;&amp;nbsp;&amp;nbsp;&lt;font color="#6f6f6f"&gt;Example Times&lt;/font&gt;&lt;/li&gt;&lt;li&gt;&lt;a href="https://news.google.com/rss/articles/BBB?oc=5"&gt;Same story &amp;amp; more&lt;/a&gt;&amp;nbsp;&amp;nbsp;&lt;font color="#6f6f6f"&gt;Other Post&lt;/font&gt;&lt;/li&gt;&lt;/ol&gt;</description>
<source url="https://www.example.com">Example Times</source></item></channel></rss>'''
a = parse_feed(SAMPLE)[0]
check('title without source suffix', a['title'] == 'Big news')
check('publishedAt ISO UTC', a['publishedAt'] == '2026-11-11T17:28:09Z')
check('source domain', a['sourceDomain'] == 'example.com')
check('related coverage excludes itself', a['relatedCoverage'] == [
    {'title': 'Same story & more', 'source': 'Other Post', 'googleNewsUrl': 'https://news.google.com/rss/articles/BBB?oc=5'}])
check('broken XML -> []', parse_feed(b'<html>') == [])
check('edition UA:uk', edition('UA:uk') == {'hl': 'uk', 'gl': 'UA', 'ceid': 'UA:uk'})
check('edition US:en', edition('US:en')['hl'] == 'en-US')
check('dates -> after/before (inclusive end)', 'after%3A2026-11-01+before%3A2026-11-03' in
      search_url('x', edition('US:en'), None, date(2026, 11, 1), date(2026, 11, 2)))
check('timeframe -> when:', 'when%3A7d' in search_url('x', edition('US:en'), '7d'))
check('windows newest first', windows(date(2026, 11, 1), date(2026, 11, 3), 1)[0] == (date(2026, 11, 3), date(2026, 11, 3)))

if '--live' in sys.argv:
    def run(inp):
        st = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'storage')
        shutil.rmtree(st, ignore_errors=True)
        os.makedirs(f'{st}/key_value_stores/default')
        json.dump(inp, open(f'{st}/key_value_stores/default/INPUT.json', 'w'))
        env = {**os.environ, 'APIFY_LOCAL_STORAGE_DIR': st, 'CRAWLEE_STORAGE_DIR': st}
        p = subprocess.run([sys.executable, '-m', 'src'], cwd=os.path.dirname(st[:-len('/tests/storage')] + '/x'),
                           env=env, capture_output=True, text=True, timeout=600)
        ds = f'{st}/datasets/default'
        items = [json.load(open(f'{ds}/{f}')) for f in sorted(os.listdir(ds)) if f.endswith('.json')
                 and f != '__metadata__.json'] if os.path.isdir(ds) else []
        return p, items

    p, items = run({'queries': ['Укренерго'], 'editions': ['UA:uk', 'UA:ru'], 'timeframe': '7d',
                    'maxArticlesPerQuery': 30})
    print(p.stderr[-800:] if not items else '', end='')
    check(f'2 editions x 30 -> {len(items)} items', 40 <= len(items) <= 60)
    check('fields present', all(i.get('title') and i.get('googleNewsUrl') and i.get('publishedAt') for i in items))
    urls = [i for i in items if (i.get('url') or '').startswith('http') and 'news.google.com' not in i['url']]
    check(f'publisher URLs {len(urls)}/{len(items)}', len(urls) >= 0.9 * len(items))
    p, items = run({'queries': ['artificial intelligence'], 'maxArticlesPerQuery': 10, 'fullText': True})
    check(f"full text {sum(1 for i in items if i.get('text'))}/10, images {sum(1 for i in items if i.get('imageUrl'))}",
          sum(1 for i in items if i.get('text')) >= 6)
    p, items = run({'queries': ['bitcoin'], 'dateFrom': '2026-11-01', 'dateTo': '2026-11-04', 'maxArticlesPerQuery': 300,
                    'resolveUrls': False})
    days = sorted({i['publishedAt'][:10] for i in items})
    check(f'day split: {len(items)} items over {days}', len(items) > 100 and days[0] >= '2026-10-31')
    check('no duplicates', len({i['articleId'] for i in items}) == len(items))
    p, items = run({'topics': ['business', 'TOP'], 'editions': ['DE:de'], 'includeRelatedCoverage': False,
                    'resolveUrls': False})
    check(f'topics -> {len(items)} items, no relatedCoverage', len(items) > 20 and
          all('relatedCoverage' not in i for i in items) and {i['topic'] for i in items} == {'BUSINESS', 'TOP'})
    p, items = run({'queries': ['x'], 'editions': ['Ukraine']})
    check('bad edition -> failed run', p.returncode != 0 or 'COUNTRY:language' in p.stdout + p.stderr)
print('FAILED' if bad else 'ALL OK', bad)
sys.exit(1 if bad else 0)
