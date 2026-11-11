#!/usr/bin/env python3
"""
League of Legends kill confirm sound.

Detects local-player kills via Riot Live Client Data API only
(https://127.0.0.1:2999/liveclientdata/...). No memory reading, injection,
or game mods.

Put your own sound at sounds/kill-confirm.wav or sounds/kill-confirm.mp3.
No sound file is shipped.
"""

from __future__ import annotations

import argparse
import json
import ssl
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

BASE_URL = "https://127.0.0.1:2999/liveclientdata"
DEFAULT_POLL_S = 0.35
DEFAULT_DEBOUNCE_S = 0.15
SOUND_WAV_REL = Path("sounds") / "kill-confirm.wav"
SOUND_MP3_REL = Path("sounds") / "kill-confirm.mp3"
# Back-compat alias for messages / older docs
SOUND_REL = SOUND_WAV_REL

# Live Client uses a self-signed cert; common local pattern is allow-insecure.
SSL_CTX = ssl._create_unverified_context()

def project_root() -> Path:
    return Path(__file__).resolve().parent


def is_mp3(path: Path) -> bool:
    return path.suffix.lower() == ".mp3"


# Persistent PowerShell MediaPlayer (Media Foundation) — works for MP3 on modern
# Windows where legacy winmm MCI MPEG drivers are often missing.
_PS_PLAYER_SCRIPT = r"""
$ErrorActionPreference = 'Continue'
Add-Type -AssemblyName PresentationCore
Add-Type -AssemblyName WindowsBase
$player = New-Object System.Windows.Media.MediaPlayer
while ($true) {
  $line = [Console]::In.ReadLine()
  if ($null -eq $line) { break }
  $path = ([string]$line).Trim()
  if (-not $path) { continue }
  if ($path -eq 'QUIT') { break }
  try {
    $player.Stop()
    $uri = [Uri]::new((Resolve-Path -LiteralPath $path).Path)
    $player.Open($uri)
    $sw = [Diagnostics.Stopwatch]::StartNew()
    while (-not $player.NaturalDuration.HasTimeSpan -and $sw.ElapsedMilliseconds -lt 4000) {
      Start-Sleep -Milliseconds 20
    }
    if (-not $player.NaturalDuration.HasTimeSpan) {
      [Console]::Error.WriteLine("OPEN_FAIL")
      [Console]::Error.Flush()
      [Console]::Out.WriteLine("FAIL")
      [Console]::Out.Flush()
      continue
    }
    $player.Volume = 1.0
    $player.Play()
    [Console]::Out.WriteLine("OK")
    [Console]::Out.Flush()
  } catch {
    [Console]::Error.WriteLine("ERR")
    [Console]::Error.Flush()
    [Console]::Out.WriteLine("FAIL")
    [Console]::Out.Flush()
  }
}
"""


