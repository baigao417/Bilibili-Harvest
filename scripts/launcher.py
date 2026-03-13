from __future__ import annotations

import argparse
import importlib
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Optional


PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

RUNTIME_TOOLS_IMPORT_ERROR: Optional[str] = None
try:
    from runtime_tools import find_executable
except Exception as exc:  # pragma: no cover - defensive bootstrap guard.
    RUNTIME_TOOLS_IMPORT_ERROR = str(exc)

    def find_executable(_name: str) -> Optional[str]:
        return None


@dataclass
class CheckResult:
    name: str
    status: str  # PASS | WARN | FAIL
    detail: str
    fix: Optional[str] = None


@dataclass
class DoctorContext:
    project_root: str
    python_executable: str
    python_version: str
    torch_version: str = "unknown"
    torch_cuda_available: str = "unknown"


def check_python_version() -> CheckResult:
    major, minor = sys.version_info.major, sys.version_info.minor
    if (major, minor) == (3, 12):
        return CheckResult(
            name="Python 3.12",
            status="PASS",
            detail=f"Running {major}.{minor} ({sys.executable})",
        )

    return CheckResult(
        name="Python 3.12",
        status="FAIL",
        detail=f"Running {major}.{minor}, expected 3.12",
        fix="Use: py -3.12 scripts/launcher.py",
    )


def check_binaries() -> list[CheckResult]:
    if RUNTIME_TOOLS_IMPORT_ERROR:
        return [
            CheckResult(
                name="runtime_tools import",
                status="FAIL",
                detail=RUNTIME_TOOLS_IMPORT_ERROR,
                fix="Run from project root and verify runtime_tools.py is importable.",
            )
        ]

    results: list[CheckResult] = []
    for binary in ("ffmpeg", "ffprobe"):
        resolved = find_executable(binary)
        if resolved:
            results.append(CheckResult(binary, "PASS", resolved))
        else:
            results.append(
                CheckResult(
                    binary,
                    "FAIL",
                    "not found in PATH or WinGet package directories",
                    fix=f"Install {binary} and ensure it is discoverable.",
                )
            )

    yt_dlp = find_executable("yt-dlp")
    you_get = find_executable("you-get")
    if yt_dlp and you_get:
        results.append(
            CheckResult(
                "downloaders",
                "PASS",
                f"yt-dlp={yt_dlp}; you-get={you_get}",
            )
        )
    elif yt_dlp or you_get:
        available_name = "yt-dlp" if yt_dlp else "you-get"
        available_path = yt_dlp or you_get or ""
        missing_name = "you-get" if yt_dlp else "yt-dlp"
        results.append(
            CheckResult(
                "downloaders",
                "WARN",
                f"{available_name} available ({available_path}); {missing_name} missing",
                fix=f"Optional: install {missing_name} for fallback resilience.",
            )
        )
    else:
        results.append(
            CheckResult(
                "downloaders",
                "FAIL",
                "yt-dlp and you-get are both missing",
                fix="Install at least one downloader (recommended: yt-dlp and you-get).",
            )
        )

    return results


def check_imports(context: DoctorContext) -> list[CheckResult]:
    # Keep torch first to match window.py's preload order and avoid c10.dll init issues.
    modules = ("torch", "whisper", "PyQt5", "qdarkstyle")
    results: list[CheckResult] = []

    for module_name in modules:
        try:
            module = importlib.import_module(module_name)
            detail = "import ok"
            if module_name == "torch":
                torch_version = getattr(module, "__version__", "unknown")
                cuda_available = False
                try:
                    cuda_available = bool(module.cuda.is_available())
                except Exception:
                    cuda_available = False

                context.torch_version = str(torch_version)
                context.torch_cuda_available = "yes" if cuda_available else "no"
                detail = f"import ok, version={torch_version}, cuda={context.torch_cuda_available}"

            results.append(CheckResult(module_name, "PASS", detail))
        except Exception as exc:
            results.append(
                CheckResult(
                    module_name,
                    "FAIL",
                    str(exc),
                    fix="Run: py -3.12 -m pip install -r requirements.txt",
                )
            )

    return results


