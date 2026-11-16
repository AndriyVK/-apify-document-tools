# Google News Scraper: Headlines by Keyword, Topic & Language

Get Google News articles as clean JSON: by keyword, by topic or by publisher site, in any Google News edition -
**Ukrainian, Russian, English, German, French, Spanish, Polish, Japanese and 40+ more**. One record per article:
headline, publisher, publication time, the **direct URL on the publisher's site** and, if you want, the article's
image, description, author and **full text** - all for one price per article.

- **Search like on Google News:** `"exact phrase"`, `OR`, `-exclude`, `site:reuters.com`, `intitle:word`.
- **Topic headlines:** TOP, WORLD, NATION, BUSINESS, TECHNOLOGY, ENTERTAINMENT, SCIENCE, SPORTS, HEALTH.
- **Several countries and languages in one run:** e.g. `UA:uk`, `UA:ru` and `US:en` for the same queries - compare
  how a story is covered in each market.
- **More than 100 articles per query:** Google News shows at most 100 per search; give a date range (or a time period)
  and the Actor reads it day by day, up to 5,000 articles per query, without duplicates.
- **Direct publisher URLs** (on by default): `url` is the article on the publisher's site, not a Google News
  redirect; `ampUrl` too when the site has one.
- **Article details and full text** (optional): image, description, author, page date, site name, word count and the
  clean article text without menus and ads - ready for AI, RAG, summaries and sentiment.
- **Related coverage:** in topic headlines most stories come with the other outlets that wrote about them (Google
  News adds these story clusters to topic feeds; search results rarely have them).
- No proxy and no API key needed; failed feeds are not charged.

Use it for media monitoring and PR, brand and competitor mentions, market and crypto news, news datasets for AI and
RAG, and daily digests (schedule it every morning).

## Why this Actor

| | This Actor | Typical alternatives in the Apify Store (Nov 2026) |
|---|---|---|
| **Languages** | Any edition, several per run (UA:uk + UA:ru + US:en…) | One region per run |
| **Volume** | Up to 5,000 articles per query by reading the date range day by day | Often capped at 100 |
| **Story context** | Topic headlines with related coverage from other outlets (story clusters) | Single article only |
| **Publisher URL + article page** | Included: **$2.50 per 1,000** (paid plans), $3 on the free plan | Usually add-ons: $3.50-4 per 1,000 in total, plus start fees of $5 per 1,000 runs |
| **Full text for AI** | Included, clean text without boilerplate | Often an extra fee per article page |
| **Start fee** | Apify's minimum ($0.05 per 1,000 runs) - cheap for frequent small runs | Often $5 per 1,000 runs, some $90 |

## Input

```json
{
  "queries": ["Укренерго", "\"electric vehicles\" -Tesla"],
  "topics": ["BUSINESS"],
  "editions": ["UA:uk", "US:en"],
  "timeframe": "7d",
  "maxArticlesPerQuery": 100,
  "includeRelatedCoverage": true,
  "resolveUrls": true,
  "articleDetails": false,
  "fullText": false
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
  "url": "https://www.example.com/business/cheaper-batteries-2027",
  "ampUrl": "https://www.example.com/amp/business/cheaper-batteries-2027",
  "imageUrl": "https://www.example.com/images/batteries.jpg",
  "description": "Battery costs keep falling, and carmakers plan cheaper models.",
  "author": "Jane Doe",
  "pageDate": "2026-11-14",
  "siteName": "Example News",
  "wordCount": 812,
  "text": "Carmakers are betting that cheaper batteries...",
  "articleId": "CBMi...",
  "relatedCoverage": [
    {"title": "Battery prices fall again", "source": "Other Daily", "googleNewsUrl": "https://news.google.com/rss/articles/..."}
  ]
}
```

(Values above are illustrative.) `imageUrl` ... `text` appear with `articleDetails` / `fullText`. If a link or a
page cannot be read, the article is still returned with `urlError` or `detailsError` explaining why.

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

- Some publisher sites block automated visitors or have paywalls: then `detailsError` says so and the article comes
  without details (its publisher URL is still there). Measured on Apify 16.11.2026: publisher URLs for 100% of
  articles; full text for 27 of 30 Ukrainian, 28 of 30 Russian-language and 39 of 50 English articles (the rest were
  sites that refuse automated visitors, such as some large paywalled outlets).
- Article details make runs slower (one page per article); leave them off when you only need headlines and URLs.
- `relatedCoverage` is filled when Google News groups a story with other outlets: usually in topic headlines, rarely
  in search results (then it is an empty list).
- Google decides which articles a search returns: recent days give up to 100 articles per query per day, older days
  fewer (Google keeps a smaller sample of them), so long ranges return less than days x 100.
- Publication times are as Google News reports them (UTC).
