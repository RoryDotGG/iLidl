"""Config file management for ilidl."""

import tomllib
from pathlib import Path

import tomli_w

_DEFAULT_PATH = Path.home() / ".config" / "ilidl" / "config.toml"


class Config:
    def __init__(self, path: Path | None = None) -> None:
        self.path = path or _DEFAULT_PATH
        self.browser: str = ""
        self._load()

    def _load(self) -> None:
        if not self.path.exists():
            return
        with open(self.path, "rb") as f:
            data = tomllib.load(f)
        self.browser = data.get("auth", {}).get("browser", "")

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with open(self.path, "wb") as f:
            tomli_w.dump({"auth": {"browser": self.browser}}, f)
