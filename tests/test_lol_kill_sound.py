from __future__ import annotations

import sys

import pytest

import lol_kill_sound as m


@pytest.fixture
def root(tmp_path, monkeypatch):
    monkeypatch.setattr(m, "project_root", lambda: tmp_path)
    (tmp_path / "sounds").mkdir()
    return tmp_path


def fake_api(monkeypatch, responses):
    """Answer http_get_json from a dict keyed by (path, query); anything else fails."""
    calls = []

    def http_get_json(path, query=None, timeout=1.5):
        key = (path, tuple(sorted((query or {}).items())))
        calls.append(key)
        if key not in responses:
            raise OSError(f"no response for {key}")
        return responses[key]

    monkeypatch.setattr(m, "http_get_json", http_get_json)
    return calls


# --- 3.2 判定 ---


def test_first_count_is_baseline():
    tracker = m.KillTracker()
    assert tracker.update(3) == 0
    assert tracker.kills == 3


def test_plays_once_per_new_kill():
    tracker = m.KillTracker()
    tracker.update(0)
    assert tracker.update(1) == 1
    assert tracker.update(1) == 0
    assert tracker.update(3) == 2


def test_drop_rebaselines_without_sound():
    tracker = m.KillTracker()
    tracker.update(5)
    assert tracker.update(0) == 0
    assert tracker.update(1) == 1


def test_reset_starts_a_new_game():
    tracker = m.KillTracker()
    tracker.update(0)
    tracker.update(4)
    tracker.reset()
    assert tracker.update(2) == 0
    assert tracker.update(3) == 1


# --- 3.1 使うデータ ---


def test_riot_id_from_activeplayer(monkeypatch):
    fake_api(monkeypatch, {("activeplayer", ()): {"riotId": "Me#JP1"}})
    assert m.active_player_riot_id() == "Me#JP1"


def test_riot_id_falls_back_to_activeplayername(monkeypatch):
    fake_api(monkeypatch, {("activeplayername", ()): '"Me#JP1"'})
    assert m.active_player_riot_id() == "Me#JP1"


def test_riot_id_none_when_unreadable(monkeypatch):
    fake_api(monkeypatch, {})
    assert m.active_player_riot_id() is None


def test_kills_from_playerscores(monkeypatch):
    fake_api(monkeypatch, {("playerscores", (("riotId", "Me#JP1"),)): {"kills": 4}})
    assert m.fetch_kills("Me#JP1") == 4


def test_kills_retry_with_summoner_name(monkeypatch):
    fake_api(monkeypatch, {("playerscores", (("summonerName", "Me#JP1"),)): {"kills": 2}})
    assert m.fetch_kills("Me#JP1") == 2


def test_kills_fall_back_to_playerlist(monkeypatch):
    players = [
        {"riotId": "Other#JP1", "scores": {"kills": 9}},
        {"riotId": "Me#JP1", "scores": {"kills": 1}},
    ]
    fake_api(monkeypatch, {("playerlist", ()): players})
    assert m.fetch_kills("Me#JP1") == 1


def test_kills_none_when_player_missing(monkeypatch):
    fake_api(monkeypatch, {("playerlist", ()): [{"riotId": "Other#JP1", "scores": {"kills": 9}}]})
    assert m.fetch_kills("Me#JP1") is None


# --- 4.1 音ファイルの選び方 ---


def test_wav_is_preferred_over_mp3(root):
    (root / "sounds" / "kill-confirm.wav").write_bytes(b"")
    (root / "sounds" / "kill-confirm.mp3").write_bytes(b"")
    assert m.resolve_sound_path(None) == root / "sounds" / "kill-confirm.wav"


def test_mp3_is_used_when_no_wav(root):
    (root / "sounds" / "kill-confirm.mp3").write_bytes(b"")
    assert m.resolve_sound_path(None) == root / "sounds" / "kill-confirm.mp3"


def test_config_path_is_relative_to_project(root):
    (root / "sounds" / "kill-confirm.mp3").write_bytes(b"")
    (root / "sounds" / "mine.mp3").write_bytes(b"")
    assert m.resolve_sound_path(m.Path("sounds/mine.mp3")) == root / "sounds" / "mine.mp3"


def test_missing_config_path_falls_back(root):
    (root / "sounds" / "kill-confirm.mp3").write_bytes(b"")
    assert m.resolve_sound_path(m.Path("sounds/gone.mp3")) == root / "sounds" / "kill-confirm.mp3"


def test_no_sound_file_explains_where_to_put_it(root):
    with pytest.raises(FileNotFoundError, match="kill-confirm.mp3"):
        m.resolve_sound_path(None)


# --- 4.2 鳴らし方 ---


@pytest.fixture
def silent_player(root, monkeypatch):
    def make(debounce_s=0.15):
        player = m.SoundPlayer(root / "sounds" / "kill-confirm.wav", debounce_s)
        player._backend = "print"
        return player

    monkeypatch.setattr(m.time, "sleep", lambda _s: None)
    return make


def test_plays_at_most_five_times(silent_player, monkeypatch):
    player = silent_player()
    played = []
    monkeypatch.setattr(player, "_play_once", lambda: played.append(1))
    player.play(8)
    assert len(played) == 5


def test_debounce_skips_plays_too_close_together(silent_player, monkeypatch, capsys):
    player = silent_player(debounce_s=0.15)
    clock = iter([10.0, 10.05, 10.3])
    monkeypatch.setattr(m.time, "monotonic", lambda: next(clock))
    player._play_once()
    player._play_once()
    player._play_once()
    assert capsys.readouterr().out.count("would play") == 2


# --- 5.2 コマンド ---


def run_main(monkeypatch, *args):
    monkeypatch.setattr(sys, "argv", ["lol_kill_sound.py", *args])
    return m.main()


def test_exit_1_without_sound_file(root, monkeypatch):
    assert run_main(monkeypatch, "--config", str(root / "none.json")) == 1


def test_exit_1_when_sound_option_missing(root, monkeypatch):
    (root / "sounds" / "kill-confirm.mp3").write_bytes(b"")
    assert run_main(monkeypatch, "--sound", "sounds/gone.mp3") == 1


def test_once_check_exit_2_outside_game(root, monkeypatch):
    (root / "sounds" / "kill-confirm.wav").write_bytes(b"")
    monkeypatch.setattr(m, "game_reachable", lambda: False)
    assert run_main(monkeypatch, "--config", str(root / "none.json"), "--once-check") == 2


def test_once_check_reads_riot_id_and_kills(root, monkeypatch, capsys):
    (root / "sounds" / "kill-confirm.wav").write_bytes(b"")
    monkeypatch.setattr(m, "game_reachable", lambda: True)
    fake_api(
        monkeypatch,
        {
            ("activeplayer", ()): {"riotId": "Me#JP1"},
            ("playerscores", (("riotId", "Me#JP1"),)): {"kills": 7},
        },
    )
    assert run_main(monkeypatch, "--config", str(root / "none.json"), "--once-check") == 0
    out = capsys.readouterr().out
    assert "'Me#JP1'" in out
    assert "Kills: 7" in out
