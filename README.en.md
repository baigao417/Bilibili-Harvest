# BilibiliHarvest

[中文文档](README.md)

A `Windows + Chrome` tool for extracting Bilibili content into a reusable local knowledge workflow.  
The desktop app is reduced to a local background service, while the browser extension acts as the primary UI.

## Project Positioning

BilibiliHarvest is built around three goals:

- extract native Bilibili subtitle tracks whenever possible
- fall back to Whisper ASR when subtitle tracks are unavailable
- save the result into a local knowledge base or push it into NotebookLM

If your workflow depends on collecting, preserving, and searching valuable Bilibili content over time, this project is designed for that use case.

## Why Save to a Local Knowledge Base

High-quality information on the internet is often fragile:

- videos can be removed
- subtitles can change or disappear
- page structure and visible content can change
- collections, favorites, and lists can be deleted or reorganized

Saving important material locally is therefore safer than relying entirely on the platform, and it also makes later indexing, archiving, and reuse much easier.

## Local Knowledge Base / Shape of Me Workflow

The project supports saving processed results into your own local knowledge base. You can think of this as:

- a generic local knowledge base workflow
- or, if you prefer, your own `Shape of Me` style workflow

When saving to the local knowledge base, each task gets its own folder:

- `video/`: saves video, preferring `1080P` by default
- `audio/`: saves extracted audio
- `text/`: saves subtitle text as `srt / txt / md`

Folder layout:

- `<archive_root>/<safe_title>_<BV>/video/*`
- `<archive_root>/<safe_title>_<BV>/audio/*`
- `<archive_root>/<safe_title>_<BV>/text/*.srt|*.txt|*.md`

## Customizable Feature Name

The "save to local knowledge base" feature name is customizable.

You can rename it in the extension settings, for example:

- Local Knowledge Base
- Shape of Me
- Video Archive
- Research Library
- Personal Knowledge Vault

The custom name affects UI labels and prompts, but not the underlying processing pipeline.

## Highlights

- Prefer native Bilibili subtitle tracks
- Automatically fall back to Whisper ASR
- Supports single videos, multi-part videos, favorites, collections, series, and space uploads
- One-click send from the current Chrome tab
- One-click post-processing:
  - save to the local knowledge base
  - push to NotebookLM
- No runtime `outputs/` directory is generated in the project root

## Who It Is For

- People who want to build a long-term archive from Bilibili content
- People who want searchable text from videos quickly
- People who want to push cleaned subtitle text into NotebookLM
- People who prefer a browser-first workflow instead of a heavy desktop UI

## Quick Start

1. Install Python `3.12`
2. Run:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\setup_windows.ps1
```

3. Load `browser_extension/` as an unpacked extension in Chrome
4. Open the extension dashboard
5. Finish the setup wizard:
   - detect the desktop service
   - auto-pair
   - choose the local knowledge base path
   - optionally customize the feature name
   - optionally sign in to NotebookLM

## Recommended Workflow

1. Keep the desktop tray service running
2. Open a Bilibili video, collection, or list page in Chrome
3. Add tasks from the dashboard
4. Start batch processing
5. When processing finishes:
   - save to the local knowledge base
   - or push to NotebookLM

## Project Structure

- The desktop app starts in tray mode by default
- Tray menu actions:
  - open the extension dashboard
  - show the diagnostic window
  - quit the service
- The dashboard handles:
  - task import
  - batch control
  - save to local knowledge base
  - push to NotebookLM

## Storage

The project no longer creates a runtime `outputs/` directory.

- Runtime config:
  - `config/runtime.json`
- Batch snapshots:
  - `config/batches/<batch_id>/state.json`
- Failure diagnostics:
  - `config/batches/<batch_id>/failed.json`
- Temporary subtitle cache:
  - `config/tmp/<batch_id>/`
- Default local library:
  - `%USERPROFILE%\Documents\BilibiliHarvest Library`

## Local API

Main workflow-related endpoints:

- `GET /v1/pairing/info`
- `POST /v1/pairing/claim`
- `GET /v1/config`
- `PATCH /v1/config`
- `POST /v1/window/show`
- `GET /v1/health`
- `POST /v1/tasks/add`
- `POST /v1/tasks/add_prefetched`
- `POST /v1/tasks/bulk_add`
- `GET /v1/tasks`
- `GET /v1/batch/status`
- `POST /v1/batch/start`
- `POST /v1/batch/stop`

## Open Source Credits

This project borrows from or depends on the following open source projects:

- [`Lanbin07/bili2text`](https://github.com/Lanbin07/bili2text): the early baseline and direction of this project
- [`openai/whisper`](https://github.com/openai/whisper): ASR transcription
- [`yt-dlp/yt-dlp`](https://github.com/yt-dlp/yt-dlp): subtitle track discovery, download, and media fallback
- [`soimort/you-get`](https://github.com/soimort/you-get): downloader fallback compatibility
- [`fastapi/fastapi`](https://github.com/fastapi/fastapi): local HTTP API service
- [`PyQt5`](https://pypi.org/project/PyQt5/): desktop UI and tray support
- [`QDarkStyleSheet`](https://github.com/ColinDuquesnoy/QDarkStyleSheet): desktop styling
- [`notebooklm-py`](https://pypi.org/project/notebooklm-py/): NotebookLM integration support

## FAQ

### Why is there no `outputs/` directory?

Because the project is now designed to write directly into the local knowledge base instead of producing runtime export folders in the repo root.

### Can I use the extension without the desktop app?

No. The extension is the main UI, but actual processing still happens in the local desktop service.

### Is it cross-platform?

The officially supported setup is currently `Windows + Chrome + Python 3.12`.

## Safety

- Never commit `config/runtime.json`
- Never commit `cookies.txt`
- Never commit `config/batches/` or `config/tmp/`
- The local API token is generated randomly on first start

## Diagnostics

```powershell
py -3.12 scripts\launcher.py --doctor
```

To show the desktop diagnostic window:

```powershell
py -3.12 scripts\launcher.py --show-window
```

## License

MIT
