"""Foreign federation.gpu=yield stops moshi through the local supervisor.

The watcher does not dial Engine/Yield and does not call kill_moshi.
A queued activity is not a handover. Hermes does not yield its own activity.
Moshi comes back only when it was serving and the interactive session is
still running.
"""

from __future__ import annotations

import time

from hsengine.engine import coordination


def _act(**overrides) -> dict:
    now = time.time_ns()
    activity = {
        "activity_id": "d1",
        "peer": "gaius",
        "kind": "decisions",
        "state": "running",
        "postures": {coordination.POSTURE_FEDERATION_GPU: coordination.POSTURE_YIELD},
        "declared_ns": now,
        "horizon_ns": now + 3_600 * 1_000_000_000,
    }
    activity.update(overrides)
    return activity


def _session() -> dict:
    return _act(
        activity_id="s1",
        peer="hermes",
        kind=coordination.KIND_INTERACTIVE,
        postures={},
    )


def _join(watcher: coordination.ActivityWatcher) -> None:
    thread = watcher._handover_thread
    assert thread is not None
    thread.join(2)
    assert not thread.is_alive()


def test_gpu_handover_active_is_a_foreign_running_yield() -> None:
    assert coordination.gpu_handover_active([_act()], "hermes") is True
    assert coordination.gpu_handover_active([_act(peer="hermes")], "hermes") is False
    assert coordination.gpu_handover_active([_act(state="queued")], "hermes") is False
    assert coordination.gpu_handover_active([_act(state="released")], "hermes") is False
    hold = _act(postures={"gaius.endpoint.thinking": "hold-uptime"})
    assert coordination.gpu_handover_active([hold], "hermes") is False


def test_watcher_stops_moshi_and_restores_while_the_session_runs(monkeypatch) -> None:
    posts: list[tuple[str, float]] = []
    monkeypatch.setattr(
        coordination, "_post_supervisor", lambda path, timeout: posts.append((path, timeout))
    )
    monkeypatch.setattr("hsengine.engine.yk_sentinel.moshi_serving", lambda *a, **k: True)
    watcher = coordination.ActivityWatcher(addr="127.0.0.1:1", peer="hermes")
    watcher.connected = True
    session = _session()
    watcher.apply([_act(), session], 1)
    watcher._sync_gpu_handover()
    _join(watcher)
    assert posts == [("/interactive/off", coordination.HANDOVER_OFF_TIMEOUT_S)]

    watcher.apply([session], 2)
    watcher._sync_gpu_handover()
    _join(watcher)
    assert posts[-1] == ("/interactive/on", coordination.HANDOVER_ON_TIMEOUT_S)


def test_watcher_does_not_start_moshi_that_was_down(monkeypatch) -> None:
    posts: list[str] = []
    monkeypatch.setattr(coordination, "_post_supervisor", lambda path, timeout: posts.append(path))
    monkeypatch.setattr("hsengine.engine.yk_sentinel.moshi_serving", lambda *a, **k: False)
    watcher = coordination.ActivityWatcher(addr="127.0.0.1:1", peer="hermes")
    watcher.connected = True
    watcher.apply([_act(), _session()], 1)
    watcher._sync_gpu_handover()
    _join(watcher)
    watcher.apply([_session()], 2)
    watcher._sync_gpu_handover()
    _join(watcher)
    assert posts == ["/interactive/off"]


def test_watcher_does_not_restore_after_the_session_ends(monkeypatch) -> None:
    posts: list[str] = []
    monkeypatch.setattr(coordination, "_post_supervisor", lambda path, timeout: posts.append(path))
    monkeypatch.setattr("hsengine.engine.yk_sentinel.moshi_serving", lambda *a, **k: True)
    watcher = coordination.ActivityWatcher(addr="127.0.0.1:1", peer="hermes")
    watcher.connected = True
    watcher.apply([_act(), _session()], 1)
    watcher._sync_gpu_handover()
    _join(watcher)
    watcher.apply([], 2)
    watcher._sync_gpu_handover()
    _join(watcher)
    assert posts == ["/interactive/off"]


def test_own_activity_does_not_stop_moshi(monkeypatch) -> None:
    posts: list[str] = []
    monkeypatch.setattr(coordination, "_post_supervisor", lambda path, timeout: posts.append(path))
    watcher = coordination.ActivityWatcher(addr="127.0.0.1:1", peer="hermes")
    watcher.connected = True
    watcher.apply([_act(peer="hermes")], 1)
    watcher._sync_gpu_handover()
    assert watcher._handover_thread is None
    assert posts == []
