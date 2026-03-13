import queue
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Optional


class TaskStatus(Enum):
    QUEUED = "queued"
    RESOLVING_TRACKS = "resolving_tracks"
    DOWNLOADING_TRACK = "downloading_track"
    TRANSCRIBING_ASR = "transcribing_asr"
    COMPLETED_TRACK = "completed_track"
    COMPLETED_ASR = "completed_asr"
    FAILED = "failed"


class FailStage(Enum):
    PARSE = "parse"
    IMPORT_SOURCE = "import_source"
    TRACK_DISCOVERY = "track_discovery"
    TRACK_DOWNLOAD = "track_download"
    DOWNLOAD = "download"
    AUDIO_SPLIT = "audio_split"
    TRANSCRIBE = "transcribe"
    EXPORT = "export"


class StageFailure(Exception):
    def __init__(self, stage: FailStage, message: str, retryable: bool = False):
        super().__init__(message)
        self.stage = stage
        self.retryable = retryable


@dataclass
class TaskItem:
    seq: int
    raw_input: str
    video_link: str
    bv: str
    aid: Optional[int] = None
    cid: Optional[int] = None
    owner: str = "UnknownUP"
    source_type: str = "single"
    source_meta: dict = field(default_factory=dict)
    page: Optional[int] = None
    page_title: str = ""
    status: TaskStatus = TaskStatus.QUEUED
    title: str = "UnknownTitle"
    subtitle_state: str = "未获取"
    result_source: str = ""
    selected_lang: str = ""
    outputs: dict = field(default_factory=dict)
    output_file: Optional[str] = None
    cookie_hint: bool = False
    retry_count: int = 0
    failed_stage: Optional[FailStage] = None
    error: Optional[str] = None
    transcribe_cur: int = 0
    transcribe_total: int = 0
    segments_cache: list[dict] = field(default_factory=list)
    segments_tmp_json: str = ""
    temp_paths: list[str] = field(default_factory=list)
    video_file_path: str = ""
    audio_file_path: str = ""
    save_selected: bool = False
    shape_folder_name: str = ""
    asset_prepare_error: str = ""
    prefetched_segments: list[dict] = field(default_factory=list)
    prefetched_meta: dict = field(default_factory=dict)
    request_cookie_header: Optional[str] = None
    nlm_source_id: str = ""
    nlm_push_status: str = ""  # "" | "pushing" | "pushed" | "push_failed"


@dataclass
class BatchContext:
    batch_id: str
    started_at: datetime
    model: str
    tasks: list[TaskItem] = field(default_factory=list)
    task_queue: queue.Queue = field(default_factory=queue.Queue)
    total_count: int = 0
    running_count: int = 0
    success_count: int = 0
    failed_count: int = 0
    done_count: int = 0
    export_dir: str = ""
    success_dir: str = ""
    success_srt_dir: str = ""
    success_txt_dir: str = ""
    success_md_dir: str = ""
    tmp_subtitle_dir: str = ""
    failed_dir: str = ""
    index_path: str = ""
    failed_csv_path: str = ""
    batch_all_md_path: str = ""
    zip_path: str = ""
    state_path: str = ""
    failed_state_path: str = ""
    io_workers: int = 2
    resumed_from: str = ""
    state_version: str = ""
    core_version: str = ""
    is_running: bool = False
    current_task_seq: Optional[int] = None
    exported_once: bool = False
    temp_cleaned: bool = False
    media_cache: dict = field(default_factory=dict)
