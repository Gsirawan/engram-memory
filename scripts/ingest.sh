#!/bin/bash
#
# Auto-ingestion script for LightRAG
# Runs converters, ingests new text files, and moves processed files
#

set -e

# ============================================================================
# Configuration
# ============================================================================

ENGRAM_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PROCESSED_DIR="${1:-$ENGRAM_DIR/../sessions/processed/}"
INGESTED_DIR="$ENGRAM_DIR/../sessions/ingested/"
LIGHTRAG_URL="http://localhost:9621"
OPENCODE_STORAGE="${HOME}/.local/share/opencode/storage/"
CLAUDE_PROJECTS="${HOME}/.claude/projects/"

# ============================================================================
# Helper functions
# ============================================================================

log() {
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*"
}

error() {
    echo "[ERROR] $*" >&2
}

# ============================================================================
# Create directories
# ============================================================================

mkdir -p "$PROCESSED_DIR"
mkdir -p "$INGESTED_DIR"

log "Starting ingestion cycle"
log "ENGRAM_DIR: $ENGRAM_DIR"
log "PROCESSED_DIR: $PROCESSED_DIR"
log "INGESTED_DIR: $INGESTED_DIR"

# ============================================================================
# Run converters
# ============================================================================

log "Running converters..."

# Claude Code JSONL converter
if [ -d "$CLAUDE_PROJECTS" ]; then
    log "Converting Claude Code projects..."
    for project_dir in "$CLAUDE_PROJECTS"/*/; do
        if [ -d "$project_dir" ]; then
            log "  Processing: $(basename "$project_dir")"
            python3 "$ENGRAM_DIR/scripts/convert_export.py" "$project_dir" "$PROCESSED_DIR" 2>&1 || true
        fi
    done
else
    log "Claude projects directory not found: $CLAUDE_PROJECTS"
fi

# OpenCode storage converter
if [ -d "$OPENCODE_STORAGE" ]; then
    log "Converting OpenCode storage..."
    python3 "$ENGRAM_DIR/scripts/convert_opencode.py" "$OPENCODE_STORAGE" "$PROCESSED_DIR" 2>&1 || true
else
    log "OpenCode storage directory not found: $OPENCODE_STORAGE"
fi

# ============================================================================
# Check LightRAG health
# ============================================================================

log "Checking LightRAG health..."
if ! curl -sf "$LIGHTRAG_URL/health" > /dev/null 2>&1; then
    error "LightRAG not running at $LIGHTRAG_URL"
    exit 1
fi
log "LightRAG is healthy"

# ============================================================================
# Ingest files
# ============================================================================

log "Ingesting files from $PROCESSED_DIR..."

ingested_count=0
failed_count=0
failed_files=()

# Find all .txt files in PROCESSED_DIR
while IFS= read -r -d '' file; do
    filename=$(basename "$file")
    log "Ingesting: $filename"
    
    # Create temporary JSON file for curl
    temp_json=$(mktemp)
    trap "rm -f $temp_json" EXIT
    
    # Read file content and create JSON payload
    # Use jq to properly escape the content
    content=$(cat "$file")
    echo "{\"text\": $(echo "$content" | jq -Rs .), \"file_source\": \"$filename\"}" > "$temp_json"
    
    # POST to LightRAG
    http_code=$(curl -s -w "%{http_code}" -X POST \
        -H "Content-Type: application/json" \
        -d @"$temp_json" \
        "$LIGHTRAG_URL/documents/text" \
        -o /dev/null)
    
    if [ "$http_code" = "200" ] || [ "$http_code" = "201" ]; then
        log "  ✓ Success (HTTP $http_code)"
        mv "$file" "$INGESTED_DIR/$filename"
        ((ingested_count++))
    else
        error "  ✗ Failed (HTTP $http_code)"
        failed_files+=("$filename")
        ((failed_count++))
    fi
    
    rm -f "$temp_json"
done < <(find "$PROCESSED_DIR" -maxdepth 1 -type f -name "*.txt" -print0)

# ============================================================================
# Summary
# ============================================================================

log "Ingestion complete"
log "  Ingested: $ingested_count files"
log "  Failed: $failed_count files"

if [ $failed_count -gt 0 ]; then
    error "Failed files (left in $PROCESSED_DIR for retry):"
    for f in "${failed_files[@]}"; do
        error "  - $f"
    done
    exit 1
fi

exit 0
