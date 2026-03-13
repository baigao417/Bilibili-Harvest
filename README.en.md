# BilibiliHarvest

[中文文档](README.md)

A `Windows + Chrome` tool for extracting Bilibili subtitles and organizing them into a reusable knowledge workflow.  
The desktop app is reduced to a local background service, while the browser extension acts as the primary UI.

## Overview

BilibiliHarvest focuses on three things:

- extracting native subtitle tracks from Bilibili whenever possible
- falling back to Whisper ASR when subtitle tracks are unavailable
- turning the result into reusable text for a local library or NotebookLM

Current structure:

- Desktop app: local API service + system tray
- Browser extension: the only user-facing interface
- Local library: subtitle text saved under `archive_root/<title>_<BV>/text/`

## Who It Is For

- People who want to build a searchable archive from Bilibili content
- People who want to convert video knowledge into text quickly
- People who want to push cleaned subtitle text into NotebookLM
- People who prefer browser-first operation instead of a heavy desktop workflow

## Highlights

- Prefer native Bilibili subtitle tracks
- Automatically fall back to Whisper ASR
- Supports single videos, multi-part videos, favorites, collections, series, and space uploads
- One-click send from the current Chrome tab
- One-click post-processing:
  - save to the local library
  - push to NotebookLM
- No runtime `outputs/` directory is generated in the project root

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
   - choose the local library path
   - optionally sign in to NotebookLM

## Recommended Workflow

1. Keep the desktop tray service running
2. Open a Bilibili video, collection, or list page in Chrome
3. Add tasks from the dashboard
4. Start batch processing
5. When processing finishes:
   - save to the local library
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
  - save to local library
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

Local library layout:

- `<archive_root>/<safe_title>_<BV>/text/*.srt|*.txt|*.md`

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

If any project attribution should be refined, feel free to open an issue or pull request.

## FAQ

### Why is there no `outputs/` directory?

Because the project is now designed to write directly into the local library instead of producing transient export folders in the repo root.

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
