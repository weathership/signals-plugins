# Copyright 2026 zndx
# SPDX-License-Identifier: Apache-2.0

from pathlib import Path

from hsengine.engine.moshi_supervisor import _has_libpython311, python311_lib


def test_python311_lib_follows_the_interpreter(tmp_path: Path) -> None:
    real = tmp_path / "real"
    (real / "bin").mkdir(parents=True)
    (real / "lib").mkdir()
    (real / "bin" / "python3.11").write_text("", encoding="utf-8")
    (real / "lib" / "libpython3.11.so.1.0").write_bytes(b"")
    link_dir = tmp_path / "venv" / "bin"
    link_dir.mkdir(parents=True)
    (link_dir / "python3.11").symlink_to(real / "bin" / "python3.11")
    assert python311_lib(link_dir / "python3.11") == real / "lib"


def test_site_packages_is_not_the_libpython_soname() -> None:
    site = "/opt/tts-venv/lib/python3.11/site-packages/torch/lib"
    assert _has_libpython311(site) is False
    assert _has_libpython311("/nix/store/hash-python3-3.11.15/lib") is True


def test_python311_lib_is_none_without_the_soname(tmp_path: Path) -> None:
    (tmp_path / "bin").mkdir()
    (tmp_path / "lib").mkdir()
    (tmp_path / "bin" / "python3.11").write_text("", encoding="utf-8")
    assert python311_lib(tmp_path / "bin" / "python3.11") is None
