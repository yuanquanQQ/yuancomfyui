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
    assert list(target.glob(".migrated-*"))

    (legacy / "uploads").mkdir()
    (legacy / "uploads" / "late.png").write_bytes(b"late")
    server._migrate_legacy_install_data(legacy, target)

    assert not (target / "uploads" / "late.png").exists()


def test_data_migration_merges_multiple_previous_locations(tmp_path: Path):
    old_install = tmp_path / "old-install"
    old_registry_location = tmp_path / "old-drive" / "UserData"
    target = tmp_path / "new-install" / "UserData"
    (old_install / ".license").mkdir(parents=True)
    (old_registry_location / "library" / "images").mkdir(parents=True)
    (old_install / ".license" / "license_state.json").write_text(
        "license", encoding="utf-8"
    )
    (old_registry_location / "library" / "images" / "asset.png").write_bytes(
        b"asset"
    )

    server._migrate_legacy_install_data(old_install, target)
    server._migrate_legacy_install_data(old_registry_location, target)

    assert (target / ".license" / "license_state.json").read_text(
        encoding="utf-8"
    ) == "license"
    assert (target / "library" / "images" / "asset.png").read_bytes() == b"asset"
    assert len(list(target.glob(".migrated-*"))) == 2


def test_unavailable_old_drive_is_not_marked_as_migrated(tmp_path: Path):
    unavailable = tmp_path / "disconnected-drive" / "UserData"
    target = tmp_path / "new-install" / "UserData"

    server._migrate_legacy_install_data(unavailable, target)

    assert not list(target.glob(".migrated-*"))

    (unavailable / ".license").mkdir(parents=True)
    (unavailable / ".license" / "license_state.json").write_text(
        "restored", encoding="utf-8"
    )
    server._migrate_legacy_install_data(unavailable, target)

    assert (target / ".license" / "license_state.json").read_text(
        encoding="utf-8"
    ) == "restored"


def test_runtime_layout_rebuilds_missing_directories_and_metadata(tmp_path: Path):
    root = tmp_path / "UserData"

    result = server._ensure_runtime_layout(root)

    for relative in (
        ".license", ".runtime", "data/pic", "data/ple", "data/video",
        "uploads", "profiles", "outputs", "library/images",
        "library/videos", "library/audio", "library/texts", "works",
    ):
        assert (root / relative).is_dir()
    assert result["library_metadata"] == root / "library" / ".metadata.json"
    assert result["library_metadata"].read_text(encoding="utf-8") == "{}\n"


def test_runtime_layout_quarantines_damaged_paths_and_rebuilds(tmp_path: Path):
    root = tmp_path / "UserData"
    root.mkdir()
    (root / "data").write_text("user damaged directory", encoding="utf-8")
    (root / "library").mkdir()
    metadata = root / "library" / ".metadata.json"
    metadata.write_text("not valid json", encoding="utf-8")

    server._ensure_runtime_layout(root)

    assert (root / "data").is_dir()
    assert (root / "data" / "pic").is_dir()
    assert metadata.read_text(encoding="utf-8") == "{}\n"
    assert list(root.glob("data.damaged-*"))
    assert list((root / "library").glob(".metadata.json.damaged-*"))