class Mp3PlayerHost:
    """One long-lived powershell STA process; send absolute paths on stdin."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._proc: subprocess.Popen[str] | None = None

    def _ensure(self) -> subprocess.Popen[str]:
        if self._proc is not None and self._proc.poll() is None:
            return self._proc
        creationflags = 0
        if sys.platform == "win32":
            creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000)
        self._proc = subprocess.Popen(
            [
                "powershell",
                "-NoProfile",
                "-STA",
                "-ExecutionPolicy",
                "Bypass",
                "-Command",
                _PS_PLAYER_SCRIPT,
            ],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
            creationflags=creationflags,
        )
        return self._proc

    def play(self, path: Path) -> None:
        abs_path = str(path.resolve())
        with self._lock:
            proc = self._ensure()
            assert proc.stdin is not None and proc.stdout is not None
            try:
                proc.stdin.write(abs_path + "\n")
                proc.stdin.flush()
            except BrokenPipeError as e:
                self._proc = None
                raise RuntimeError(f"MP3 player process died before play: {path}") from e
            # Non-blocking-ish: wait briefly for ACK so obvious failures surface
            # without stalling the kill poll loop for the full clip length.
            deadline = time.monotonic() + 2.5
            ack = ""
            while time.monotonic() < deadline:
                if proc.poll() is not None:
                    err = ""
                    if proc.stderr is not None:
                        err = proc.stderr.read() or ""
                    self._proc = None
                    raise RuntimeError(f"MP3 player exited early: {err.strip() or proc.returncode}")
                # Peek via short readline with timeout using a worker
                line_holder: list[str] = []

                def _read() -> None:
                    assert proc.stdout is not None
                    line_holder.append(proc.stdout.readline())

                t = threading.Thread(target=_read, daemon=True)
                t.start()
                t.join(timeout=max(0.05, deadline - time.monotonic()))
                if t.is_alive():
                    continue
                ack = (line_holder[0] if line_holder else "").strip()
                break
            if ack != "OK":
                err = ""
                # Best-effort stderr without blocking forever
                if proc.stderr is not None:
                    err_holder: list[str] = []

                    def _err() -> None:
                        assert proc.stderr is not None
                        err_holder.append(proc.stderr.readline())

                    et = threading.Thread(target=_err, daemon=True)
                    et.start()
                    et.join(timeout=0.2)
                    err = (err_holder[0] if err_holder else "").strip()
                raise RuntimeError(f"MP3 play failed for {path}: {err or ack or 'no ack'}")

    def close(self) -> None:
        with self._lock:
            if self._proc is None:
                return
            try:
                if self._proc.stdin and self._proc.poll() is None:
                    self._proc.stdin.write("QUIT\n")
                    self._proc.stdin.flush()
                    self._proc.wait(timeout=1.5)
            except Exception:
                try:
                    self._proc.kill()
                except Exception:
                    pass
            self._proc = None


_MP3_HOST: Mp3PlayerHost | None = None


def play_via_mediaplayer(path: Path) -> None:
    global _MP3_HOST
    if _MP3_HOST is None:
        _MP3_HOST = Mp3PlayerHost()
    _MP3_HOST.play(path)


def resolve_sound_path(explicit: Path | None) -> Path:
    """Pick the kill-confirm file.

    Priority (first existing wins):
      1. config / explicit sound_path (if given and present)
      2. sounds/kill-confirm.wav
      3. sounds/kill-confirm.mp3
    """
    root = project_root()
    preferred_wav = root / SOUND_WAV_REL
    preferred_mp3 = root / SOUND_MP3_REL

    candidates: list[Path] = []
    if explicit is not None:
        candidates.append(explicit if explicit.is_absolute() else root / explicit)
    candidates.append(preferred_wav)
    candidates.append(preferred_mp3)

    seen: set[Path] = set()
    for p in candidates:
        rp = p.resolve() if p.exists() else p
        if rp in seen:
            continue
        seen.add(rp)
        if p.is_file():
            return p

    raise FileNotFoundError(
        f"No sound file. Put a WAV or MP3 at {preferred_wav} / {preferred_mp3}."
    )


def http_get_json(path: str, query: dict[str, str] | None = None, timeout: float = 1.5):
    url = f"{BASE_URL}/{path.lstrip('/')}"
    if query:
        url = f"{url}?{urllib.parse.urlencode(query)}"
    req = urllib.request.Request(url, headers={"Accept": "application/json"})
    with urllib.request.urlopen(req, context=SSL_CTX, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def game_reachable() -> bool:
    try:
        http_get_json("gamestats")
        return True
    except Exception:
        return False


def active_player_riot_id() -> str | None:
    """Return Riot ID (GameName#Tag) or summoner name for score lookups."""
    # Prefer activeplayer for riotId; fall back to activeplayername.
    try:
        data = http_get_json("activeplayer")
        if isinstance(data, dict):
            riot_id = data.get("riotId") or data.get("summonerName")
            if riot_id:
                return str(riot_id)
    except Exception:
        pass
    try:
        name = http_get_json("activeplayername")
        if isinstance(name, str) and name.strip():
            return name.strip().strip('"')
        if isinstance(name, dict):
            # Some builds wrap the string oddly; ignore.
            pass
    except Exception:
        pass
    return None


def fetch_kills(riot_id: str) -> int | None:
    """Read local player kill count from playerscores."""
    # API accepts riotId (current) and historically summonerName.
    for key in ("riotId", "summonerName"):
        try:
            scores = http_get_json("playerscores", {key: riot_id})
            if isinstance(scores, dict) and "kills" in scores:
                return int(scores["kills"])
        except Exception:
            continue
    # Fallback: playerlist + match by riotId / summonerName
    try:
        players = http_get_json("playerlist")
        if isinstance(players, list):
            for p in players:
                if not isinstance(p, dict):
                    continue
                ids = {
                    str(p.get("riotId") or ""),
                    str(p.get("summonerName") or ""),
                    str(p.get("riotIdGameName") or ""),
                }
                if riot_id in ids:
                    scores = p.get("scores") or {}
                    if "kills" in scores:
                        return int(scores["kills"])
    except Exception:
        pass
    return None


def fetch_event_ids() -> set[int]:
    """Optional: known EventIDs (for multi-kill logging / future hooks)."""
    try:
        data = http_get_json("eventdata")
        events = data.get("Events") if isinstance(data, dict) else None
        if not isinstance(events, list):
            return set()
        out: set[int] = set()
        for ev in events:
            if isinstance(ev, dict) and "EventID" in ev:
                out.add(int(ev["EventID"]))
        return out
    except Exception:
        return set()


class KillTracker:
    """Turn the kill count read on each poll into how many sounds to play."""

    def __init__(self) -> None:
        self.kills: int | None = None

    def reset(self) -> None:
        self.kills = None

    def update(self, kills: int) -> int:
        # The first count of a game is the baseline; a drop (remake) re-baselines silently.
        previous = self.kills
        self.kills = kills
        if previous is None or kills <= previous:
            return 0
        return kills - previous


class SoundPlayer:
    def __init__(self, path: Path, debounce_s: float):
        self.path = path
        self.debounce_s = debounce_s
        self._lock = threading.Lock()
        self._last_play = 0.0
        self._backend = self._pick_backend()

    def _pick_backend(self) -> str:
        if is_mp3(self.path):
            if sys.platform == "win32":
                return "mediaplayer"
            try:
                import pygame  # type: ignore  # noqa: F401

                return "pygame"
            except ImportError:
                return "print"

        if sys.platform == "win32":
            try:
                import winsound  # noqa: F401

                return "winsound"
            except ImportError:
                pass
        # Optional deps for non-Windows / testing
        try:
            import pygame  # type: ignore  # noqa: F401

            return "pygame"
        except ImportError:
            pass
        return "print"

    def play(self, times: int = 1) -> None:
        times = max(1, min(times, 5))
        for i in range(times):
            self._play_once()
            if i + 1 < times:
                time.sleep(max(self.debounce_s, 0.08))

    def _play_once(self) -> None:
        with self._lock:
            now = time.monotonic()
            if now - self._last_play < self.debounce_s:
                return
            self._last_play = now

        path = str(self.path)
        if self._backend == "winsound":
            import winsound

            # ASYNC so polling is not blocked by sound length
            winsound.PlaySound(path, winsound.SND_FILENAME | winsound.SND_ASYNC)
        elif self._backend == "mediaplayer":
            play_via_mediaplayer(self.path)
        elif self._backend == "pygame":
            import pygame

            if not pygame.mixer.get_init():
                pygame.mixer.init()
            pygame.mixer.music.load(path)
            pygame.mixer.music.play()
        else:
            print(f"[sound] would play: {path} (no audio backend; install pygame or run on Windows)")


def load_config(path: Path | None) -> dict:
    cfg_path = path or (project_root() / "config.json")
    if not cfg_path.is_file():
        return {}
    with cfg_path.open(encoding="utf-8") as f:
        data = json.load(f)
    return data if isinstance(data, dict) else {}


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Play a kill-confirm sound when you get a kill in League of Legends "
        "(Live Client Data API only)."
    )
    p.add_argument(
        "--sound",
        type=Path,
        default=None,
        help="Path to WAV/MP3 (default: sounds/kill-confirm.wav then .mp3)",
    )
    p.add_argument("--poll", type=float, default=None, help=f"Poll interval seconds (default {DEFAULT_POLL_S})")
    p.add_argument("--debounce", type=float, default=None, help=f"Min seconds between plays (default {DEFAULT_DEBOUNCE_S})")
    p.add_argument("--config", type=Path, default=None, help="Optional config.json path")
    p.add_argument("--once-check", action="store_true", help="Check API once and exit (for troubleshooting)")
    p.add_argument("--test-sound", action="store_true", help="Play the sound once and exit")
    return p.parse_args()


