# Office to PDF & PDF/A: Word, Excel, PowerPoint, HTML, Images

Convert office documents to PDF — or to archival **PDF/A-2b** — in bulk, with a download link for every file.
Word, Excel, PowerPoint, OpenDocument, RTF, TXT, CSV, HTML and images, modern and legacy formats alike.

- **All common formats.** DOCX, DOC, ODT, RTF, TXT, HTML, XLSX, XLS, ODS, CSV, PPTX, PPT, ODP, PNG, JPG, TIFF, SVG.
- **PDF/A for archives and e-filing.** One switch produces PDF/A-2b, the format courts, tax portals and archives ask for.
- **Faithful layout.** LibreOffice with metric-compatible fonts (Calibri, Cambria, Arial, Times New Roman, Courier
  equivalents) keeps line and page breaks; Cyrillic, Greek and most Latin scripts are covered.
- **Batch and merge.** Convert hundreds of files in one run and optionally get them merged into a single PDF.

## Why this Actor

| | This Actor | Typical alternatives |
|---|---|---|
| **Archival PDF/A-2b** | One switch — for courts, tax portals, e-invoicing and long-term archives | Usually plain PDF only |
| **Legacy files** | DOC, XLS, PPT, RTF and OpenDocument convert as well as DOCX/XLSX/PPTX | Modern formats only, or none at all |
| **Price** | **$10 per 1,000 documents**, any number of pages | Online converters: subscriptions or per-page fees; most Store PDF tools only render HTML/URLs ($5–25 per 1,000) |
| **Batch + merge** | Hundreds of files per run, optional single merged PDF, links for every file | Often one file at a time |
| **Privacy** | LibreOffice runs inside the Actor; files are not sent to a third-party conversion API | Many converters upload your files to an external service |

## Input

```json
{
  "sources": [
    { "url": "https://example.com/contract.docx" },
    { "url": "https://example.com/price-list.xlsx" }
  ],
  "pdfA": false,
  "mergeIntoOne": true
}
```

| Field | Meaning |
|---|---|
| `sources` | File URLs. Files in your own Apify key-value store work too: set the store's access to "Anyone with ID can read" and use `https://api.apify.com/v2/key-value-stores/<store ID>/records/<key>` (the Actor runs with limited permissions and does not use your token). |
| `pdfA` | Produce PDF/A-2b instead of plain PDF |
| `mergeIntoOne` | Also return `merged.pdf` with all converted documents in input order (no extra charge) |

## Output

One dataset item per document:

```json
{
  "url": "https://example.com/contract.docx",
  "fileName": "contract.docx",
  "format": "docx",
  "pdfUrl": "https://api.apify.com/v2/key-value-stores/.../records/0001-contract.pdf?signature=...",
  "pdfKey": "0001-contract.pdf",
  "pages": 4,
  "bytes": 58211,
  "pdfA": false
}
```

The PDFs are stored in the run's key-value store; `pdfUrl` is a ready download link. A document that cannot be
downloaded or opened (damaged, password-protected, wrong extension) gets an `error` field instead and is **not charged**.

## Pricing

Pay per event:

| Event | Price | What counts |
|---|---|---|
| `document` | **$10 per 1,000** | one successfully converted document (any number of pages) |

Plus Apify's standard start fee of $0.05 per 1,000 runs. Merging is free. The run converts only as many documents as fit
under your maximum charge per run.

## Use with AI agents and code

- **MCP (Claude, Cursor, VS Code, any MCP client):** add `https://mcp.apify.com?tools=ai_admin/office-to-pdf` as an MCP server —
  the agent gets one tool with this Actor's input schema and pays per use through your Apify account.
- **One HTTP call that returns the results:**

```bash
curl -X POST "https://api.apify.com/v2/acts/ai_admin~office-to-pdf/run-sync-get-dataset-items?token=$APIFY_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"sources": [{"url": "https://api.apify.com/v2/key-value-stores/FloomuI2DrQCJazY8/records/doc-en.docx"}, {"url": "https://api.apify.com/v2/key-value-stores/FloomuI2DrQCJazY8/records/sheet-en.xlsx"}], "pdfA": true, "mergeIntoOne": false}'
```
- **Agentic payments:** the Actor is enabled for Apify's agentic payments (x402), so autonomous agents can pay per run.

Open source: [github.com/AndriyVK/-apify-document-tools](https://github.com/AndriyVK/-apify-document-tools)

## Limits

- Password-protected files are not supported. Maximum download size is 200 MB per file.
- Fonts that are not installed are replaced by metric-compatible ones; exotic fonts may change the look slightly.
- Multi-page TIFF images may be converted to their first page only.
- Macros are not executed (LibreOffice default macro security).
