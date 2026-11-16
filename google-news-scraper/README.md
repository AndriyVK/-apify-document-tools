# Google News Scraper: Headlines by Keyword, Topic & Language

Get Google News articles as clean JSON: by keyword, by topic or by publisher site, in any Google News edition -
**Ukrainian, Russian, English, German, French, Spanish, Polish, Japanese and 40+ more**. One record per article:
headline, publisher, publication time, link and the other outlets covering the same story.

- **Search like on Google News:** `"exact phrase"`, `OR`, `-exclude`, `site:reuters.com`, `intitle:word`.
- **Topic headlines:** TOP, WORLD, NATION, BUSINESS, TECHNOLOGY, ENTERTAINMENT, SCIENCE, SPORTS, HEALTH.
- **Several countries and languages in one run:** e.g. `UA:uk`, `UA:ru` and `US:en` for the same queries - compare
  how a story is covered in each market.
- **More than 100 articles per query:** Google News shows at most 100 per search; give a date range (or a time period)
  and the Actor reads it day by day, up to 5,000 articles per query, without duplicates.
- **Related coverage:** each story comes with the other outlets that wrote about it.
- No proxy and no API key needed; failed feeds are not charged.

Use it for media monitoring and PR, brand and competitor mentions, market and crypto news, news datasets for AI and
RAG, and daily digests (schedule it every morning).

## Why this Actor

| | This Actor | Typical alternatives in the Apify Store (Nov 2026) |
|---|---|---|
| **Languages** | Any edition, several per run (UA:uk + UA:ru + US:en…) | One region per run |
| **Volume** | Up to 5,000 articles per query by reading the date range day by day | Often capped at 100 |
| **Story context** | Related coverage from other outlets in every record | Single article only |
| **Price** | **$2.50-3 per 1,000 articles**, no add-on fees | $2-5 per 1,000, extra fees per article page or start |

## Input

```json
{
  "queries": ["Укренерго", "\"electric vehicles\" -Tesla"],
  "topics": ["BUSINESS"],
  "editions": ["UA:uk", "US:en"],
  "timeframe": "7d",
  "maxArticlesPerQuery": 100,
  "includeRelatedCoverage": true
}
```

For a fixed period use `"dateFrom": "2026-11-01", "dateTo": "2026-11-15"` instead of `timeframe`.

## Output

```json
{
  "query": "electric vehicles",
  "edition": "US:en",
  "position": 1,
  "title": "Automakers bet on cheaper batteries for 2027 models",
  "source": "Example News",
  "sourceUrl": "https://www.example.com",
  "sourceDomain": "example.com",
  "publishedAt": "2026-11-14T09:30:00Z",
  "googleNewsUrl": "https://news.google.com/rss/articles/CBMi...?oc=5",
  "articleId": "CBMi...",
  "relatedCoverage": [
    {"title": "Battery prices fall again", "source": "Other Daily", "googleNewsUrl": "https://news.google.com/rss/articles/..."}
  ]
}
```

(Values above are illustrative.) `googleNewsUrl` opens the article on the publisher's site through Google News.

## Pricing

| Event | Free plan | Paid plans | What counts |
|---|---|---|---|
| `article` | $3 per 1,000 | **$2.50 per 1,000** | one article in the results |

Plus Apify's standard start fee of $0.05 per 1,000 runs. Duplicates across queries are removed before charging, and
the run stops before it would exceed your maximum charge per run.

## Related Actors

- [Video Transcript & Translation](https://apify.com/ai_admin/social-video-transcript) - YouTube, TikTok, Reels to text
- [Document to Markdown for AI](https://apify.com/ai_admin/document-to-markdown) - PDFs and Office files to Markdown
- [Website Screenshot & URL/HTML to PDF](https://apify.com/ai_admin/website-screenshot) - capture the article pages

Open source: [github.com/AndriyVK/-apify-document-tools](https://github.com/AndriyVK/-apify-document-tools)

## Use with AI agents and code

- **MCP (Claude, Cursor, VS Code, any MCP client):** add `https://mcp.apify.com?tools=ai_admin/google-news-scraper` as an
  MCP server - the agent gets one tool with this Actor's input schema and pays per use through your Apify account.
- **One HTTP call that returns the results:**

```bash
curl -X POST "https://api.apify.com/v2/acts/ai_admin~google-news-scraper/run-sync-get-dataset-items?token=$APIFY_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"queries": ["artificial intelligence"], "editions": ["US:en"], "timeframe": "1d"}'
```

## Limits

- Links point to Google News, which forwards to the publisher; the Actor does not download article pages.
- Google decides which articles a search returns: recent days give up to 100 articles per query per day, older days
  fewer (Google keeps a smaller sample of them), so long ranges return less than days x 100.
- Publication times are as Google News reports them (UTC).
