# Image to Text OCR: Bulk Images & Scanned PDFs, 38 Languages

Extract text from images and scanned PDFs in bulk — screenshots, photos of documents, receipts, scans — with the
confidence and position of every line and word.

- **Images and scanned PDFs.** PNG, JPG, WebP, TIFF (multi-page), GIF, BMP, iPhone HEIC/HEIF, AVIF and PDF pages;
  choose pages like `1-3,5,8-`.
- **38 languages**, several at once: English, Ukrainian, Russian, German, French, Spanish, Italian, Portuguese, Polish,
  Dutch, Czech, Turkish, Arabic, Hebrew, Hindi, Chinese, Japanese, Korean, Vietnamese and more.
- **Structured output.** Plain text with paragraphs, plus lines and (optionally) words with confidence 0–100 and
  bounding boxes in pixels of the original image — ready for highlighting, redaction or data extraction.
- **Auto-rotate** for pages scanned sideways or upside down; small images are upscaled automatically.
- **Private:** runs on Tesseract inside the Actor — your images are not sent to any third-party OCR service.

## Why this Actor

| | This Actor | Typical alternatives in the Apify Store (Oct 2026) |
|---|---|---|
| **Price** | **$1.50 per 1,000 images** | $2–6.50 per 1,000 |
| **Output** | Text **plus** every line and word with confidence and bounding box | Often plain text only |
| **Languages** | 38, several at once — incl. Ukrainian, Arabic, Chinese, Japanese, Hindi | Often English-first |
| **Scans** | Scanned PDFs and multi-page TIFFs page by page, auto-rotate | Often images only |
| **Privacy** | OCR runs inside the Actor — images are not sent to Google or other OCR APIs | Several wrap Google Lens |

## Input

```json
{
  "sources": [{ "url": "https://example.com/receipt.jpg" }, { "url": "https://example.com/scan.pdf" }],
  "languages": ["eng", "ukr"],
  "pages": "1-3",
  "layout": "auto",
  "autoRotate": false,
  "includeLines": true,
  "includeWords": false
}
```

| Field | Meaning |
|---|---|
| `sources` | URLs of images or PDFs. Files in your own Apify key-value store work too: set the store's access to "Anyone with ID can read" and use `https://api.apify.com/v2/key-value-stores/<store ID>/records/<key>` (the Actor runs with limited permissions and does not use your token). |
| `languages` | Tesseract codes: `eng`, `ukr`, `rus`, `deu`, `fra`, `spa`, `chi_sim`, `jpn`, `ara`… |
| `pages` | Pages of PDFs and multi-page TIFFs, empty = all |
| `layout` | `auto` (documents, columns), `single-block`, `single-line`, `sparse` (screenshots, receipts, signs) |
| `autoRotate` | Detect and fix page orientation before OCR |
| `includeLines` / `includeWords` | Return lines / words with confidence and bounding box |

## Output

One item per image or PDF page:

```json
{
  "url": "https://example.com/scan.pdf",
  "fileName": "scan.pdf",
  "kind": "pdf",
  "page": 1,
  "totalPages": 3,
  "languages": ["eng", "ukr"],
  "text": "Quarterly Supply Report\n\nThe warehouse in Lviv received 1,240 pallets...",
  "meanConfidence": 95.0,
  "lines": [{ "text": "Quarterly Supply Report", "confidence": 96.3, "bbox": [63, 59, 766, 55] }],
  "width": 2480,
  "height": 3508
}
```

`bbox` is `[x, y, width, height]` in pixels. A file that cannot be downloaded or opened gets an `error` field instead
and is **not charged**.

## Pricing

| Event | Price | What counts |
|---|---|---|
| `image` | **$1.50 per 1,000** | one OCR'd image, TIFF frame or PDF page |

Plus Apify's standard start fee of $0.05 per 1,000 runs. The run stops before it would exceed your maximum charge per run.

## Related Actors

- [Document to Markdown for AI](https://apify.com/ai_admin/document-to-markdown) — PDFs, scans and Office files → Markdown, tables, RAG chunks
- [PDF to Image & Image Converter](https://apify.com/ai_admin/pdf-image-converter) — PDF ↔ PNG/JPG/WebP, HEIC → JPG
- [Office to PDF & PDF/A](https://apify.com/ai_admin/office-to-pdf) — Word, Excel, PowerPoint, HTML → PDF/PDF-A
- [Audio & Video Transcriber](https://apify.com/ai_admin/audio-transcriber) — speech to text, SRT and VTT subtitles

Open source: [github.com/AndriyVK/-apify-document-tools](https://github.com/AndriyVK/-apify-document-tools)

## Use with AI agents and code

- **MCP (Claude, Cursor, VS Code, any MCP client):** add `https://mcp.apify.com?tools=ai_admin/image-to-text-ocr` as an MCP server —
  the agent gets one tool with this Actor's input schema and pays per use through your Apify account.
- **One HTTP call that returns the results:**

```bash
curl -X POST "https://api.apify.com/v2/acts/ai_admin~image-to-text-ocr/run-sync-get-dataset-items?token=$APIFY_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"sources": [{"url": "https://api.apify.com/v2/key-value-stores/FloomuI2DrQCJazY8/records/image-en.png"}], "languages": ["eng"], "includeLines": true}'
```
- **Agentic payments:** the Actor is enabled for Apify's agentic payments (x402), so autonomous agents can pay per run.

## Limits

- Handwriting is recognised poorly; printed text works best. Photos should be in focus, at least ~20 px letter height.
- Password-protected PDFs are not supported. Maximum download size is 200 MB per file.
- For PDFs with a text layer (not scans) use Document to Markdown — it is faster and exact.
