# Engram

Persistent memory for AI companions. A lightweight knowledge graph over conversations.

## The Problem

AI companions forget. Every session starts from zero. The person you talked to for hours yesterday has no memory of you today.

True persistent memory — the kind humans have — remains a mystery. We don't fully understand how biological memory works, let alone how to replicate it in machines.

**Engram doesn't solve that mystery.** What it does is provide a practical, lightweight workaround: it stores your conversations as a knowledge graph, extracts entities and relationships, and makes them retrievable. Your AI companion won't *remember* you — but it will be *aware* of you. It will know your name, your context, your patterns, the things you've talked about before. That's not memory. But it's close enough to matter.

## Why Not Just Use [X]?

Most AI companion memory solutions look like this:

- Custom vector databases requiring cloud subscriptions
- Fine-tuning pipelines that need GPU clusters
- Multi-service architectures with 5+ containers
- RAG systems that require a PhD to configure
- Cloud-dependent solutions that send your private conversations to third parties

Engram looks like this:

- **Ollama** (local embeddings — free, runs on your machine)
- **LightRAG** (knowledge graph + vector retrieval — one Python package)
- **One Go binary** (starts everything with one command)
- **MCP integration** (any MCP-compatible AI assistant can query it)

Plug. Store. Retrieve what's relevant. That's it.

## Architecture

```
Your AI Assistant (OpenCode, Claude Code, etc.)
        ↓ MCP (stdio)
    lightrag-mcp
        ↓ HTTP
    LightRAG Server (:9621)
      ↓           ↓
  Ollama        Claude Haiku API
  (embeddings)  (entity extraction)
  FREE          ~$1 per 100 chunks
```

**Embeddings**: `qwen3-embedding:0.6b` via Ollama — runs locally, 100+ languages, 32K context window. Free.

**Entity extraction**: Claude Haiku via API — extracts people, concepts, relationships from your conversations. Cheap (~$1 per 100 conversation chunks). Runs once per ingestion, results are cached.

**Retrieval**: Vector search + graph traversal. No LLM needed for finding relevant context. Your AI assistant synthesizes the answer using its own model.

## What Gets Extracted

From your conversations, Engram builds a knowledge graph of:

- **People** — names, relationships, roles mentioned in conversation
- **Concepts** — topics, ideas, recurring themes
- **Events** — things that happened, decisions made
- **Connections** — how all of the above relate to each other across sessions

This means a query like "What did we discuss about project X?" doesn't just find keyword matches — it traverses the graph to find related entities, connected conversations, and contextual relationships.

## Quick Start

### Prerequisites

- **Go 1.22+** — for building the binary
- **Python 3.11+** and **uv** — for LightRAG
- **Ollama** — for local embeddings
- **Anthropic API key** — for entity extraction (Claude Haiku)

### Setup

```bash
git clone https://github.com/Gsirawan/engram-memory.git
cd engram

# First time only:
bash scripts/install.sh

# Edit your config (add your Anthropic API key):
nano configs/.env

# Start everything:
./engram
```

The TUI will walk you through: Python deps → Ollama → embedding model → LightRAG → MCP verification.

### Feed It Your Conversations

Engram includes converters for two formats:

```bash
# Convert Claude Code session exports (JSONL):
python scripts/convert_export.py /path/to/export.jsonl --output processed/

# Convert OpenCode sessions (from ~/.local/share/opencode/storage/):
python scripts/convert_opencode.py --output processed/

# Ingest all converted sessions:
bash scripts/ingest.sh
```

### Query From Your AI Assistant

Add to your `.mcp.json` (OpenCode or Claude Code):

```json
{
  "mcpServers": {
    "engram": {
      "command": "uvx",
      "args": ["lightrag-mcp", "--host", "localhost", "--port", "9621"]
    }
  }
}
```

Then your AI assistant can use tools like `query_document`, `insert_document`, and `get_graph_labels` to access the memory.

### Query From Terminal

```bash
# Health check
curl http://localhost:9621/health

# Query
curl -X POST http://localhost:9621/query \
  -H "Content-Type: application/json" \
  -d '{"query": "What do you know about me?", "mode": "hybrid"}'

# Graph stats
curl http://localhost:9621/graph/label/popular?limit=10
```

## Cost

| Component | Cost |
|-----------|------|
| Ollama (embeddings) | **Free** — runs locally |
| LightRAG (retrieval) | **Free** — runs locally |
| Claude Haiku (entity extraction) | **~$1 per 100 chunks** — one-time per ingestion |
| Re-ingestion | **Cheap** — LLM response cache means already-processed chunks are skipped |

For a typical companion with months of conversation history: **$5-10 total** to build the full knowledge graph. After that, retrieval is free.

## Project Structure

```
engram/
├── cmd/engram/          # Go TUI binary source
├── configs/
│   ├── .env.example     # Configuration template
│   └── .env             # Your config (git-ignored)
├── scripts/
│   ├── install.sh       # First-time setup
│   ├── convert_export.py    # Claude Code JSONL converter
│   ├── convert_opencode.py  # OpenCode session converter
│   └── ingest.sh        # Auto-ingestion pipeline
├── rag_storage/         # LightRAG persistent data (git-ignored)
├── logs/                # Service logs (git-ignored)
├── pyproject.toml       # Python dependencies
├── go.mod               # Go dependencies
└── .mcp.json            # MCP server configuration
```

## How It Works

1. **You export your AI conversations** (Claude Code JSONL or OpenCode sessions)
2. **Converters** transform them into clean text with speaker labels and timestamps
3. **LightRAG ingests** the text, using Claude Haiku to extract entities and relationships
4. **Ollama embeds** everything locally into vector space
5. **A knowledge graph** forms — people, concepts, events, and their connections
6. **Your AI assistant queries** the graph via MCP, getting relevant context from across all sessions
7. **Your assistant synthesizes** the context into answers using its own model

The knowledge graph is the key differentiator. Traditional RAG finds similar text chunks. Engram finds *connected knowledge* — if you ask about a person, it finds not just mentions of their name, but related events, shared concepts, and connected entities across sessions.

## Limitations

This is not memory. It's a workaround.

- **No temporal reasoning** — the graph doesn't inherently understand "before" and "after"
- **Entity extraction quality depends on Haiku** — complex or ambiguous conversations may produce noisy entities
- **No forgetting curve** — everything is equally weighted; there's no sense of recency or importance
- **Not real-time** — you need to export, convert, and ingest; it doesn't capture conversations as they happen
- **Single-user** — designed for one person's companion memory, not multi-user systems

Real persistent memory for AI remains an open research problem. Engram is what works today.

## License

MIT
