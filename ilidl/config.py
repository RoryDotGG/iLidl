"""Config file management for ilidl."""

import tomllib
from pathlib import Path

import tomli_w

_DEFAULT_PATH = Path.home() / ".config" / "ilidl" / "config.toml"


class Config:
    def __init__(self, path: Path | None = None) -> None:
        self.path = path or _DEFAULT_PATH
        self.refresh_token: str = ""
        self.language: str = "en"
        self.country: str = "GB"
        self._load()

    def _load(self) -> None:
        if not self.path.exists():
            return
        with open(self.path, "rb") as f:
            data = tomllib.load(f)
        auth = data.get("auth", {})
        self.refresh_token = auth.get("refresh_token", "")
        account = data.get("account", {})
        self.language = account.get("language", "en")
        self.country = account.get("country", "GB")

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        data = {
            "auth": {"refresh_token": self.refresh_token},
            "account": {
                "language": self.language,
                "country": self.country,
            },
        }
        with open(self.path, "wb") as f:
            tomli_w.dump(data, f)
