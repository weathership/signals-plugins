"""HOCON is the only config entry; lattice port is 50651."""
from __future__ import annotations

import os

from hsengine.config import get_int, get_str, load_config, reset_config


def test_lattice_port_and_project_defaults():
    reset_config()
    assert get_int("hermes.engine.grpc.port") == 50651
    assert get_str("hermes.engine.grpc.host") == "0.0.0.0"
    assert get_int("hermes.dashboard.http.bind_port") == 9119


def test_federation_peers_default_to_gaius_then_aegir():
    reset_config()
    from hsengine.engine.federation import federation_peers

    assert federation_peers() == ["127.0.0.1:50051", "127.0.0.1:50151"]


def test_load_config_rereads_when_base_conf_mtime_changes(tmp_path):
    """The engine process lives across voice edits; a stale lru cache keeps the first speaker."""
    cfg_dir = tmp_path / "config"
    cfg_dir.mkdir()
    base = cfg_dir / "base.conf"
    base.write_text('voice = "one.wav"\n')
    reset_config()
    assert load_config(cfg_dir).get("voice") == "one.wav"
    base.write_text('voice = "two.wav"\n')
    stat = base.stat()
    os.utime(base, (stat.st_atime, stat.st_mtime + 2))
    assert load_config(cfg_dir).get("voice") == "two.wav"
