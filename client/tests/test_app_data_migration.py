from pathlib import Path

import server


def test_legacy_install_data_migrates_once_without_overwriting(tmp_path: Path):
    legacy = tmp_path / "installed"
    target = tmp_path / "local-app-data"
    (legacy / ".license").mkdir(parents=True)
    (legacy / "profiles" / "account").mkdir(parents=True)
    (legacy / ".license" / "license_state.json").write_text("legacy", encoding="utf-8")
    (legacy / "profiles" / "account" / "state.json").write_text("profile", encoding="utf-8")

    (target / ".license").mkdir(parents=True)
    (target / ".license" / "license_state.json").write_text("current", encoding="utf-8")

    server._migrate_legacy_install_data(legacy, target)

    assert (target / ".license" / "license_state.json").read_text(encoding="utf-8") == "current"
    assert (target / "profiles" / "account" / "state.json").read_text(encoding="utf-8") == "profile"
    assert (target / ".legacy_install_data_migrated").exists()

    (legacy / "uploads").mkdir()
    (legacy / "uploads" / "late.png").write_bytes(b"late")
    server._migrate_legacy_install_data(legacy, target)

    assert not (target / "uploads" / "late.png").exists()
