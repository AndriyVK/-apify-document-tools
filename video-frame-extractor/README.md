# Video Frame Extractor: Thumbnails, Scenes, Keyframes, Timecodes

Turn videos into still images: thumbnails for a gallery, one frame per scene for AI vision or video search, or frames at
the exact moments you need — each with its timecode and a download link.

- **Five modes:** N evenly spaced frames, one frame every N seconds, exact timestamps (`90.5`, `01:30`, `1:02:03`),
  every **scene change** (adjustable sensitivity), or the video's **keyframes**.
- **JPG, PNG or WebP**, optional downscaling (`maxWidth`).
- **Contact sheet** with all frames and timecodes in one image — free.
- **Video metadata:** duration, resolution, frame rate, codec.
- Files up to 2 GB: MP4, MOV, WebM, MKV, AVI, M4V, MPEG, 3GP and anything else ffmpeg reads.

## Why this Actor

| | This Actor | Typical alternatives in the Apify Store (Oct 2026) |
|---|---|---|
| **Price** | **$1 per 1,000 frames**, no per-video fee | $2 per 1,000 frames, often plus $2–10 per 1,000 videos |
| **Modes** | Evenly spaced, every N seconds, exact timestamps, scene changes, keyframes | Two or three modes |
| **Extras** | Free contact sheet, timecodes, video metadata, JPG/PNG/WebP, downscaling | Contact sheet as a paid add-on or missing |

## Input

```json
{
  "sources": [{ "url": "https://example.com/lecture.mp4" }],
  "mode": "scenes",
  "sceneThreshold": 0.3,
  "maxFramesPerVideo": 100,
  "format": "jpg",
  "maxWidth": 1280,
  "contactSheet": true
}
```

| Field | Meaning |
|---|---|
| `sources` | Direct links to video files. Pages like YouTube are not supported. Files in your own Apify key-value store work too: set the store's access to "Anyone with ID can read" and use `https://api.apify.com/v2/key-value-stores/<store ID>/records/<key>` (the Actor runs with limited permissions and does not use your token). |
| `mode` | `count`, `interval`, `timestamps`, `scenes` or `keyframes` |
| `frameCount` | Frames for `count` |
| `intervalSeconds` | Seconds between frames for `interval` (0.5 = two per second) |
| `timestamps` | Times for `timestamps` |
| `sceneThreshold` | 0.1 = sensitive … 0.5 = hard cuts only |
| `maxFramesPerVideo` | Upper limit for every mode |
| `format`, `maxWidth` | Image format and optional downscaling |
| `contactSheet` | One overview image per video (free) |

## Output

One item per video:

```json
{
  "url": "https://example.com/lecture.mp4",
  "fileName": "lecture.mp4",
  "mode": "scenes",
  "duration": 1843.2,
  "width": 1920,
  "height": 1080,
  "fps": 25.0,
  "codec": "h264",
  "frameCount": 42,
  "frames": [
    { "index": 1, "time": 12.48, "timecode": "00:00:12.480", "key": "0001-lecture-00001.jpg",
      "url": "https://api.apify.com/v2/key-value-stores/.../records/0001-lecture-00001.jpg", "bytes": 98211 }
  ],
  "contactSheetUrl": "https://api.apify.com/v2/key-value-stores/.../records/0001-lecture-contact-sheet.jpg"
}
```

A video that cannot be downloaded or decoded gets an `error` field instead and is **not charged**.

## Pricing

| Event | Price | What counts |
|---|---|---|
| `frame` | **$1 per 1,000** | one extracted frame |
| `scene-minute` | **$1 per 1,000** | only in `scenes` mode: one started minute of video analysed for scene changes |

Plus Apify's standard start fee of $0.05 per 1,000 runs. The contact sheet is free. The run stops before it would exceed
your maximum charge per run.

## Related Actors

- [Image to Text OCR](https://apify.com/ai_admin/image-to-text-ocr) — read the text on the extracted frames
- [Audio & Video Transcriber](https://apify.com/ai_admin/audio-transcriber) — speech to text, SRT and VTT subtitles
- [PDF to Image & Image Converter](https://apify.com/ai_admin/pdf-image-converter) — PDF ↔ PNG/JPG/WebP, HEIC → JPG

Open source: [github.com/AndriyVK/-apify-document-tools](https://github.com/AndriyVK/-apify-document-tools)

## Use with AI agents and code

- **MCP (Claude, Cursor, VS Code, any MCP client):** add `https://mcp.apify.com?tools=ai_admin/video-frame-extractor` as an MCP server —
  the agent gets one tool with this Actor's input schema and pays per use through your Apify account.
- **One HTTP call that returns the results:**

```bash
curl -X POST "https://api.apify.com/v2/acts/ai_admin~video-frame-extractor/run-sync-get-dataset-items?token=$APIFY_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"sources": [{"url": "https://api.apify.com/v2/key-value-stores/FloomuI2DrQCJazY8/records/video-en.mp4"}], "mode": "count", "frameCount": 6, "format": "jpg"}'
```

## Limits

- Direct file links only (no YouTube, TikTok or other page links). Maximum 2 GB per file.
- Scene detection compares brightness and colour between frames: slow fades may produce no frame; lower the sensitivity.
