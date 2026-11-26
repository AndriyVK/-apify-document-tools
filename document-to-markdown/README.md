# Document to Markdown for AI: PDF, OCR, Word, Excel, PowerPoint

Turn any business document into clean Markdown, JSON tables and RAG-ready chunks - one Actor for PDF, scanned PDF,
images, DOCX/DOC, XLSX/XLS, PPTX/PPT, ODT/ODS/ODP, RTF and HTML.

- **Every common format in one place.** Modern and legacy Office files (DOC, XLS, PPT, RTF, OpenDocument) are converted too.
- **OCR only where it is needed.** Pages with a text layer are read directly. Scanned pages and images go through
  Tesseract OCR in 11 languages, including **Ukrainian and Russian** (Cyrillic) as well as English, German, French,
  Spanish, Italian, Portuguese, Polish, Dutch and Czech.
- **Structure kept for LLMs.** Headings (`#`, `##`), lists and tables as Markdown, every table also as JSON rows,
  optional chunks with their nearest heading for vector databases.

Spreadsheet cells keep their values exactly: text stays text (`96.50` is not turned into `96.5`), numbers follow the
cell's number format (`1,234.50`).

## Why this Actor

| | This Actor | Typical alternatives in the Apify Store (Oct 2026) |
|---|---|---|
| **Price** | **$2 per 1,000 text pages ($1.50 on Gold+), $4 per 1,000 OCR pages** - you pay per page, OCR only for scanned pages | $3-5 per 1,000 PDFs plus $15-20 per 1,000 OCR pages |
| **Formats** | PDF, scans, images, DOCX/DOC, XLSX/XLS, PPTX/PPT, ODT/ODS/ODP, RTF, HTML - one Actor | Mostly PDF only; Office files need another tool |
| **Structure** | Headings, lists, tables as Markdown **and** JSON rows, RAG chunks with their heading | Often plain text, tables lost |
| **Cyrillic** | Ukrainian and Russian OCR built in | English-first OCR |
| **PDF control** | Page ranges, protected PDFs, header/footer and page-number removal | Some offer these, many do not |

## Input

```json
{
  "sources": [
    { "url": "https://example.com/report.pdf" },
    { "url": "https://example.com/contract.docx" }
  ],
  "ocrMode": "auto",
  "ocrLanguages": ["eng", "ukr"],
  "includeTables": true,
  "chunkSize": 1500
}
```

| Field | Meaning |
|---|---|
| `sources` | Document URLs. Files in your own Apify key-value store work too: set the store's access to "Anyone with ID can read" and use `https://api.apify.com/v2/key-value-stores/<store ID>/records/<key>` (the Actor runs with limited permissions and does not use your token). |
| `ocrMode` | `auto` (scanned pages only), `always`, `never` |
| `ocrLanguages` | Languages expected in scans and images |
| `includeTables` | Return tables as JSON rows (header first) |
| `chunkSize` | Characters per RAG chunk, `0` = no chunks |
| `maxPagesPerDocument` | Pages beyond the limit are skipped and not charged |
| `pageRange` | PDF pages to convert, e.g. `1-3, 5, 10-` (page 10 to the end); only these pages are charged |
| `password` | Password for protected PDFs (stored encrypted, never logged) |
| `removeHeadersFooters` | Drop running headers, footers and page numbers that repeat on most PDF pages - clean text for RAG |

## Output

One dataset item per document:

```json
{
  "url": "https://example.com/report.pdf",
  "fileName": "report.pdf",
  "format": "pdf",
  "sourcePages": 3,
  "textPages": 2,
  "ocrPages": 1,
  "characters": 5120,
  "metadata": { "title": "Quarterly Supply Report", "author": "..." },
  "markdown": "# Quarterly Supply Report\n\nThe warehouse in Lviv received 1,240 pallets...\n\n| Item | Quantity | Price |\n| --- | --- | --- |\n| Cement | 420 | 96.50 |",
  "tables": [[["Item", "Quantity", "Price"], ["Cement", "420", "96.50"]]],
  "chunks": [{ "index": 0, "heading": "Quarterly Supply Report", "text": "..." }],
  "warnings": [],
  "seconds": 1.4
}
```

