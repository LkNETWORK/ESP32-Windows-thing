from __future__ import annotations

import json

import pytest

from companion.config import Config, ConfigError, load_config, save_config


def test_first_run_creates_default_config(tmp_path) -> None:
    path = tmp_path / "config.json"
    config = load_config(path)
    assert config.port == 8722
    assert config.host == "0.0.0.0"
    assert path.exists()
    data = json.loads(path.read_text(encoding="utf-8"))
    assert data["port"] == 8722
    assert "token" not in data


def test_config_round_trips_without_rewriting(tmp_path) -> None:
    path = tmp_path / "config.json"
    custom = Config(host="127.0.0.1", port=9000, poll_interval_ms=800)
    save_config(custom, path)
    before = path.read_text(encoding="utf-8")
    loaded = load_config(path)
    assert loaded == custom
    assert path.read_text(encoding="utf-8") == before


def test_invalid_json_is_rejected_and_file_is_kept(tmp_path) -> None:
    path = tmp_path / "config.json"
    path.write_text("{not json", encoding="utf-8")
    with pytest.raises(ConfigError):
        load_config(path)
    assert path.read_text(encoding="utf-8") == "{not json"


def test_invalid_port_is_rejected(tmp_path) -> None:
    path = tmp_path / "config.json"
    path.write_text(json.dumps({"port": 80}), encoding="utf-8")
    with pytest.raises(ConfigError):
        load_config(path)


def test_missing_config_without_create_does_not_write(tmp_path) -> None:
    path = tmp_path / "config.json"
    config = load_config(path, create=False)
    assert config.port == 8722
    assert not path.exists()


def test_overrides_are_validated() -> None:
    config = Config()
    updated = config.with_overrides(port=9100)
    assert updated.port == 9100
    with pytest.raises(ConfigError):
        config.with_overrides(port=99)
