#!/usr/bin/env python3
"""
Convert OpenCode session storage to clean plain text for LightRAG ingestion.

Usage:
    python convert_opencode.py ~/.local/share/opencode/storage/ /path/to/output/
"""

import json
import argparse
import sys
from pathlib import Path
from datetime import datetime, timezone
from typing import Optional, List, Dict, Any
import re


class OpenCodeConverter:
    """Convert OpenCode storage sessions to plain text."""

    def __init__(self, output_dir: Path):
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.processed_sessions = set()
        self.agent_case_map = {}  # Track original casing of agent names

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

    def _format_timestamp_ms(self, ms_epoch: int) -> str:
        """Convert millisecond epoch to HH:MM format (UTC)."""
        try:
            # Use UTC timezone for consistency
            dt = datetime.fromtimestamp(ms_epoch / 1000.0, tz=timezone.utc)
            return dt.strftime("%H:%M")
        except:
            return "??:??"

    def _get_date_from_ms(self, ms_epoch: int) -> str:
        """Convert millisecond epoch to YYYY-MM-DD format (UTC)."""
        try:
            dt = datetime.fromtimestamp(ms_epoch / 1000.0, tz=timezone.utc)
            return dt.strftime("%Y-%m-%d")
        except:
            return "unknown-date"

    def _get_time_from_ms(self, ms_epoch: int) -> str:
        """Convert millisecond epoch to HH-MM format (UTC) for filename."""
        try:
            dt = datetime.fromtimestamp(ms_epoch / 1000.0, tz=timezone.utc)
            return dt.strftime("%H-%M")
        except:
            return "00-00"

    def _normalize_agent_name(self, agent_str: str) -> str:
        """Normalize agent name to display format, tracking original casing."""
        if not agent_str:
            return ""

        # Extract base agent name (e.g., "Sisyphus" from "Planner-Sisyphus")
        parts = agent_str.split("-")
        base_agent = parts[-1] if parts else agent_str

        # Track original casing
        lower_base = base_agent.lower()
        if lower_base not in self.agent_case_map:
            self.agent_case_map[lower_base] = base_agent

        # Return the first occurrence's casing
        return self.agent_case_map[lower_base]

    def _load_session(self, session_path: Path) -> Optional[Dict[str, Any]]:
        """Load session JSON file."""
        try:
            with open(session_path, "r") as f:
                data = json.load(f)
                if isinstance(data, dict):
                    return data
        except:
            pass
        return None

    def _load_message(self, message_path: Path) -> Optional[Dict[str, Any]]:
        """Load message JSON file."""
        try:
            with open(message_path, "r") as f:
                data = json.load(f)
                if isinstance(data, dict):
                    return data
        except:
            pass
        return None

    def _load_part(self, part_path: Path) -> Optional[Dict[str, Any]]:
        """Load part JSON file."""
        try:
            with open(part_path, "r") as f:
                data = json.load(f)
                if isinstance(data, dict):
                    return data
        except:
            pass
        return None

    def _should_skip_part(self, part: Dict[str, Any]) -> bool:
        """Determine if part should be skipped."""
        part_type = part.get("type")

        # Only include text parts
        if part_type != "text":
            return True

        # Skip synthetic parts
        if part.get("synthetic"):
            return True

        # Skip excluded types (shouldn't happen with type==text, but be safe)
        excluded_types = {
            "reasoning",
            "tool",
            "step-start",
            "step-finish",
            "file",
            "compaction",
            "subtask",
        }
        if part_type in excluded_types:
            return True

        return False

    def _extract_part_text(self, part: Dict[str, Any]) -> Optional[str]:
        """Extract text from part, applying filters."""
        if self._should_skip_part(part):
            return None

        text = part.get("text", "").strip()
        if not text:
            return None

        return text

    def _get_part_timestamp(self, part: Dict[str, Any], message_time_ms: int) -> int:
        """Get timestamp for part in milliseconds. Falls back to message time."""
        part_time = part.get("time", {})
        if isinstance(part_time, dict):
            start_ms = part_time.get("start")
            if start_ms:
                return start_ms

        return message_time_ms

    def convert_session(self, session_path: Path, storage_dir: Path) -> bool:
        """Convert a single session to text. Returns True if successful."""
        session = self._load_session(session_path)
        if not session:
            return False

        session_id = session.get("id")

        # Skip child sessions (those with parentID)
        if session.get("parentID"):
            return False

        # Skip if already processed
        if session_id in self.processed_sessions:
            return False

        self.processed_sessions.add(session_id)

        # Collect messages
        messages = []
        first_timestamp_ms: Optional[int] = None

        if not session_id:
            return False

        message_dir = storage_dir / "message" / session_id
        if not message_dir.exists():
            return False

        # Walk message files
        message_files = sorted(message_dir.glob("*.json"))
        if not message_files:
            return False

        for message_file in message_files:
            message = self._load_message(message_file)
            if not message:
                continue

            message_id = message.get("id")
            message_time_data = message.get("time", {})
            message_time_ms: Optional[int] = None
            if isinstance(message_time_data, dict):
                message_time_ms = message_time_data.get("created")

            if not message_time_ms:
                continue

            if first_timestamp_ms is None:
                first_timestamp_ms = message_time_ms

            role = message.get("role")
            agent = message.get("agent", "")

            # Walk part files for this message
            if not message_id:
                continue

            part_dir = storage_dir / "part" / message_id
            if not part_dir.exists():
                continue

            part_files = sorted(part_dir.glob("*.json"))
            for part_file in part_files:
                part = self._load_part(part_file)
                if not part:
                    continue

                text = self._extract_part_text(part)
                if not text:
                    continue

                # Get timestamp for this part
                part_timestamp_ms = self._get_part_timestamp(part, message_time_ms)

                messages.append(
                    {
                        "role": role,
                        "text": text,
                        "timestamp_ms": part_timestamp_ms,
                        "agent": agent,
                    }
                )

        # Check if we have content
        if not messages:
            return False

        # Sort messages by timestamp
        messages.sort(key=lambda m: m["timestamp_ms"])

        # Generate output filename
        if not first_timestamp_ms:
            return False

        date_str = self._get_date_from_ms(first_timestamp_ms)
        time_str = self._get_time_from_ms(first_timestamp_ms)

        title = session.get("title", "Untitled Session")
        summary_slug = re.sub(r"[^a-z0-9]+", "-", title.lower())[:40].strip("-")

        output_filename = f"session_{date_str}_{time_str}_{summary_slug}.txt"
        output_path = self.output_dir / output_filename

        # Generate output text
        output_lines = []
        output_lines.append(f"=== Session: {title} ({summary_slug}) ===")
        output_lines.append(f"Date: {date_str} {time_str.replace('-', ':')}")
        output_lines.append(f"Session ID: {session_id}")
        output_lines.append(f"Messages: {len(messages)}")
        output_lines.append("===\n")

        # Add conversation
        for msg in messages:
            timestamp = self._format_timestamp_ms(msg["timestamp_ms"])

            if msg["role"] == "user":
                speaker = "User"
            else:
                agent_name = self._normalize_agent_name(msg["agent"])
                speaker = f"Assistant ({agent_name})" if agent_name else "Assistant"

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

    def convert_directory(self, storage_dir: Path) -> int:
        """Convert all sessions in storage directory. Returns count of successful conversions."""
        storage_dir = Path(storage_dir)

        if not storage_dir.is_dir():
            print(f"ERROR: Not a directory: {storage_dir}")
            return 0

        session_dir = storage_dir / "session" / "global"
        if not session_dir.exists():
            print(f"ERROR: Session directory not found: {session_dir}")
            return 0

        session_files = list(session_dir.glob("*.json"))
        if not session_files:
            print(f"WARNING: No session files found in {session_dir}")
            return 0

        count = 0
        for session_path in sorted(session_files):
            if self.convert_session(session_path, storage_dir):
                count += 1

        return count


def main():
    parser = argparse.ArgumentParser(
        description="Convert OpenCode storage sessions to plain text for LightRAG"
    )
    parser.add_argument(
        "storage_dir",
        help="Path to OpenCode storage directory (~/.local/share/opencode/storage/)",
    )
    parser.add_argument(
        "output_dir",
        help="Output directory for text files",
    )

    args = parser.parse_args()

    converter = OpenCodeConverter(args.output_dir)
    count = converter.convert_directory(args.storage_dir)
    print(f"\nConverted {count} session(s)")
    return 0 if count > 0 else 1


if __name__ == "__main__":
    sys.exit(main())
