"""Tests for ilidl config management."""

from pathlib import Path

from ilidl.config import Config


class TestConfig:
    def test_load_missing_file(self, tmp_path):
        config = Config(tmp_path / "config.toml")
        assert config.refresh_token == ""
        assert config.language == "en"
        assert config.country == "GB"

    def test_save_and_load(self, tmp_path):
        path = tmp_path / "config.toml"
        config = Config(path)
        config.refresh_token = "TOKEN123"
        config.language = "de"
        config.country = "DE"
        config.save()

        loaded = Config(path)
        assert loaded.refresh_token == "TOKEN123"
        assert loaded.language == "de"
        assert loaded.country == "DE"

    def test_save_creates_parent_dirs(self, tmp_path):
        path = tmp_path / "nested" / "dir" / "config.toml"
        config = Config(path)
        config.refresh_token = "TOKEN"
        config.save()
        assert path.exists()

    def test_default_path(self):
        config = Config()
        expected = Path.home() / ".config" / "ilidl" / "config.toml"
        assert config.path == expected
