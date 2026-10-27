# Document to Markdown for AI: PDF, OCR, Word, Excel, PowerPoint

Turn any business document into clean Markdown, JSON tables and RAG-ready chunks — one Actor for PDF, scanned PDF,
images, DOCX/DOC, XLSX/XLS, PPTX/PPT, ODT/ODS/ODP, RTF and HTML.

- **Every common format in one place.** Modern and legacy Office files (DOC, XLS, PPT, RTF, OpenDocument) are converted too.
- **OCR only where it is needed.** Pages with a text layer are read directly. Scanned pages and images go through
  Tesseract OCR in 11 languages, including **Ukrainian and Russian** (Cyrillic) as well as English, German, French,
  Spanish, Italian, Portuguese, Polish, Dutch and Czech.
- **Structure kept for LLMs.** Headings (`#`, `##`), lists and tables as Markdown, every table also as JSON rows,
  optional chunks with their nearest heading for vector databases.

Spreadsheet cells keep their values exactly: text stays text (`96.50` is not turned into `96.5`), numbers follow the
cell's number format (`1,234.50`).

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

Pay per event — you pay only for converted pages:

| Event | Price | What counts |
|---|---|---|
| `page` | **$1 per 1,000** | a PDF page read from its text layer; for Office, HTML and text files — every 3,000 characters of output (at least 1 per document) |
| `ocr-page` | **$4 per 1,000** | a scanned PDF page or an image frame read with OCR |

Plus Apify's standard start fee of $0.05 per 1,000 runs. Failed documents and skipped pages are not charged, and pages
with a text layer or blank pages are never charged as OCR. The run stops before it
would exceed your maximum charge per run.

## Use with AI agents (MCP)

The Actor works as a tool in the [Apify MCP server](https://mcp.apify.com): add `ai_admin/document-to-markdown` to
your client's Actor list and ask the agent to convert a document by URL.

Open source: [github.com/AndriyVK/-apify-document-tools](https://github.com/AndriyVK/-apify-document-tools)

## Limits

- Tables are detected in PDFs with a text layer and in Office/HTML files. Tables in scanned pages come out as OCR text.
- RTF files keep no heading styles, so their headings arrive as plain paragraphs.
- Password-protected files are not supported. Maximum download size is 200 MB.

## Feedback

Found a document that converts badly? Open an issue with a link to a sample (or a similar public file) — fixes for real
documents get priority.
