#!/usr/bin/env python3
"""Watch for League of Legends and start lol_kill_sound.py once.

Polls for LeagueClient.exe / League of Legends.exe. When found, launches the
kill-sound watcher in a new console if it is not already running. Leaves the
watcher running after League exits; restarts it later if League returns and
the watcher is gone. Stdlib only.
"""

from __future__ import annotations

import base64
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

LEAGUE_NAMES = ("LeagueClient.exe", "League of Legends.exe")
WATCHER_SCRIPT = "lol_kill_sound.py"
POLL_S = 5.0

CREATE_NEW_CONSOLE = getattr(subprocess, "CREATE_NEW_CONSOLE", 0x00000010)
CREATE_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000)


def project_root() -> Path:
    return Path(__file__).resolve().parent


def find_python() -> str | None:
    """Match run.bat: py -3 → python → LocalAppData\\Programs\\Python\\Python3*."""
    candidates: list[str] = []

    py_launcher = shutil.which("py")
    if py_launcher:
        try:
            probe = subprocess.run(
                [py_launcher, "-3", "-c", "import sys; print(sys.executable)"],
                check=True,
                capture_output=True,
                text=True,
                timeout=15,
                creationflags=CREATE_NO_WINDOW,
            )
            exe = probe.stdout.strip()
            if exe and Path(exe).is_file():
                return exe
        except (OSError, subprocess.SubprocessError):
            pass

    for name in ("python", "python3"):
        found = shutil.which(name)
        if found:
            candidates.append(found)

    local = Path(os.environ.get("LocalAppData", "")) / "Programs" / "Python"
    if local.is_dir():
        for child in sorted(local.glob("Python3*"), reverse=True):
            exe = child / "python.exe"
            if exe.is_file():
                candidates.append(str(exe))

    # Prefer an interpreter that can import from this folder's script path.
    for exe in candidates:
        try:
            probe = subprocess.run(
                [exe, "-c", "import sys; print(sys.executable)"],
                check=True,
                capture_output=True,
                text=True,
                timeout=15,
                creationflags=CREATE_NO_WINDOW,
            )
            if probe.stdout.strip():
                return exe
        except (OSError, subprocess.SubprocessError):
            continue

    # Last resort: same interpreter running this helper.
    if Path(sys.executable).is_file() and not sys.executable.lower().endswith(
        "pythonw.exe"
    ):
        return sys.executable
    return None


def tasklist_image_names() -> set[str]:
    try:
        out = subprocess.check_output(
            ["tasklist", "/FO", "CSV", "/NH"],
            text=True,
            errors="replace",
            timeout=30,
            creationflags=CREATE_NO_WINDOW,
        )
    except (OSError, subprocess.SubprocessError):
        return set()

    names: set[str] = set()
    for line in out.splitlines():
        line = line.strip()
        if not line.startswith('"'):
            continue
        name = line.split('","', 1)[0].strip('"')
        if name:
            names.add(name.lower())
    return names


def league_running() -> bool:
    names = tasklist_image_names()
    return any(n.lower() in names for n in LEAGUE_NAMES)


def watcher_running() -> bool:
    """True if a python/py process is running lol_kill_sound.py."""
    # Write YES/NO to a temp file so CLIXML progress noise cannot hide the result.
    flag = Path(os.environ.get("TEMP", str(project_root()))) / "lol_kill_sound_watcher_running.txt"
    ps = (
        "$ProgressPreference = 'SilentlyContinue'; "
        "$ErrorActionPreference = 'SilentlyContinue'; "
        f"$flag = '{flag.as_posix()}'; "
        "$hit = Get-CimInstance Win32_Process | Where-Object { "
        "$_.CommandLine -and "
        "($_.Name -like 'python*.exe' -or $_.Name -eq 'py.exe') -and "
        "($_.CommandLine -like '*lol_kill_sound.py*') -and "
        "($_.CommandLine -notlike '*lol_autostart.py*') "
        "}; $val = if ($hit) { 'YES' } else { 'NO' }; "
        "Set-Content -LiteralPath $flag -Value $val -Encoding Ascii"
    )
    encoded = base64.b64encode(ps.encode("utf-16le")).decode("ascii")
    try:
        subprocess.run(
            [
                "powershell",
                "-NoProfile",
                "-NonInteractive",
                "-ExecutionPolicy",
                "Bypass",
                "-EncodedCommand",
                encoded,
            ],
            check=False,
            capture_output=True,
            timeout=45,
            creationflags=CREATE_NO_WINDOW,
        )
        if not flag.is_file():
            return False
        return flag.read_text(encoding="ascii", errors="ignore").strip().upper() == "YES"
    except (OSError, subprocess.SubprocessError):
        return False
    finally:
        try:
            flag.unlink(missing_ok=True)
        except OSError:
            pass


def start_watcher(python_exe: str) -> subprocess.Popen[str] | subprocess.Popen[bytes]:
    script = project_root() / WATCHER_SCRIPT
    if not script.is_file():
        raise FileNotFoundError(f"Missing watcher script: {script}")
    print(f"[autostart] Starting watcher: {python_exe} {script.name}", flush=True)
    return subprocess.Popen(
        [python_exe, str(script)],
        cwd=str(project_root()),
        creationflags=CREATE_NEW_CONSOLE,
    )


def main() -> int:
    if sys.platform != "win32":
        print("This helper is for Windows only.", flush=True)
        return 1

    watcher_path = project_root() / WATCHER_SCRIPT
    if not watcher_path.is_file():
        print(f"Missing {WATCHER_SCRIPT} next to this script.", flush=True)
        return 1

    python_exe = find_python()
    if not python_exe:
        print("Python が見つかりません。python.org から Python 3.10+ を入れてください。", flush=True)
        print('インストール時に "Add python.exe to PATH" にチェックを入れてください。', flush=True)
        return 1

    print("LoL 自動起動ヘルパー", flush=True)
    print(f"  Python : {python_exe}", flush=True)
    print(f"  Watcher: {watcher_path}", flush=True)
    print(
        f"  Watching for: {', '.join(LEAGUE_NAMES)} (poll {POLL_S:.0f}s)",
        flush=True,
    )
    print("  League 終了後もキル音ウォッチャーは動かしたままにします。", flush=True)
    print("  終了: Ctrl+C", flush=True)
    print("", flush=True)

    spawned: subprocess.Popen[str] | subprocess.Popen[bytes] | None = None
    last_league = False

    try:
        while True:
            in_league = league_running()
            if in_league and not last_league:
                print("[autostart] League detected.", flush=True)
            elif not in_league and last_league:
                print(
                    "[autostart] League exited (watcher left running if still open).",
                    flush=True,
                )
            last_league = in_league

            if in_league:
                alive_spawned = spawned is not None and spawned.poll() is None
                if not alive_spawned and not watcher_running():
                    try:
                        spawned = start_watcher(python_exe)
                        print(
                            f"[autostart] Watcher console started (pid {spawned.pid}).",
                            flush=True,
                        )
                    except OSError as exc:
                        print(f"[autostart] Failed to start watcher: {exc}", flush=True)
                        spawned = None
                elif alive_spawned or watcher_running():
                    # Already up — do not spawn a duplicate.
                    pass

            time.sleep(POLL_S)
    except KeyboardInterrupt:
        print("\n[autostart] Stopped. (Watcher window is left open if still running.)", flush=True)
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
