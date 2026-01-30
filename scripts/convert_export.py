#!/usr/bin/env python3
"""
Convert Claude Code session JSONL files to clean plain text for LightRAG ingestion.

Usage:
    python convert_export.py /path/to/session.jsonl /path/to/output/
    python convert_export.py /path/to/project/dir/ /path/to/output/
    python convert_export.py --auto /path/to/output/
"""

import json
import argparse
import sys
from pathlib import Path
from datetime import datetime
from typing import Optional, List, Dict, Any
import re


class JSONLConverter:
    """Convert Claude Code JSONL sessions to plain text."""

    def __init__(self, output_dir: Path):
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.processed_sessions = set()

    def _is_command_message(self, content: str) -> bool:
        """Check if message contains command tags."""
        return bool(re.search(r"<(local-)?command-", content))

    def _is_meta_message(self, content: str) -> bool:
        """Check if message is metadata (isMeta flag)."""
        # This is checked at the message level, not content level
        return False

    def _extract_text_blocks(self, content: Any) -> List[str]:
        """Extract text from content blocks (handles both string and list)."""
        texts = []

        if isinstance(content, str):
            # Plain string content
            if not self._is_command_message(content):
                texts.append(content)
        elif isinstance(content, list):
            # List of content blocks
            for block in content:
                if isinstance(block, dict):
                    if block.get("type") == "text" and "text" in block:
                        texts.append(block["text"])
                    # Skip tool_use, thinking, tool_result blocks

        return texts

    def _collapse_code_blocks(self, text: str) -> str:
        """Replace code blocks >10 lines with collapsed summary."""
        lines = text.split("\n")
        result = []
        i = 0

        while i < len(lines):
            line = lines[i]

            # Detect code block start (```language or just ```)
            if line.strip().startswith("```"):
                code_lines = [line]
                i += 1

                # Collect code block lines
                while i < len(lines) and not lines[i].strip().startswith("```"):
                    code_lines.append(lines[i])
                    i += 1

                # Include closing ```
                if i < len(lines):
                    code_lines.append(lines[i])
                    i += 1

                # If block is >10 lines, collapse it
                if len(code_lines) > 10:
                    first_line = code_lines[0].strip()
                    if first_line.startswith("```"):
                        first_line = first_line[3:].strip()
                    if not first_line:
                        first_line = (
                            code_lines[1].strip() if len(code_lines) > 1 else "code"
                        )

                    result.append(
                        f"[code block: {first_line}... ({len(code_lines)} lines)]"
                    )
                else:
                    result.extend(code_lines)
            else:
                # Check for file dump (very long single line with code indicators)
                if len(line) > 500 and any(
                    indicator in line
                    for indicator in ["def ", "class ", "import ", "function ", "{"]
                ):
                    result.append("[file dump: long code output stripped]")
                else:
                    result.append(line)
                i += 1

        return "\n".join(result)

    def _should_skip_message(self, msg_obj: Dict[str, Any]) -> bool:
        """Determine if message should be skipped."""
        msg_type = msg_obj.get("type")

        # Skip non-conversation types
        if msg_type in (
            "queue-operation",
            "file-history-snapshot",
            "system",
            "summary",
        ):
            return True

        # Skip if no message field
        if "message" not in msg_obj:
            return True

        # Skip if isMeta flag is true
        if msg_obj.get("isMeta"):
            return True

        return False

    def _extract_user_message(self, msg_obj: Dict[str, Any]) -> Optional[str]:
        """Extract user message text, applying filters."""
        if self._should_skip_message(msg_obj):
            return None

        message = msg_obj.get("message", {})
        if message.get("role") != "user":
            return None

        content = message.get("content")

        # Handle string content
        if isinstance(content, str):
            if self._is_command_message(content):
                return None
            return content.strip()

        # Handle list content
        if isinstance(content, list):
            # Check if it's all tool_result blocks (skip entire message)
            has_text = False
            has_tool_result = False

            for block in content:
                if isinstance(block, dict):
                    if block.get("type") == "tool_result":
                        has_tool_result = True
                    elif block.get("type") == "text":
                        has_text = True

            # If only tool_results, skip
            if has_tool_result and not has_text:
                return None

            # Extract text blocks
            texts = self._extract_text_blocks(content)
            if texts:
                return "\n".join(texts).strip()

        return None

    def _extract_assistant_message(self, msg_obj: Dict[str, Any]) -> Optional[str]:
        """Extract assistant message text, stripping thinking/tool_use."""
        if self._should_skip_message(msg_obj):
            return None

        message = msg_obj.get("message", {})
        if message.get("role") != "assistant":
            return None

        content = message.get("content")

        # Assistant content should be a list
        if not isinstance(content, list):
            return None

        # Extract only text blocks (skip thinking, tool_use)
        texts = self._extract_text_blocks(content)
        if texts:
            return "\n".join(texts).strip()

        return None

    def _format_timestamp(self, iso_timestamp: str) -> str:
        """Convert ISO timestamp to HH:MM format."""
        try:
            dt = datetime.fromisoformat(iso_timestamp.replace("Z", "+00:00"))
            return dt.strftime("%H:%M")
        except:
            return "??:??"

    def _get_date_from_timestamp(self, iso_timestamp: str) -> str:
        """Convert ISO timestamp to YYYY-MM-DD format."""
        try:
            dt = datetime.fromisoformat(iso_timestamp.replace("Z", "+00:00"))
            return dt.strftime("%Y-%m-%d")
        except:
            return "unknown-date"

    def _load_session_metadata(self, jsonl_path: Path) -> Optional[Dict[str, Any]]:
        """Load session metadata from sessions-index.json."""
        index_path = jsonl_path.parent / "sessions-index.json"

        if not index_path.exists():
            return None

        try:
            with open(index_path, "r") as f:
                index = json.load(f)

            # Find entry matching this JSONL file
            for entry in index.get("entries", []):
                if entry.get("fullPath") == str(jsonl_path):
                    return entry
        except:
            pass

        return None

    def _get_summary(self, jsonl_path: Path, first_user_message: Optional[str]) -> str:
        """Get session summary from metadata or first user message."""
        metadata = self._load_session_metadata(jsonl_path)

        if metadata and metadata.get("summary"):
            return metadata["summary"]

        if first_user_message:
            # Truncate to ~60 chars
            summary = first_user_message[:60].replace("\n", " ")
            if len(first_user_message) > 60:
                summary += "..."
            return summary

        return "Untitled Session"

    def convert_jsonl(self, jsonl_path: Path) -> bool:
        """Convert a single JSONL file to text. Returns True if successful."""
        jsonl_path = Path(jsonl_path)

        if not jsonl_path.exists():
            print(f"ERROR: File not found: {jsonl_path}")
            return False

        messages = []
        first_timestamp = None
        first_user_message = None
        session_id = None
        project_path = None

        # Parse JSONL
        try:
            with open(jsonl_path, "r") as f:
                for line in f:
                    if not line.strip():
                        continue

                    try:
                        msg_obj = json.loads(line)
                    except json.JSONDecodeError:
                        continue

                    # Capture metadata from first message
                    if first_timestamp is None:
                        first_timestamp = msg_obj.get("timestamp")
                        session_id = msg_obj.get("sessionId")
                        project_path = msg_obj.get("cwd")

                    # Extract user message
                    user_text = self._extract_user_message(msg_obj)
                    if user_text:
                        if first_user_message is None:
                            first_user_message = user_text
                        timestamp = msg_obj.get("timestamp")
                        messages.append(
                            {"role": "user", "text": user_text, "timestamp": timestamp}
                        )
                        continue

                    # Extract assistant message
                    assistant_text = self._extract_assistant_message(msg_obj)
                    if assistant_text:
                        timestamp = msg_obj.get("timestamp")
                        messages.append(
                            {
                                "role": "assistant",
                                "text": assistant_text,
                                "timestamp": timestamp,
                            }
                        )

        except Exception as e:
            print(f"ERROR reading {jsonl_path}: {e}")
            return False

        # Check if we have content
        if not messages:
            print(f"WARNING: No messages extracted from {jsonl_path}")
            return False

        # Check for duplicates
        if session_id and session_id in self.processed_sessions:
            print(f"WARNING: Session {session_id} already processed, skipping")
            return False

        if session_id:
            self.processed_sessions.add(session_id)

        # Generate output filename
        date_str = (
            self._get_date_from_timestamp(first_timestamp)
            if first_timestamp
            else "unknown-date"
        )
        time_str = (
            self._format_timestamp(first_timestamp) if first_timestamp else "00-00"
        )
        time_str = time_str.replace(":", "-")

        summary = self._get_summary(jsonl_path, first_user_message)
        summary_slug = re.sub(r"[^a-z0-9]+", "-", summary.lower())[:40].strip("-")

        output_filename = f"session_{date_str}_{time_str}_{summary_slug}.txt"
        output_path = self.output_dir / output_filename

        # Generate output text
        output_lines = []
        output_lines.append(f"=== Session: {summary} ===")
        output_lines.append(f"Date: {date_str} {time_str.replace('-', ':')}")
        if project_path:
            output_lines.append(f"Project: {project_path}")
        if session_id:
            output_lines.append(f"Session ID: {session_id}")
        output_lines.append(f"Messages: {len(messages)}")
        output_lines.append("===\n")

        # Add conversation
        for msg in messages:
            timestamp = (
                self._format_timestamp(msg["timestamp"])
                if msg["timestamp"]
                else "??:??"
            )
            speaker = "User" if msg["role"] == "user" else "Assistant"

            # Collapse code blocks and clean up
            text = self._collapse_code_blocks(msg["text"])

            output_lines.append(f"[{timestamp}] {speaker}:")
            output_lines.append(text)
            output_lines.append("")

        # Write output
        try:
            with open(output_path, "w") as f:
                f.write("\n".join(output_lines))

            print(f"✓ {output_filename} ({len(messages)} messages)")
            return True

        except Exception as e:
            print(f"ERROR writing {output_path}: {e}")
            return False

    def convert_directory(self, dir_path: Path) -> int:
        """Convert all JSONL files in a directory. Returns count of successful conversions."""
        dir_path = Path(dir_path)

        if not dir_path.is_dir():
            print(f"ERROR: Not a directory: {dir_path}")
            return 0

        jsonl_files = list(dir_path.glob("*.jsonl"))

        if not jsonl_files:
            print(f"WARNING: No JSONL files found in {dir_path}")
            return 0

        count = 0
        for jsonl_path in sorted(jsonl_files):
            if self.convert_jsonl(jsonl_path):
                count += 1

        return count

    def auto_discover(self) -> int:
        """Auto-discover Claude project for current directory. Returns count of conversions."""
        # Get current project path
        cwd = Path.cwd()

        # Encode path like Claude does: /home/user/projects/myapp -> -home-user-projects-myapp
        encoded = "-" + cwd.as_posix().lstrip("/").replace("/", "-")

        claude_projects_dir = Path.home() / ".claude" / "projects"
        project_dir = claude_projects_dir / encoded

        if not project_dir.exists():
            print(f"ERROR: Claude project directory not found: {project_dir}")
            return 0

        print(f"Auto-discovered: {project_dir}")
        return self.convert_directory(project_dir)


