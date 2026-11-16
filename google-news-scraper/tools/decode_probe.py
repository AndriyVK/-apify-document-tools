"""Checks how Google News article links resolve to publisher URLs (allowed by the owner on 16.11.2026).

Usage: python3 tools/decode_probe.py [query] [edition] [count]
Prints the publisher URL for each article, where the link signature sits in the page, time and bytes.
"""
import sys
import time

import httpx

sys.path.insert(0, '.')
from src.news import edition, parse_feed, search_url  # noqa: E402
from src.resolve import resolve_one  # noqa: E402


def main():
    query = sys.argv[1] if len(sys.argv) > 1 else 'Укренерго'
    ed = edition(sys.argv[2] if len(sys.argv) > 2 else 'UA:uk')
    count = int(sys.argv[3]) if len(sys.argv) > 3 else 5
    with httpx.Client(timeout=30, follow_redirects=True) as client:
        arts = parse_feed(client.get(search_url(query, ed)).content)[:count]
        for a in arts:
            t = time.time()
            res = resolve_one(client, a['articleId'])
            print(f"{time.time() - t:4.1f}s {res.get('bytes', 0) / 1024:5.0f} KB  {a['source'][:22]:22} "
                  f"{res.get('url') or res.get('error')}")


if __name__ == '__main__':
    main()
