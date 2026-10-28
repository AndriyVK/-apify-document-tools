# Text to Speech: PDF, DOCX → MP3 + Subtitles, Ukrainian +22 More

Turn text, articles, PDFs and Word documents into natural-sounding speech — MP3, WAV or OGG — with SRT and VTT
subtitles. Neural voices run inside the Actor: no API key, no account elsewhere, no per-character fees.

**Listen first:** [Ukrainian — Mykyta (recommended)](https://api.apify.com/v2/key-value-stores/FloomuI2DrQCJazY8/records/tts-sample-uk_UA-mykyta-high.mp3) · [Ukrainian — Tetiana](https://api.apify.com/v2/key-value-stores/FloomuI2DrQCJazY8/records/tts-sample-uk_UA-tetiana-high.mp3) ·
[English HQ — LJSpeech](https://api.apify.com/v2/key-value-stores/FloomuI2DrQCJazY8/records/tts-sample-en_US-ljspeech-high.mp3) · [English fast — John](https://api.apify.com/v2/key-value-stores/FloomuI2DrQCJazY8/records/tts-sample-en_US-john-medium.mp3) ·
[German — Thorsten](https://api.apify.com/v2/key-value-stores/FloomuI2DrQCJazY8/records/tts-sample-de_DE-thorsten-high.mp3)

## Why this Actor

| | This Actor | Typical alternatives |
|---|---|---|
| **Commercial use** | Every voice is CC0, public domain, Apache 2.0 or CC BY 4.0 — safe for YouTube, courses, ads and client work | Many free voices are "non-commercial only" (CC BY-NC); unofficial Edge or Google voices may break those services' terms |
| **Ukrainian** | 3 natural high-quality Ukrainian voices (українська озвучка тексту), word stress from a Ukrainian dictionary, lively intonation | Rarely offered at all; open voices often stress Ukrainian words wrongly |
| **Documents in** | PDF, DOCX, HTML, Markdown, TXT — menus, scripts and Markdown symbols skipped | Plain text only; you copy and clean the text yourself |
| **Subtitles** | SRT + VTT timed per sentence, free | Extra tool or extra fee |
| **Cost** | Per minute of audio; no API key or subscription elsewhere | ElevenLabs-style wrappers need your own paid key and bill per character |

## Features

- **37 neural voices in 23 languages:** Ukrainian, US and UK English, German, French, Spanish, Italian, Polish,
  Portuguese, Dutch, Czech, Russian, Romanian, Finnish, Hungarian, Slovak, Swedish, Danish, Greek, Latvian, Slovenian,
  Chinese, Persian, Vietnamese.
- **Speed control** 0.5×–2×, natural pauses between sentences and paragraphs.
- **Delivery:** "Lively" (more varied intonation) or "Standard" (even and calm); "Auto" uses Lively for Ukrainian.
- **Audiobooks, podcasts, e-learning, accessibility:** long texts (up to 1,000,000 characters per item) are read
  sentence by sentence.

## Input

```json
{
  "text": "Hello! This is a natural-sounding neural voice.",
  "sources": [{ "url": "https://example.com/article.pdf" }],
  "voice": "en_US-john-medium",
  "speed": 1.12,
  "style": "auto",
  "format": "mp3",
  "subtitles": true
}
```

| Field | Meaning |
|---|---|
| `text` | Text to read; blank lines separate paragraphs |
| `sources` | Links to TXT, Markdown, HTML, PDF or DOCX files — one audio file each. Files in your own Apify key-value store work too: set the store's access to "Anyone with ID can read" and use `https://api.apify.com/v2/key-value-stores/<store ID>/records/<key>` (the Actor runs with limited permissions and does not use your token). |
| `voice` | Voice ID from the table below |
| `speed` | 0.5–2; default 1.12 (smoother, fewer hesitations than the voice's own pace 1.0) |
| `style` | `auto` (default), `lively` or `standard` |
| `format` | `mp3` (64 kbit/s), `wav`, `ogg` (Opus) |
| `subtitles` | Also return `.srt` and `.vtt` |
| `maxCharactersPerItem` | Longer texts are cut; ~750–900 characters ≈ 1 minute of speech |

## Voices

| Language | Voice IDs |
|---|---|
| Ukrainian | `uk_UA-tetiana-high`, `uk_UA-mykyta-high`, `uk_UA-oleksa-high` |
| English (US) | `en_US-ljspeech-high`, `en_US-john-medium`, `en_US-kristin-medium`, `en_US-bryce-medium`, `en_US-norman-medium`, `en_US-joe-medium` |
| English (UK) | `en_GB-cori-high`, `en_GB-alba-medium` |
| German | `de_DE-thorsten-high`, `de_DE-kerstin-low` |
| French | `fr_FR-siwis-medium`, `fr_FR-gilles-low` |
| Spanish (Spain) | `es_ES-davefx-medium` |
| Spanish (Mexico) | `es_MX-claude-high` |
| Italian | `it_IT-serena-high` |
| Polish | `pl_PL-gosia-medium`, `pl_PL-darkman-medium` |
| Portuguese (Brazil) | `pt_BR-faber-medium` |
| Dutch | `nl_NL-pim-medium` |
| Czech | `cs_CZ-jirka-medium` |
| Russian | `ru_RU-denis-medium`, `ru_RU-dmitri-medium` |
| Romanian | `ro_RO-mihai-medium` |
| Finnish | `fi_FI-harri-medium` |
| Hungarian | `hu_HU-anna-medium` |
| Slovak | `sk_SK-lili-medium` |
| Swedish | `sv_SE-nst-medium` |
| Danish | `da_DK-talesyntese-medium` |
| Greek | `el_GR-rapunzelina-medium` |
| Latvian | `lv_LV-aivars-medium` |
| Slovenian | `sl_SI-artur-medium` |
| Chinese | `zh_CN-chaowen-medium` |
| Persian | `fa_IR-amir-medium` |
| Vietnamese | `vi_VN-vais1000-medium` |

`high` voices sound best and cost more per minute; `medium` and `low` are a little more synthetic, but about 7× faster.

## Output

```json
{
  "url": "https://example.com/article.pdf",
  "voice": "en_US-ljspeech-high",
  "language": "English (US)",
  "format": "mp3",
  "characters": 5240,
  "truncated": false,
  "durationSeconds": 352.4,
  "sentences": 61,
  "audioUrl": "https://api.apify.com/v2/key-value-stores/.../records/0002-article.mp3",
  "srtUrl": "https://api.apify.com/v2/key-value-stores/.../records/0002-article.srt",
  "vttUrl": "https://api.apify.com/v2/key-value-stores/.../records/0002-article.vtt"
}
```

A document that cannot be downloaded or read gets an `error` field instead and is **not charged**.

## Pricing

| Event | Price | What counts |
|---|---|---|
| `audio-minute` | **$10 per 1,000** (1 cent a minute, $0.60 per hour) | one started minute of audio with a `medium` or `low` voice |
| `hq-audio-minute` | **$40 per 1,000** (4 cents a minute, $2.40 per hour) | one started minute of audio with a `high` voice (needs ~7× more computing) |

Plus Apify's standard start fee of $0.05 per 1,000 runs. Subtitles are free. The run stops before it would exceed your
maximum charge per run.

## Related Actors

- [Audio & Video Transcriber](https://apify.com/ai_admin/audio-transcriber) — the other direction: speech to text and subtitles
- [Document to Markdown for AI](https://apify.com/ai_admin/document-to-markdown) — PDFs, scans and Office files → Markdown
- [Image to Text OCR](https://apify.com/ai_admin/image-to-text-ocr) — scanned pages to text, then to speech

Open source: [github.com/AndriyVK/-apify-document-tools](https://github.com/AndriyVK/-apify-document-tools)

## Use with AI agents and code

- **MCP (Claude, Cursor, VS Code, any MCP client):** add `https://mcp.apify.com?tools=ai_admin/text-to-speech` as an MCP server —
  the agent gets one tool with this Actor's input schema and pays per use through your Apify account.
- **One HTTP call that returns the results:**

```bash
curl -X POST "https://api.apify.com/v2/acts/ai_admin~text-to-speech/run-sync-get-dataset-items?token=$APIFY_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"text": "Hello! This is a natural-sounding neural voice.", "voice": "en_US-john-medium", "format": "mp3", "subtitles": true}'
```

## Limits

- Scanned PDFs without a text layer are not read — run them through Image to Text OCR first.
- Numbers, abbreviations and foreign words are read by the voice's rules and may sound unusual.
- Speech engine: [Piper](https://github.com/OHF-Voice/piper1-gpl) (GPL-3.0). Voice models: [rhasspy/piper-voices](https://huggingface.co/rhasspy/piper-voices);
  CC BY 4.0 voices (`en_GB-alba`, `fr_FR-siwis`, `it_IT-serena`, `sl_SI-artur`, `vi_VN-vais1000`) are credited to their
  dataset authors as listed in each voice's model card.
