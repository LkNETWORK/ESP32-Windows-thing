from __future__ import annotations

from companion import paths


def test_explicit_data_dir_override(tmp_path, monkeypatch) -> None:
    target = tmp_path / "state"
    monkeypatch.setenv("ESP_MEDIA_CONTROLLER_DATA", str(target))
    paths.reset_for_tests()
    try:
        assert paths.data_dir() == target.resolve()
        assert paths.config_path() == target.resolve() / "config.json"
        assert paths.log_dir() == target.resolve() / "logs"
        assert paths.using_fallback() is False
    finally:
        paths.reset_for_tests()


def test_unwritable_preferred_dir_falls_back(tmp_path, monkeypatch) -> None:
    monkeypatch.delenv("ESP_MEDIA_CONTROLLER_DATA", raising=False)
    blocked = tmp_path / "blocked"
    blocked.write_text("not a directory", encoding="utf-8")
    fallback = tmp_path / "fallback"
    monkeypatch.setattr(paths, "_candidate_dirs", lambda: [blocked, fallback])
    paths.reset_for_tests()
    try:
        assert paths.data_dir() == fallback.resolve()
        assert paths.using_fallback() is True
        assert fallback.is_dir()
    finally:
        paths.reset_for_tests()


def test_unwritable_override_is_an_error(tmp_path, monkeypatch) -> None:
    blocked = tmp_path / "blocked"
    blocked.write_text("not a directory", encoding="utf-8")
    monkeypatch.setenv("ESP_MEDIA_CONTROLLER_DATA", str(blocked))
    paths.reset_for_tests()
    try:
        try:
            paths.data_dir()
        except OSError as exc:
            assert "not writable" in str(exc)
        else:
            raise AssertionError("expected OSError")
    finally:
        paths.reset_for_tests()
