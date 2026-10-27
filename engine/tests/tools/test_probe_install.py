import tarfile

import pytest

from parsewright.tools.probes.probe_install import (
    APP,
    PROPS_V1,
    SOURCETYPE_V1,
    build_package,
    expected_epochs,
    packages_dir,
)


def test_package_holds_only_the_app_folder(tmp_path):
    package = build_package(tmp_path, "0.0.1", PROPS_V1)
    with tarfile.open(package) as tar:
        names = tar.getnames()
        props = tar.extractfile(f"{APP}/default/props.conf").read().decode()
    assert sorted(names) == [
        f"{APP}/default/app.conf",
        f"{APP}/default/props.conf",
        f"{APP}/metadata/default.meta",
    ]
    assert all(".." not in n and not n.startswith("/") for n in names)
    assert f"[{SOURCETYPE_V1}]" in props
    assert package.stat().st_mode & 0o777 == 0o644


def test_test_identity_and_pw_naming():
    assert APP.startswith("TA-parsewright-") and APP.endswith("__test_probe")
    assert SOURCETYPE_V1.endswith("__test_probe")


def test_expected_epochs_use_the_probe_timezone():
    # 2026-01-02 03:04:05 in Pacific/Chatham (UTC+13:45 in January) is 2026-01-01 13:19:05 UTC.
    assert expected_epochs()[0] == 1767273545
    assert expected_epochs() == sorted(expected_epochs())


@pytest.mark.parametrize("raw", ["", "relative/dir"])
def test_packages_dir_must_be_absolute(monkeypatch, raw):
    monkeypatch.setenv("PARSEWRIGHT_PACKAGES_DIR", raw)
    with pytest.raises(ValueError):
        packages_dir()


def test_packages_dir_must_exist(monkeypatch, tmp_path):
    monkeypatch.setenv("PARSEWRIGHT_PACKAGES_DIR", str(tmp_path / "missing"))
    with pytest.raises(ValueError):
        packages_dir()
    monkeypatch.setenv("PARSEWRIGHT_PACKAGES_DIR", str(tmp_path))
    assert packages_dir() == tmp_path.resolve()
