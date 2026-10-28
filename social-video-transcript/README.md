# Video Transcript & Translation: YouTube, TikTok, Instagram, Facebook

Paste video links, get the **transcript, timestamped segments, SRT / VTT subtitles and an optional translation** —
for YouTube videos and Shorts, TikTok, Instagram Reels, Facebook videos and Reels, X (Twitter), Vimeo and 1,000+ other
sites.

## What makes it different

1. **Translation into Ukrainian and 20 other languages in the same run.** You get the translated transcript and
   ready-to-use SRT/VTT subtitles for it, not only for the original. Of the transcript Actors we found in the Apify
   Store (October 2026), only one other offers translation, at $0.045 / $0.013 per video. Here it costs from $0.007
   per minute. Languages: English, Ukrainian, Russian, German, French, Spanish, Portuguese, Italian, Polish, Dutch,
   Turkish, Czech, Romanian, Swedish, Arabic, Hindi, Indonesian, Vietnamese, Chinese, Japanese, Korean.
2. **All platforms in one Actor.** One input list takes YouTube videos and Shorts, TikTok, Instagram Reels, Facebook
   videos and Reels, X (Twitter), Vimeo and 1,000+ other sites. Most alternatives cover one platform per Actor.
3. **Works when there are no captions.** Captions are used first: fast, any length, one flat price. Without them
   the speech is recognised with **Whisper large-v3**, so TikToks, Reels and YouTube videos without captions still
   get a transcript. Many YouTube transcript tools return nothing in that case.
4. **Failed videos are free.** Private, deleted, blocked or too-long videos get an `error` field and are not
   charged. You pay only for the transcripts you receive.
5. **No API key of your own.** You don't need an OpenAI or any other account: you pay per video through Apify.

Also included: timestamped segments, SRT and VTT subtitle files with download links, and the video's title, author,
upload date, duration and views next to the text. Speech recognition covers 99 spoken languages, including
Ukrainian. Recognition in Ukrainian is common; what is rare is translation into Ukrainian and the other languages.

## Input

```json
{
  "videoUrls": [
    "https://www.youtube.com/watch?v=MLgYJh6OFbY",
    "https://www.tiktok.com/@nasa/video/7698805564884733198"
  ],
  "translateTo": "es",
  "useCaptions": true,
  "maxDurationMinutes": 60
}
```

| Field | Meaning |
|---|---|
| `videoUrls` | Links to single videos. Profile, playlist and search pages are not supported. |
| `translateTo` | Optional language code (`en`, `es`, `de`, `uk`…) to also translate the transcript and subtitles |
| `language` | Spoken language code, or empty to detect it automatically |
| `useCaptions` | Use the video's captions when available (default). Off: always recognise the speech with Whisper |
| `maxDurationMinutes` | Videos without captions longer than this are skipped (free). Captions work for any length |
| `quality` | `accurate` (Whisper large-v3, default) or `fast` (large-v3-turbo) — same price |
| `subtitles` | Save SRT and VTT files (free) |
| `includeSegments` | Include timestamped segments, not only the full text |

## Output

```json
{
  "url": "https://www.tiktok.com/@nasa/video/7698805564884733198",
  "platform": "tiktok",
  "title": "…",
  "author": "nasa",
  "uploadDate": "20261020",
  "durationSeconds": 45,
  "language": "en",
  "transcriptSource": "speech-recognition",
  "text": "…",
  "segments": [{ "start": 0.0, "end": 3.2, "text": "…" }],
  "srtUrl": "https://api.apify.com/v2/key-value-stores/.../records/0001-7698805564884733198.srt?signature=...",
  "vttUrl": "https://api.apify.com/v2/key-value-stores/.../records/0001-7698805564884733198.vtt?signature=...",
  "translation": { "language": "es", "text": "…", "segments": [], "srtUrl": "…", "vttUrl": "…" }
}
```

`transcriptSource` is `uploaded-captions`, `automatic-captions` or `speech-recognition`.

## Pricing

You pay per result. On any paid Apify plan you get the lower price.

| Event | Free plan | Paid plans | What counts |
|---|---|---|---|
| `video` | $15 / 1,000 | **$10 / 1,000 videos** | one transcript, from captions (any length) or up to 3 minutes of recognised speech |
| `audio-minute` | $5 / 1,000 | $4 / 1,000 minutes | speech recognition only (TikTok, Instagram, Facebook, X…): each started minute after the first 3 |
| `youtube-audio-minute` | $12 / 1,000 | $10 / 1,000 minutes | YouTube videos **without** captions: each started minute, charged instead of `video` |
| `translated-minute` | $10 / 1,000 | $7 / 1,000 minutes | only with `translateTo`: each started minute of translated video (text and subtitles) |

Examples on a paid plan:
- a YouTube video with captions: $0.01, whatever its length;
- a 1-minute TikTok: $0.01;
- the same TikTok translated into Ukrainian: $0.017;
- a 10-minute YouTube video without captions: $0.10.

Each run also carries Apify's standard start fee of $0.05 per 1,000 runs. Subtitles are free. If a run reaches your
maximum charge, the remaining videos are skipped.

## Privacy

Audio is sent to [Groq](https://groq.com)'s speech-to-text API (Whisper) only when a video has no captions; transcripts
are sent to Groq's language model API only when you ask for a translation. See
[Groq's privacy policy](https://groq.com/privacy-policy/). Results stay in your own Apify run storage. Transcribe only
videos you are allowed to use.

## Related Actors

- [Audio & Video Transcriber](https://apify.com/ai_admin/audio-transcriber) — your own audio and video files to text and subtitles
- [Text to Speech](https://apify.com/ai_admin/text-to-speech) · [Video Frame Extractor](https://apify.com/ai_admin/video-frame-extractor)

## Use with AI agents and code

- **MCP (Claude, Cursor, VS Code, any MCP client):** add `https://mcp.apify.com?tools=ai_admin/social-video-transcript`
  as an MCP server — the agent gets one tool with this Actor's input schema and pays per use through your Apify account.
- **One HTTP call that returns the results:**

```bash
curl -X POST "https://api.apify.com/v2/acts/ai_admin~social-video-transcript/run-sync-get-dataset-items?token=$APIFY_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"videoUrls": ["https://www.tiktok.com/@nasa/video/7698805564884733198"], "translateTo": "es"}'
```

## Limits

- Private videos, videos that need a login and live streams are not supported.
- Instagram often blocks downloads from servers; such Reels get an `error` and are free.
- Speaker labels (diarization) are not included.
