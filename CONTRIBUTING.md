# Contributing to Engram

## Getting Started

1. Fork the repository
2. Create a feature branch: `git checkout -b feature/your-feature`
3. Make your changes
4. Test locally (see below)
5. Submit a pull request

## Local Development

```bash
bash scripts/install.sh
cp configs/.env.example configs/.env
# Edit configs/.env with your API key
./engram
```

## What We're Looking For

- **New converters** — support for more AI assistant export formats
- **Bug fixes** — especially around edge cases in session parsing
- **Documentation** — clearer setup instructions, troubleshooting guides
- **Performance** — ingestion speed, query latency improvements

## Guidelines

- Keep it simple. Engram's value is in being lightweight.
- Don't add dependencies unless absolutely necessary.
- Test with real conversation data before submitting.
- Follow existing code style.

## Issues

Found a bug? Open an issue with:
- What you expected
- What happened
- Steps to reproduce
- Your environment (OS, Python version, Go version)