A document that cannot be downloaded or read gets an `error` field instead and is **not charged**.
Markdown longer than 4 million characters is stored in full in the run's key-value store (`markdownKey`).

## Pricing

Pay per event - you pay only for converted pages:

| Event | Price | What counts |
|---|---|---|
| `page` | **$2 per 1,000** ($2.50 on the free plan, $1.50 on Gold and higher) | a PDF page read from its text layer; for Office, HTML and text files - every 3,000 characters of output (at least 1 per document) |
| `ocr-page` | **$4 per 1,000** | a scanned PDF page or an image frame read with OCR |

Plus Apify's standard start fee of $0.05 per 1,000 runs. Failed documents and skipped pages are not charged, and pages
with a text layer or blank pages are never charged as OCR. The run stops before it
would exceed your maximum charge per run.

## Use with AI agents and code

- **MCP (Claude, Cursor, VS Code, any MCP client):** add `https://mcp.apify.com?tools=ai_admin/document-to-markdown` as an MCP server -
  the agent gets one tool with this Actor's input schema and pays per use through your Apify account.
- **One HTTP call that returns the results:**

```bash
curl -X POST "https://api.apify.com/v2/acts/ai_admin~document-to-markdown/run-sync-get-dataset-items?token=$APIFY_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"sources": [{"url": "https://api.apify.com/v2/key-value-stores/FloomuI2DrQCJazY8/records/text-en.pdf"}, {"url": "https://api.apify.com/v2/key-value-stores/FloomuI2DrQCJazY8/records/doc-uk.docx"}], "ocrMode": "auto", "ocrLanguages": ["eng", "ukr"], "includeTables": true}'
```
- **Agentic payments:** the Actor is enabled for Apify's agentic payments (x402), so autonomous agents can pay per run.

Open source: [github.com/AndriyVK/-apify-document-tools](https://github.com/AndriyVK/-apify-document-tools)

## Guides

- [Ukrainian scanned PDFs to Markdown for RAG and LLMs](https://andriyvk.github.io/ukrainian-scans-to-markdown/)
- [Ukrainian scans, invoices, Word and Excel to Markdown - 5 Apify Actors on 7 files](https://andriyvk.github.io/ukrainian-documents-to-markdown-5-actors-compared/)
- [MCP server for document and media tools - OCR, PDF and audio tools for Claude or Cursor](https://andriyvk.github.io/mcp-document-tools-for-ai-agents/)

## Related Actors

- [Image to Text OCR](https://apify.com/ai_admin/image-to-text-ocr) - photos and screenshots to text with line and word positions, tables
- [Office to PDF & PDF/A](https://apify.com/ai_admin/office-to-pdf) - Word, Excel, PowerPoint, HTML → PDF/PDF-A
- [PDF to Image & Image Converter](https://apify.com/ai_admin/pdf-image-converter) - PDF ↔ PNG/JPG/WebP, HEIC → JPG
- [Audio & Video Transcriber](https://apify.com/ai_admin/audio-transcriber) - speech to text, SRT and VTT subtitles

## Limits

- Tables are detected in PDFs with a text layer, in Office/HTML files and in scans and images: ruled tables (also on
  noisy or slightly rotated scans) and tables without rules that have at least 3 rows and 3 columns with clear gaps.
  Merged cells and multi-line cells in tables without rules are not reconstructed.
- With mixed languages such as `["ukr", "eng"]`, Cyrillic words that OCR read with Latin look-alike letters
  (`Apmatypa`) are put back in Cyrillic (`Арматура`) when the Cyrillic word is in Tesseract's dictionary and the
  Latin one is not an English word.
- RTF files keep no heading styles, so their headings arrive as plain paragraphs.
- Password-protected files are not supported. Maximum download size is 200 MB.

## Feedback

Found a document that converts badly? Open an issue with a link to a sample (or a similar public file) - fixes for real
documents get priority.
