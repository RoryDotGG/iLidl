# Contributing

Thanks for your interest in contributing to iLidl!

## Setup

```bash
git clone https://github.com/RoryDotGG/iLidl.git
cd iLidl
uv venv && source .venv/bin/activate
uv pip install -e ".[dev,auth]"
playwright install chromium
```

## Development

Run tests:

```bash
uv run pytest tests/ -q
```

Lint and format:

```bash
uv run ruff check .
uv run ruff format .
```

## Submitting changes

1. Fork the repository
2. Create a feature branch (`git checkout -b feat/my-feature`)
3. Make your changes with tests
4. Ensure `ruff check .` and `ruff format --check .` pass
5. Commit using [conventional commits](https://www.conventionalcommits.org/) (e.g. `feat:`, `fix:`, `chore:`)
6. Open a pull request against `main`

## Notes

- UK receipts are the primary focus. Other countries may work but are untested.
- The Lidl Plus API is undocumented and may change without notice.
- Keep the `App-Version` header realistic. The API rejects fake versions.
