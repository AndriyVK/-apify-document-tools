# Audio & Video Transcriber: Speech to Text, SRT/VTT Subtitles

Turn audio and video files into text, timestamped segments and ready-to-use **SRT / VTT subtitles** with OpenAI's
Whisper large-v3 model — 99 languages, automatic language detection, files of any length.

- **Any audio or video format.** MP3, WAV, M4A, AAC, OGG, OPUS, FLAC, MP4, MOV, MKV, WebM, AVI… The speech track is
  extracted automatically.
- **Long recordings.** Meetings, lectures, podcasts and interviews are split into 10-minute parts and stitched back
  with continuous timestamps.
- **Strong non-English support.** Whisper large-v3 handles Ukrainian, Polish, German, Spanish, Russian and 90+ more
  languages; a vocabulary hint fixes the spelling of names and terms.
- **Subtitles included.** SRT and WebVTT files with download links, plus segments as JSON.

## Input

```json
{
  "sources": [{ "url": "https://example.com/interview.mp3" }, { "url": "https://example.com/webinar.mp4" }],
  "language": "uk",
  "quality": "accurate",
  "vocabulary": "Lviv, Kyivstar, PrivatBank",
  "subtitles": true
}
```

| Field | Meaning |
|---|---|
| `sources` | URLs of audio or video files. Files in your own Apify key-value store work too: set the store's access to "Anyone with ID can read" and use `https://api.apify.com/v2/key-value-stores/<store ID>/records/<key>` (the Actor runs with limited permissions and does not use your token). |
| `language` | ISO code (`en`, `uk`, `de`…) or empty for automatic detection |
| `quality` | `accurate` (Whisper large-v3, default) or `fast` (large-v3-turbo) — same price |
| `vocabulary` | Names and terms to spell correctly |
| `subtitles` | Save SRT and VTT files (free) |

## Output

```json
{
  "url": "https://example.com/interview.mp3",
  "fileName": "interview.mp3",
  "language": "Ukrainian",
  "durationSeconds": 1834.2,
  "billedMinutes": 31,
  "model": "whisper-large-v3",
  "text": "Добрий день! Сьогодні ми поговоримо про…",
  "segments": [{ "start": 0.0, "end": 4.6, "text": "Добрий день!" }],
  "srtUrl": "https://api.apify.com/v2/key-value-stores/.../records/0001-interview.srt?signature=...",
  "vttUrl": "https://api.apify.com/v2/key-value-stores/.../records/0001-interview.vtt?signature=..."
}
```

A file that cannot be downloaded or has no audio track gets an `error` field instead and is **not charged**.

## Pricing

| Event | Price | What counts |
|---|---|---|
| `audio-minute` | **$5 per 1,000 minutes** | every started minute of transcribed audio (at least 1 per file) |

Plus Apify's standard start fee of $0.05 per 1,000 runs. Subtitles are free. The run transcribes only as many minutes as
fit under your maximum charge per run and marks the item with a warning.

## Privacy

The speech track is sent to [Groq](https://groq.com)'s speech-to-text API, which runs the Whisper model; see
[Groq's privacy policy](https://groq.com/privacy-policy/). This Actor keeps files only in your own Apify run storage.

## Related Actors

- [Document to Markdown for AI](https://apify.com/ai_admin/document-to-markdown) — PDFs, scans, Office files → Markdown
- [Office to PDF & PDF/A](https://apify.com/ai_admin/office-to-pdf) · [PDF to Image & Image Converter](https://apify.com/ai_admin/pdf-image-converter)

Open source: [github.com/AndriyVK/-apify-document-tools](https://github.com/AndriyVK/-apify-document-tools)

## Limits

- YouTube and other streaming pages are not supported — provide a direct link to the media file.
- Maximum download size is 200 MB per file.
- Speaker labels (diarization) are not included.