def check_runtime_config() -> list[CheckResult]:
    results: list[CheckResult] = []
    try:
        from runtime_config import load_runtime_config
    except Exception as exc:
        return [
            CheckResult(
                "runtime_config",
                "FAIL",
                str(exc),
                fix="Verify runtime_config.py is importable from project root.",
            )
        ]

    try:
        cfg = load_runtime_config()
    except Exception as exc:
        return [
            CheckResult(
                "runtime_config load",
                "FAIL",
                str(exc),
                fix="Delete or repair config/runtime.json then rerun launcher.",
            )
        ]

    details = (
        f"http_enabled={cfg.http_enabled}, host={cfg.http_host}, port={cfg.http_port}, "
        f"io_workers={cfg.io_workers}, extension_ids={len(cfg.extension_ids)}"
    )
    results.append(CheckResult("runtime_config", "PASS", details))

    if not cfg.api_token:
        results.append(
            CheckResult(
                "runtime api token",
                "WARN",
                "api_token missing; runtime_config will regenerate on next save",
                fix="Open GUI service settings and reset token once.",
            )
        )
    else:
        results.append(CheckResult("runtime api token", "PASS", "configured"))

    if cfg.http_enabled:
        for module_name in ("fastapi", "uvicorn"):
            try:
                importlib.import_module(module_name)
                results.append(CheckResult(f"http dep {module_name}", "PASS", "import ok"))
            except Exception as exc:
                results.append(
                    CheckResult(
                        f"http dep {module_name}",
                        "FAIL",
                        str(exc),
                        fix="Run: py -3.12 -m pip install -r requirements.txt",
                    )
                )
    return results


def run_checks() -> tuple[DoctorContext, list[CheckResult]]:
    context = DoctorContext(
        project_root=str(PROJECT_ROOT),
        python_executable=sys.executable,
        python_version=sys.version.split()[0],
    )

    results: list[CheckResult] = []
    results.append(check_python_version())
    results.extend(check_binaries())
    results.extend(check_imports(context))
    results.extend(check_runtime_config())
    return context, results


def print_report(context: DoctorContext, results: list[CheckResult], verbose: bool) -> None:
    print("== BilibiliHarvest doctor ==")
    print(f"project_root: {context.project_root}")
    print(f"python_executable: {context.python_executable}")
    print(f"python_version: {context.python_version}")
    print(f"torch_version: {context.torch_version}")
    print(f"torch_cuda_available: {context.torch_cuda_available}")
    print("")

    items = results if verbose else [item for item in results if item.status != "PASS"]
    if not items:
        print("[PASS] all startup checks passed")
    else:
        for item in items:
            print(f"[{item.status}] {item.name}: {item.detail}")
            if item.fix:
                print(f"  fix: {item.fix}")

    failed = sum(1 for item in results if item.status == "FAIL")
    warned = sum(1 for item in results if item.status == "WARN")
    passed = sum(1 for item in results if item.status == "PASS")
    print("")
    print(f"summary: pass={passed}, warn={warned}, fail={failed}")


def has_blocking_failures(results: list[CheckResult]) -> bool:
    return any(item.status == "FAIL" for item in results)


def launch_window(show_window: bool = False, force_http_enabled: bool = True) -> int:
    try:
        import window
    except Exception as exc:
        print(f"[FAIL] import window: {exc}")
        print("fix: run: py -3.12 scripts/launcher.py --doctor")
        return 1

    try:
        window.main(show_window=show_window, force_http_enabled=force_http_enabled)
    except KeyboardInterrupt:
        return 130
    except Exception as exc:
        print(f"[FAIL] window.main() crashed: {exc}")
        print("fix: run: py -3.12 scripts/launcher.py --doctor")
        return 1

    return 0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="BilibiliHarvest launcher with environment checks")
    parser.add_argument("--doctor", action="store_true", help="Run checks only and print diagnostics")
    parser.add_argument(
        "--background",
        action="store_true",
        help="Compatibility flag. Background tray mode is now the default.",
    )
    parser.add_argument(
        "--show-window",
        action="store_true",
        help="Show the diagnostic desktop window instead of tray-only mode.",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Show PASS entries as well. Default behavior shows WARN/FAIL entries.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    context, results = run_checks()
    verbose = args.doctor or args.verbose
    print_report(context, results, verbose=verbose)

    if has_blocking_failures(results):
        print("startup aborted: blocking checks failed")
        return 1

    if args.doctor:
        print("doctor completed: no blocking issues")
        return 0

    show_window = bool(args.show_window and not args.background)
    return launch_window(show_window=show_window, force_http_enabled=True)


if __name__ == "__main__":
    raise SystemExit(main())
