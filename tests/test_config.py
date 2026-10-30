"""Tests for ilidl config management."""

from ilidl.config import Config


def test_load_missing_file(tmp_path):
    assert Config(tmp_path / "config.toml").browser == ""


def test_save_and_load_creates_parent_dirs(tmp_path):
    path = tmp_path / "nested" / "config.toml"
    config = Config(path)
    config.browser = "brave"
    config.save()
    assert Config(path).browser == "brave"


def test_ignores_old_refresh_token_config(tmp_path):
    path = tmp_path / "config.toml"
    path.write_text('[auth]\nrefresh_token = "old"\n\n[account]\ncountry = "GB"\n')
    assert Config(path).browser == ""
