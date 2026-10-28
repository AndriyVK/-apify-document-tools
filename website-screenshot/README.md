# Website Screenshot & URL/HTML to PDF: Full Page, Mobile, Bulk

Capture any web page as an image or a PDF — the whole page or just the first screen, on desktop or a phone — in bulk,
with a download link for each file.

- **Screenshots:** PNG, JPEG or WebP; full page (up to 20,000 px) or viewport; a single element by CSS selector.
- **PDF:** save web pages or your own **raw HTML** (invoices, reports, templates) as PDF — A4, Letter, Legal, A3, A5,
  portrait or landscape, print or screen styles.
- **Devices:** desktop 1920×1080, laptop 1366×768, iPad Pro 11, iPhone 15 Pro, Galaxy S24 (real pixel density), or a
  custom viewport; **dark mode**.
- **Clean captures:** floating cookie and consent banners are hidden, lazy-loaded images are loaded by scrolling, and
  you can inject your own CSS (e.g. hide chat widgets).
- **Safe:** requests to private network addresses are blocked.

## Why this Actor

| | This Actor | Typical alternatives |
|---|---|---|
| **Devices** | Desktop, laptop, iPad, iPhone and Android at real pixel density, dark mode | Often desktop only |
| **PDF** | Web pages **and your own raw HTML** (invoices, reports) to PDF — A4/Letter, margins, print or screen styles | Often screenshot only, or a separate PDF tool |
| **Clean captures** | Cookie banners hidden, lazy images loaded, custom CSS, element screenshots | Banners and empty placeholders in the shot |
| **Safety** | Requests to private networks blocked | — |
| **Price** | **$4 per 1,000** captures | $0.83–20 per 1,000 |

## Input

```json
{
  "urls": [{ "url": "https://apify.com" }, { "url": "example.com" }],
  "format": "png",
  "device": "mobile",
  "fullPage": true,
  "hideCookieBanners": true,
  "waitUntil": "load",
  "delayMs": 0
}
```

HTML to PDF:

```json
{
  "html": "<h1>Invoice #42</h1><p>Total: €120</p>",
  "format": "pdf",
  "pdfFormat": "A4",
  "pdfMargin": "15mm"
}
```

| Field | Meaning |
|---|---|
| `urls` | Pages to capture (`https://` is added when missing) |
| `html` | Raw HTML to render (optional) |
| `format` | `png`, `jpeg`, `webp` or `pdf` |
| `device` | `desktop`, `laptop`, `tablet`, `mobile`, `android` |
| `fullPage` | Whole page or just the first screen |
| `selector` | Capture one element, e.g. `#pricing` |
| `hideCookieBanners`, `scrollToBottom`, `css` | Clean-up before capturing |
| `waitUntil`, `delayMs`, `timeoutSecs` | When to capture |
| `viewportWidth`, `viewportHeight`, `darkMode`, `quality` | Look of the capture |
| `pdfFormat`, `pdfLandscape`, `pdfScreenMedia`, `pdfMargin` | PDF options |

## Output

```json
{
  "url": "https://apify.com",
  "finalUrl": "https://apify.com/",
  "status": 200,
  "title": "Apify: Full-stack web scraping and data extraction platform",
  "format": "png",
  "device": "mobile",
  "key": "0001-apify.com.png",
  "fileUrl": "https://api.apify.com/v2/key-value-stores/.../records/0001-apify.com.png",
  "width": 1179,
  "height": 14820,
  "bannersHidden": 1,
  "blockedRequests": 0
}
```

Pages that answer with an HTTP error (e.g. 404) are captured as they look, with `status` showing the code. A page that
does not load at all gets an `error` field instead and is **not charged**.

## Pricing

| Event | Price | What counts |
|---|---|---|
| `screenshot` | **$4 per 1,000** | one screenshot or PDF |

Plus Apify's standard start fee of $0.05 per 1,000 runs. The run stops before it would exceed your maximum charge per run.

## Related Actors

- [Office to PDF & PDF/A](https://apify.com/ai_admin/office-to-pdf) — Word, Excel, PowerPoint, HTML files → PDF/PDF-A
- [Document to Markdown for AI](https://apify.com/ai_admin/document-to-markdown) — PDFs, scans and Office files → Markdown
- [Image to Text OCR](https://apify.com/ai_admin/image-to-text-ocr) — read the text in screenshots

Open source: [github.com/AndriyVK/-apify-document-tools](https://github.com/AndriyVK/-apify-document-tools)

## Use with AI agents and code

- **MCP (Claude, Cursor, VS Code, any MCP client):** add `https://mcp.apify.com?tools=ai_admin/website-screenshot` as an MCP server —
  the agent gets one tool with this Actor's input schema and pays per use through your Apify account.
- **One HTTP call that returns the results:**

```bash
curl -X POST "https://api.apify.com/v2/acts/ai_admin~website-screenshot/run-sync-get-dataset-items?token=$APIFY_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"urls": [{"url": "https://apify.com"}], "format": "png", "device": "desktop", "fullPage": true}'
```

## Limits

- Pages behind a login, CAPTCHA or strong bot protection are captured as the visitor sees them (e.g. a login form).
- Full-page screenshots are capped at 20,000 px height; longer pages are cut.
- Some sites block data-centre IP addresses; such pages may load with an error or a block page.
