# PDF to Image & Image Converter: PNG, JPG, WebP, HEIC, PDF

Render PDF pages to images, turn images into PDF and convert images between formats — including iPhone **HEIC** photos —
in bulk, with a download link for every file.

- **PDF → PNG, JPG, WebP or TIFF.** Choose the DPI (72 for thumbnails, 300 for print) and the pages (`1-3,5,8-`).
- **Images → PDF.** One PDF per image, or all images merged into a single PDF.
- **Image format conversion.** PNG, JPG, WebP, TIFF, GIF, BMP, HEIC/HEIF and AVIF in, PNG/JPG/WebP/TIFF out;
  multi-page TIFFs are split into frames; EXIF rotation is applied; optional downscaling.
- **ZIP of everything** and per-file download links in the dataset.

## Input

```json
{
  "sources": [{ "url": "https://example.com/catalog.pdf" }, { "url": "https://example.com/IMG_0042.heic" }],
  "outputFormat": "jpg",
  "dpi": 150,
  "pages": "1-3",
  "quality": 85,
  "maxWidth": 1600,
  "zipAll": true
}
```

| Field | Meaning |
|---|---|
| `sources` | URLs of PDFs or images. Files in your own Apify key-value store work too: set the store's access to "Anyone with ID can read" and use `https://api.apify.com/v2/key-value-stores/<store ID>/records/<key>` (the Actor runs with limited permissions and does not use your token). |
| `outputFormat` | `png`, `jpg`, `webp`, `tiff`, or `pdf` (images only) |
| `dpi` | Resolution for PDF pages, 36–600 |
| `pages` | PDF pages to render, empty = all |
| `quality` | JPG/WebP quality 10–100 |
| `maxWidth` | Downscale wider images, 0 = keep size |
| `mergeImagesIntoOnePdf` | With `pdf` output: also return `merged.pdf` (free) |
| `zipAll` | Also return `all-files.zip` (free) |

## Output

```json
{
  "url": "https://example.com/catalog.pdf",
  "fileName": "catalog.pdf",
  "kind": "pdf",
  "outputFormat": "jpeg",
  "sourcePages": 12,
  "count": 3,
  "files": [
    { "key": "0001-catalog-p0001.jpg", "url": "https://api.apify.com/v2/key-value-stores/.../records/0001-catalog-p0001.jpg?signature=...", "bytes": 182311 }
  ],
  "warnings": []
}
```

A file that cannot be downloaded or opened gets an `error` field instead and is **not charged**.

## Pricing

| Event | Price | What counts |
|---|---|---|
| `page` | **$2 per 1,000** | one produced image (a rendered PDF page or a converted image frame), or one PDF made from an image |

Plus Apify's standard start fee of $0.05 per 1,000 runs. Merging and ZIP are free. The run stops before it would exceed
your maximum charge per run.

## Related Actors

- [Office to PDF & PDF/A](https://apify.com/ai_admin/office-to-pdf) — Word, Excel, PowerPoint, HTML → PDF/PDF-A
- [Document to Markdown for AI](https://apify.com/ai_admin/document-to-markdown) — PDFs, scans and Office files → Markdown, tables, RAG chunks

Open source: [github.com/AndriyVK/-apify-document-tools](https://github.com/AndriyVK/-apify-document-tools)

## Limits

- Password-protected PDFs are not supported. Maximum download size is 200 MB per file.
- Very large pages at high DPI produce large images; use `maxWidth` to keep them small.
