# Copyright 2026 zndx
# SPDX-License-Identifier: Apache-2.0

from pathlib import Path

from hsengine.engine import moshi_supervisor
from hsengine.engine.moshi_supervisor import _path_has_soname, python311_lib


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


def test_site_packages_is_not_the_libpython_soname(tmp_path: Path) -> None:
    site = tmp_path / "lib" / "python3.11" / "site-packages" / "torch" / "lib"
    site.mkdir(parents=True)
    assert _path_has_soname([str(site)]) is False
    lib = tmp_path / "python3-3.11.15" / "lib"
    lib.mkdir(parents=True)
    (lib / "libpython3.11.so.1.0").write_bytes(b"")
    assert _path_has_soname([str(lib)]) is True


def test_stale_python314_wrap_uses_the_profile_interpreter(tmp_path: Path, monkeypatch) -> None:
    real = tmp_path / "nix-py"
    (real / "bin").mkdir(parents=True)
    (real / "lib").mkdir()
    (real / "bin" / "python3.11").write_text("", encoding="utf-8")
    (real / "lib" / "libpython3.11.so.1.0").write_bytes(b"")
    bin_dir = tmp_path / ".devenv" / "profile" / "bin"
    bin_dir.mkdir(parents=True)
    (bin_dir / "moshi-server").write_text(
        'libs="/nix/store/hash-python3-3.14.3/lib"\n',
        encoding="utf-8",
    )
    (bin_dir / "moshi-python").symlink_to(real / "bin" / "python3.11")
    monkeypatch.setattr(moshi_supervisor, "devenv_root", lambda: tmp_path)
    path = moshi_supervisor._ld_library_path(None)
    assert str(real / "lib") in path.split(":")


def test_python311_lib_is_none_without_the_soname(tmp_path: Path) -> None:
    (tmp_path / "bin").mkdir()
    (tmp_path / "lib").mkdir()
    (tmp_path / "bin" / "python3.11").write_text("", encoding="utf-8")
    assert python311_lib(tmp_path / "bin" / "python3.11") is None
