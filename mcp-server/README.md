# MCP server: document & media tools for AI agents

Four tools for Claude, Cursor, ChatGPT and any other MCP client, backed by open-source Actors on Apify:

| Tool | What it does | Price (billed by Apify) |
|---|---|---|
| `convert_document_to_markdown` | PDF (text and scanned, OCR in 11 languages), images, DOCX/DOC, XLSX/XLS, PPTX/PPT, ODT, RTF, HTML → Markdown, JSON tables, RAG chunks | $1 / 1,000 text pages, $4 / 1,000 OCR pages |
| `convert_office_to_pdf` | Word, Excel, PowerPoint, OpenDocument, RTF, HTML, images → PDF or PDF/A-2b, optional merge | $10 / 1,000 documents |
| `convert_pdf_or_images` | PDF pages → PNG/JPG/WebP/TIFF, images ↔ PDF, iPhone HEIC → JPG, resize | $2 / 1,000 images |
| `transcribe_audio` | Audio and video → text, timestamped segments, SRT/VTT (Whisper large-v3, 99 languages) | $5 / 1,000 minutes |

Every tool takes public file URLs and a `max_charge_usd` safety limit per call (default $1).

## Option 1 — hosted (no install)

Use Apify's hosted MCP server with exactly these four tools:

```json
{
  "mcpServers": {
    "document-tools": {
      "url": "https://mcp.apify.com?tools=ai_admin/document-to-markdown,ai_admin/office-to-pdf,ai_admin/pdf-image-converter,ai_admin/audio-transcriber"
    }
  }
}
```

On first connection your browser opens to sign in to Apify (or pass `Authorization: Bearer <APIFY_TOKEN>`).

## Option 2 — local (stdio)

```bash
git clone https://github.com/AndriyVK/-apify-document-tools
cd -- -apify-document-tools/mcp-server
pip install -r requirements.txt
```

```json
{
  "mcpServers": {
    "document-tools": {
      "command": "python",
      "args": ["/path/to/-apify-document-tools/mcp-server/server.py"],
      "env": { "APIFY_TOKEN": "your Apify API token" }
    }
  }
}
```

Get the token in Apify Console → Settings → API & Integrations. New Apify accounts include free monthly usage credit.

## Source

The Actors behind the tools live in the parent folders of this repository (MIT licence).
