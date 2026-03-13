# BilibiliHarvest

[中文 README](README.md)

A `Windows + Chrome` workflow tool for extracting Bilibili subtitles.

- Desktop app: local API service + system tray
- Browser extension: the primary UI
- Local library: subtitles are saved under `archive_root/<title>_<BV>/text/`

## Quick Start

1. Install Python `3.12`
2. Run:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\setup_windows.ps1
```

3. Load `browser_extension/` as an unpacked extension in Chrome
4. Open the extension dashboard
5. Finish the first-run wizard:
   - detect the desktop service
   - auto-pair
   - choose the local library path
   - optionally sign in to NotebookLM

## Architecture

- The desktop app starts in tray mode by default
- The tray menu can:
  - open the extension dashboard
  - show the diagnostic window
  - quit the service
- The extension dashboard handles:
  - task import
  - batch control
  - saving to the local library
  - pushing to NotebookLM

## Storage

The project no longer creates an `outputs/` directory.

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

## Main Features

- Prefer native Bilibili subtitle tracks
- Fall back to Whisper ASR when no subtitle track is available
- Supports single videos, multi-part videos, favorites, collections, series, and space uploads
- One-click send from the current Chrome tab
- One-click post-processing workflow:
  - save to the local library
  - push to NotebookLM

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

- [`Lanbin07/bili2text`](https://github.com/Lanbin07/bili2text): the original project direction and early baseline
- [`openai/whisper`](https://github.com/openai/whisper): ASR transcription
- [`yt-dlp/yt-dlp`](https://github.com/yt-dlp/yt-dlp): subtitle track discovery, download, and media fallback
- [`soimort/you-get`](https://github.com/soimort/you-get): downloader fallback compatibility
- [`fastapi/fastapi`](https://github.com/fastapi/fastapi): local HTTP API service
- [`PyQt5`](https://pypi.org/project/PyQt5/): desktop UI and tray support
- [`QDarkStyleSheet`](https://github.com/ColinDuquesnoy/QDarkStyleSheet): desktop styling
- [`notebooklm-py`](https://pypi.org/project/notebooklm-py/): NotebookLM integration support

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

## Export a Clean Public Snapshot

To avoid carrying over private git history, export a clean snapshot first:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\export_public_repo.ps1
```

## License

MIT
