# Security Policy

## Scope

Engram stores and retrieves personal conversation data. Security matters.

## Reporting a Vulnerability

If you discover a security vulnerability, please report it responsibly:

1. **Open a public issue**
2. Include: description, reproduction steps, potential impact

We will acknowledge within 48 hours and aim to patch critical issues within 7 days.

## Known Security Considerations

- **LightRAG API** binds to `127.0.0.1` (localhost only) by default. Do not change this to `0.0.0.0` unless you understand the implications — the API has no authentication.
- **Conversation data** is stored unencrypted in `rag_storage/`. Protect this directory with appropriate filesystem permissions.
- **API keys** are stored in `configs/.env`. This file is git-ignored but ensure it has restricted permissions (`chmod 600`).
- **Entity extraction** sends conversation chunks to the Anthropic API. Review Anthropic's data retention policy if this concerns you.
