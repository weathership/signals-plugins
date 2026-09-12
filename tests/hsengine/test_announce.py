"""Hermes joins the waffle walk by Engine/Announce, not a hub contract row."""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import grpc
import pytest

from hsengine.config import reset_config
from hsengine.engine import announce, federation


@pytest.fixture(autouse=True)
def _env(monkeypatch):
    monkeypatch.setenv("HERMES_ADVERTISE_HOST", "lattice.example.org")
    monkeypatch.delenv("HERMES_PRIMARY_UI", raising=False)
    monkeypatch.delenv("SIGNALS_ENGINE_TARGET", raising=False)
    reset_config()
    federation.reset_status_cache()
    yield
    reset_config()
    federation.reset_status_cache()


def test_local_engine_target_is_advertise_host_not_loopback():
    assert announce.local_engine_target() == "lattice.example.org:50651"


def test_announce_targets_include_directory_and_peers(monkeypatch):
    monkeypatch.setenv("SIGNALS_ENGINE_TARGET", "tinybox.dev.vista.zndx.org:50551")
    reset_config()
    targets = announce.announce_targets()
    assert targets[0] == "tinybox.dev.vista.zndx.org:50551"
    assert "127.0.0.1:50151" in targets
    assert "127.0.0.1:50051" in targets
    assert all(not t.endswith(":50651") for t in targets)


def test_build_announce_carries_primary_surface():
    req = announce.build_announce(dashboard_healthy=True)
    assert req is not None
    assert req.project == "hermes"
    assert req.engine_target == "lattice.example.org:50651"
    assert req.ttl_seconds == 90
    primary = [s.url for s in req.surfaces if s.kind == "primary"]
    assert primary == ["http://lattice.example.org:9119"]


def test_announce_once_unimplemented_is_honest():
    class _Unimplemented(grpc.RpcError):
        def code(self):
            return grpc.StatusCode.UNIMPLEMENTED

        def details(self):
            return "Method not implemented!"

    req = announce.build_announce()
    with patch("hsengine.engine.announce.grpc.insecure_channel") as ch:
        ch.return_value.__enter__.return_value = MagicMock()
        with patch("hsengine.engine.announce.zpb_grpc.EngineStub") as stub_cls:
            stub_cls.return_value.Announce.side_effect = _Unimplemented()
            assert announce.announce_once("127.0.0.1:50551", req) is None


def test_announce_all_records_accepted_ack():
    ack = announce.zpb.AnnounceAck(accepted=True, ttl_seconds=90, error="")
    req = announce.build_announce()
    with patch.object(announce, "announce_targets", return_value=["127.0.0.1:50151"]):
        with patch.object(announce, "announce_once", return_value=ack) as once:
            rows = announce.announce_all()
    assert rows == [("127.0.0.1:50151", ack)]
    once.assert_called_once()
    sent = once.call_args[0][1]
    assert sent.project == req.project
    assert sent.engine_target == req.engine_target
