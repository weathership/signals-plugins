"""Status.surfaces — advertise the Hermes UI without loopback or secrets."""
from __future__ import annotations

from unittest.mock import patch

import pytest

from hsengine.config import reset_config
from hsengine.engine import surfaces

ENV_KEYS = ("HERMES_ADVERTISE_HOST", "SIGNALS_ADVERTISE_HOST", "HERMES_PRIMARY_UI")


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    for key in ENV_KEYS:
        monkeypatch.delenv(key, raising=False)
    reset_config()
    yield
    reset_config()


def test_configured_advertise_host_wins(monkeypatch):
    monkeypatch.setenv("HERMES_ADVERTISE_HOST", "lattice.example.org")
    reset_config()
    assert surfaces.advertise_host() == "lattice.example.org"
    assert surfaces.primary_ui_url() == "http://lattice.example.org:9119"


def test_advertise_host_accepts_host_port_or_url(monkeypatch):
    monkeypatch.setenv("HERMES_ADVERTISE_HOST", "hub.example.org:50551")
    reset_config()
    assert surfaces.advertise_host() == "hub.example.org"
    monkeypatch.setenv("HERMES_ADVERTISE_HOST", "https://hub.example.org/")
    reset_config()
    assert surfaces.advertise_host() == "hub.example.org"


def test_loopback_is_never_advertised(monkeypatch):
    monkeypatch.setenv("HERMES_ADVERTISE_HOST", "127.0.0.1")
    reset_config()
    with patch.object(surfaces.socket, "getfqdn", return_value="localhost"):
        with patch.object(surfaces.socket, "gethostname", return_value="localhost"):
            assert surfaces.advertise_host() == ""
            assert surfaces.primary_ui_url() == ""
            assert surfaces.local_surfaces(True) == []


def test_default_advertise_host_is_the_lattice_host():
    assert surfaces.advertise_host() == "tinybox.dev.vista.zndx.org"
    assert surfaces.primary_ui_url() == "http://tinybox.dev.vista.zndx.org:9119"


def test_primary_surface_is_the_federated_menu_url():
    got = surfaces.local_surfaces(True)
    primary = [s for s in got if s.kind == "primary"]
    assert len(primary) == 1
    assert primary[0].url == "http://tinybox.dev.vista.zndx.org:9119"
    assert primary[0].healthy is True


def test_primary_ui_override_rewrites_loopback(monkeypatch):
    monkeypatch.setenv("HERMES_ADVERTISE_HOST", "lattice.example.org")
    monkeypatch.setenv("HERMES_PRIMARY_UI", "http://127.0.0.1:9119/")
    reset_config()
    assert surfaces.primary_ui_url() == "http://lattice.example.org:9119"


def test_local_surfaces_shape(monkeypatch):
    monkeypatch.setenv("HERMES_ADVERTISE_HOST", "lattice.example.org")
    reset_config()
    got = surfaces.local_surfaces(False)
    kinds = [(s.kind, s.url, s.healthy) for s in got]
    assert ("primary", "http://lattice.example.org:9119", False) in kinds
    assert ("health", "http://lattice.example.org:9119/api/health", False) in kinds
    blob = " ".join(s.url for s in got).lower()
    for forbidden in ("password", "api_key", "secret", "token"):
        assert forbidden not in blob


def test_canonical_target_rewrites_loopback_only(monkeypatch):
    monkeypatch.setenv("HERMES_ADVERTISE_HOST", "lattice.example.org")
    reset_config()
    assert surfaces.canonical_target("127.0.0.1:50051") == "lattice.example.org:50051"
    assert surfaces.canonical_target("10.1.1.1:50051") == "10.1.1.1:50051"
    assert surfaces.canonical_target("") == ""