def main():
    parser = argparse.ArgumentParser(
        description="Convert Claude Code JSONL sessions to plain text for LightRAG"
    )
    parser.add_argument(
        "--auto",
        action="store_true",
        help="Auto-discover Claude project for current directory",
    )
    parser.add_argument(
        "input",
        nargs="?",
        help="Path to JSONL file, directory of JSONL files (or output dir if using --auto)",
    )
    parser.add_argument("output", nargs="?", help="Output directory for text files")

    args = parser.parse_args()

    # Handle --auto mode
    if args.auto:
        if not args.input:
            parser.error("--auto mode requires output directory argument")
        converter = JSONLConverter(args.input)
        count = converter.auto_discover()
        print(f"\nConverted {count} session(s)")
        return 0 if count > 0 else 1

    # Handle normal mode
    if not args.input or not args.output:
        parser.error("input and output arguments required (or use --auto <output-dir>)")

    converter = JSONLConverter(args.output)
    input_path = Path(args.input)

    if input_path.is_file():
        success = converter.convert_jsonl(input_path)
        return 0 if success else 1
    elif input_path.is_dir():
        count = converter.convert_directory(input_path)
        print(f"\nConverted {count} session(s)")
        return 0 if count > 0 else 1
    else:
        print(f"ERROR: Path not found: {input_path}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