def main() -> int:
    args = parse_args()
    cfg = load_config(args.config)

    poll_s = float(args.poll if args.poll is not None else cfg.get("poll_interval_s", DEFAULT_POLL_S))
    debounce_s = float(
        args.debounce if args.debounce is not None else cfg.get("debounce_s", DEFAULT_DEBOUNCE_S)
    )
    sound_cfg = cfg.get("sound_path")
    try:
        if args.sound is not None:
            # Explicit CLI path must exist (no silent fallback).
            cli_path = args.sound if args.sound.is_absolute() else project_root() / args.sound
            if not cli_path.is_file():
                raise FileNotFoundError(f"Sound file not found: {cli_path}")
            sound_path = cli_path
        else:
            # config sound_path → kill-confirm.wav → kill-confirm.mp3
            preferred = Path(str(sound_cfg)) if sound_cfg else None
            sound_path = resolve_sound_path(preferred)
    except FileNotFoundError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 1

    player = SoundPlayer(sound_path, debounce_s)
    print(f"Sound: {sound_path} (backend={player._backend})")

    if args.test_sound:
        print("Playing test sound…")
        player.play(1)
        # Give async WAV / MCI a moment to start (and short clips to finish a bit)
        time.sleep(1.2)
        return 0

    if args.once_check:
        ok = game_reachable()
        print(f"Live Client reachable: {ok}")
        if not ok:
            print("Start a LoL match (or Practice Tool) and retry.")
            return 2
        rid = active_player_riot_id()
        print(f"Active player: {rid!r}")
        if rid:
            kills = fetch_kills(rid)
            print(f"Kills: {kills}")
        return 0

    print("Waiting for a live League game on https://127.0.0.1:2999 …")
    print("Ctrl+C to quit. No game mods — Live Client Data API only.")

    tracker = KillTracker()
    in_game = False
    riot_id: str | None = None
    seen_events: set[int] = set()

    try:
        while True:
            if not game_reachable():
                if in_game:
                    print("Game ended / API gone. Waiting for next match…")
                in_game = False
                tracker.reset()
                riot_id = None
                seen_events.clear()
                time.sleep(max(poll_s, 1.0))
                continue

            if not in_game:
                riot_id = active_player_riot_id()
                if not riot_id:
                    time.sleep(poll_s)
                    continue
                kills = fetch_kills(riot_id)
                if kills is None:
                    time.sleep(poll_s)
                    continue
                in_game = True
                tracker.update(kills)
                seen_events = fetch_event_ids()
                print(f"In game as {riot_id!r}. Baseline kills={kills}. Watching…")
                time.sleep(poll_s)
                continue

            # Refresh identity rarely if needed
            if riot_id is None:
                riot_id = active_player_riot_id()
                if riot_id is None:
                    time.sleep(poll_s)
                    continue

            kills = fetch_kills(riot_id)
            if kills is None:
                time.sleep(poll_s)
                continue

            previous = tracker.kills
            delta = tracker.update(kills)
            if delta:
                print(f"Kill +{delta} (total {kills})")
                player.play(delta)

                # Optional multi-kill notice from event feed (does not double-play)
                events = None
                try:
                    events = http_get_json("eventdata")
                except Exception:
                    events = None
                if isinstance(events, dict):
                    for ev in events.get("Events") or []:
                        if not isinstance(ev, dict):
                            continue
                        eid = ev.get("EventID")
                        if eid is None or int(eid) in seen_events:
                            continue
                        seen_events.add(int(eid))
                        if ev.get("EventName") == "Multikill" and str(ev.get("KillerName") or "") in {
                            riot_id,
                            riot_id.split("#")[0],
                        }:
                            streak = ev.get("KillStreak")
                            print(f"  (multi-kill streak={streak})")

            elif previous is not None and kills < previous:
                # New game / remake edge case
                print(f"Kill count reset {previous} → {kills}; re-baselining.")

            time.sleep(poll_s)
    except KeyboardInterrupt:
        print("\nStopped.")
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
