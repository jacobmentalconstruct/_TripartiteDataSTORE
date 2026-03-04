"""
Tripartite DiffEngine — Version Layer (Layer 4)

Hybrid versioning with HEAD state + bidirectional diff history.
Stores both forward diffs (readable audit trail) and reverse diffs
(fast backward reconstruction from HEAD to any prior version).

Storage model:
  - files table    : HEAD state (current truth, fast reads for UI/RAG)
  - diff_log table : forward + reverse diffs per edit, timestamped

Reconstruction: start at HEAD, apply reverse diffs walking backward
in time until target version is reached.

Lives alongside verbatim.db / semantic.db / graph.db as diffs.db.
The CID-based verbatim layer already deduplicates line content,
so diffs only capture the delta — both directions cost bytes, not KB.
"""

from __future__ import annotations

import datetime
import difflib
import hashlib
import re
import sqlite3
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


# ══════════════════════════════════════════════════════════════════════════════
#  DATA TYPES
# ══════════════════════════════════════════════════════════════════════════════

@dataclass
class DiffEntry:
    """A single history entry with both diff directions."""
    diff_id: str
    file_id: str
    timestamp: str
    change_type: str              # CREATE | EDIT | DELETE
    forward_diff: str             # "what changed" — human-readable
    reverse_diff: str             # "how to undo" — for reconstruction
    author: str
    version: int                  # monotonic version counter
    content_hash: str             # SHA-256 of content after this edit


@dataclass
class FileState:
    """Current HEAD state of a tracked file."""
    file_id: str
    path: str
    content: str
    version: int
    last_updated: str
    content_hash: str


@dataclass
class TokenizedLine:
    """A line decomposed into whitespace-safe tokens for matching."""
    line_num: int                 # 0-indexed position in file
    raw: str                      # original line with whitespace
    leading: str                  # leading whitespace
    content: str                  # stripped content (match target)
    trailing: str                 # trailing whitespace
    content_hash: str             # hash of content only


# ══════════════════════════════════════════════════════════════════════════════
#  LINE TOKENIZER — whitespace-safe matching
# ══════════════════════════════════════════════════════════════════════════════

_LEADING_RE = re.compile(r'^(\s*)')
_TRAILING_RE = re.compile(r'(\s*)$')


def tokenize_line(line_num: int, raw: str) -> TokenizedLine:
    """
    Decompose a line into leading_ws | content | trailing_ws.
    Matching operates on content only — immune to indentation changes.
    """
    # Don't strip the newline for raw storage, but separate whitespace
    leading = _LEADING_RE.match(raw).group(1) if raw else ""
    trailing_match = _TRAILING_RE.search(raw.rstrip('\n\r'))
    trailing = trailing_match.group(1) if trailing_match else ""

    content = raw.strip()
    content_hash = hashlib.sha256(content.encode('utf-8')).hexdigest()[:16]

    return TokenizedLine(
        line_num=line_num,
        raw=raw,
        leading=leading,
        content=content,
        trailing=trailing,
        content_hash=content_hash,
    )


def tokenize_content(text: str) -> list[TokenizedLine]:
    """Tokenize an entire file into lines."""
    lines = text.splitlines(keepends=True)
    return [tokenize_line(i, line) for i, line in enumerate(lines)]


# ══════════════════════════════════════════════════════════════════════════════
#  DIFF ENGINE
# ══════════════════════════════════════════════════════════════════════════════

class DiffEngine:
    """
    Bidirectional diff storage with HEAD + history.

    HEAD is always the current truth (fast reads).
    History stores both forward and reverse diffs so any prior
    version can be reconstructed by walking backward from HEAD.

    Parameters:
        db_path:  Path to diffs.db (defaults to alongside main DB)
    """

    def __init__(self, db_path: Optional[Path] = None):
        self.db_path = db_path or Path("diffs.db")
        self._init_db()

    def _get_conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.db_path))
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
        return conn

    def _init_db(self):
        with self._get_conn() as conn:
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS files (
                    id            TEXT PRIMARY KEY,
                    path          TEXT UNIQUE NOT NULL,
                    content       TEXT,
                    version       INTEGER DEFAULT 0,
                    content_hash  TEXT,
                    last_updated  TIMESTAMP
                );

                CREATE TABLE IF NOT EXISTS diff_log (
                    id            TEXT PRIMARY KEY,
                    file_id       TEXT NOT NULL,
                    version       INTEGER NOT NULL,
                    timestamp     TIMESTAMP,
                    change_type   TEXT,
                    forward_diff  TEXT,
                    reverse_diff  TEXT,
                    author        TEXT,
                    content_hash  TEXT,
                    FOREIGN KEY(file_id) REFERENCES files(id)
                );

                CREATE INDEX IF NOT EXISTS idx_diff_file_version
                    ON diff_log(file_id, version DESC);

                CREATE INDEX IF NOT EXISTS idx_diff_file_time
                    ON diff_log(file_id, timestamp DESC);
            """)

    # ── Core operations ───────────────────────────────────────────────────

    def update_file(self, path: str, new_content: str,
                    author: str = "user") -> Dict[str, Any]:
        """
        Atomic update: compute bidirectional diffs, log history, update HEAD.

        Returns dict with status, file_id, version, diff sizes.
        """
        path = str(Path(path).as_posix())
        now = datetime.datetime.utcnow().isoformat()
        new_hash = hashlib.sha256(new_content.encode()).hexdigest()[:32]

        with self._get_conn() as conn:
            row = conn.execute(
                "SELECT id, content, version, content_hash FROM files WHERE path = ?",
                (path,)
            ).fetchone()

            if not row:
                # New file — CREATE
                file_id = str(uuid.uuid4())
                conn.execute(
                    "INSERT INTO files (id, path, content, version, content_hash, last_updated) "
                    "VALUES (?, ?, ?, ?, ?, ?)",
                    (file_id, path, new_content, 1, new_hash, now))

                self._log_diff(
                    conn, file_id, version=1, change_type="CREATE",
                    forward_diff="[New File Created]",
                    reverse_diff="[File Deleted]",
                    author=author, timestamp=now, content_hash=new_hash)

                return {"status": "created", "file_id": file_id,
                        "version": 1}

            file_id = row["id"]
            old_content = row["content"] or ""
            old_version = row["version"] or 0
            new_version = old_version + 1

            # Skip if unchanged
            if row["content_hash"] == new_hash:
                return {"status": "unchanged", "file_id": file_id,
                        "version": old_version}

            # Compute both diff directions
            old_lines = old_content.splitlines(keepends=True)
            new_lines = new_content.splitlines(keepends=True)

            forward_diff = "".join(difflib.unified_diff(
                old_lines, new_lines,
                fromfile=f"v{old_version}/{path}",
                tofile=f"v{new_version}/{path}"))

            reverse_diff = "".join(difflib.unified_diff(
                new_lines, old_lines,
                fromfile=f"v{new_version}/{path}",
                tofile=f"v{old_version}/{path}"))

            # Store both diffs
            self._log_diff(
                conn, file_id, version=new_version, change_type="EDIT",
                forward_diff=forward_diff, reverse_diff=reverse_diff,
                author=author, timestamp=now, content_hash=new_hash)

            # Update HEAD
            conn.execute(
                "UPDATE files SET content = ?, version = ?, "
                "content_hash = ?, last_updated = ? WHERE id = ?",
                (new_content, new_version, new_hash, now, file_id))

            return {
                "status": "updated", "file_id": file_id,
                "version": new_version,
                "forward_size": len(forward_diff),
                "reverse_size": len(reverse_diff),
            }

    def _log_diff(self, conn, file_id, version, change_type,
                  forward_diff, reverse_diff, author, timestamp,
                  content_hash):
        diff_id = str(uuid.uuid4())
        conn.execute(
            "INSERT INTO diff_log "
            "(id, file_id, version, timestamp, change_type, "
            " forward_diff, reverse_diff, author, content_hash) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (diff_id, file_id, version, timestamp, change_type,
             forward_diff, reverse_diff, author, content_hash))

    # ── Read operations ───────────────────────────────────────────────────

    def get_head(self, path: str) -> Optional[FileState]:
        """Fast retrieval of current content (HEAD)."""
        with self._get_conn() as conn:
            row = conn.execute(
                "SELECT id, path, content, version, last_updated, content_hash "
                "FROM files WHERE path = ?", (path,)
            ).fetchone()
            if not row:
                return None
            return FileState(
                file_id=row["id"], path=row["path"],
                content=row["content"] or "",
                version=row["version"], last_updated=row["last_updated"],
                content_hash=row["content_hash"] or "")

    def get_history(self, path: str) -> list[DiffEntry]:
        """Full edit history for a file, newest first."""
        with self._get_conn() as conn:
            file_row = conn.execute(
                "SELECT id FROM files WHERE path = ?", (path,)
            ).fetchone()
            if not file_row:
                return []

            rows = conn.execute(
                "SELECT id, file_id, timestamp, change_type, "
                "forward_diff, reverse_diff, author, version, content_hash "
                "FROM diff_log WHERE file_id = ? ORDER BY version DESC",
                (file_row["id"],)
            ).fetchall()

            return [DiffEntry(
                diff_id=r["id"], file_id=r["file_id"],
                timestamp=r["timestamp"], change_type=r["change_type"],
                forward_diff=r["forward_diff"],
                reverse_diff=r["reverse_diff"],
                author=r["author"], version=r["version"],
                content_hash=r["content_hash"] or "",
            ) for r in rows]

    def reconstruct_at_version(self, path: str,
                               target_version: int) -> Optional[str]:
        """
        Reconstruct file content at a specific version.

        Strategy: start at HEAD, apply reverse diffs backward
        until we reach target_version.
        """
        head = self.get_head(path)
        if not head:
            return None

        if target_version >= head.version:
            return head.content

        if target_version < 1:
            return None

        with self._get_conn() as conn:
            # Get reverse diffs from HEAD version down to target+1
            rows = conn.execute(
                "SELECT version, reverse_diff FROM diff_log "
                "WHERE file_id = ? AND version > ? AND version <= ? "
                "ORDER BY version DESC",
                (self._file_id_for_path(conn, path),
                 target_version, head.version)
            ).fetchall()

        content = head.content
        for row in rows:
            reverse_diff = row["reverse_diff"]
            if reverse_diff and reverse_diff not in ("[File Deleted]",):
                content = self._apply_unified_diff(content, reverse_diff)

        return content

    def reconstruct_at_timestamp(self, path: str,
                                 timestamp: str) -> Optional[str]:
        """Reconstruct content at a point in time."""
        with self._get_conn() as conn:
            file_id = self._file_id_for_path(conn, path)
            if not file_id:
                return None

            # Find the version active at that timestamp
            row = conn.execute(
                "SELECT version FROM diff_log "
                "WHERE file_id = ? AND timestamp <= ? "
                "ORDER BY version DESC LIMIT 1",
                (file_id, timestamp)
            ).fetchone()

            if not row:
                return None

            return self.reconstruct_at_version(path, row["version"])

    def get_diff_between(self, path: str,
                         from_version: int,
                         to_version: int) -> Optional[str]:
        """
        Get a unified diff between any two versions.
        Reconstructs both versions and diffs them.
        """
        content_from = self.reconstruct_at_version(path, from_version)
        content_to = self.reconstruct_at_version(path, to_version)
        if content_from is None or content_to is None:
            return None

        old_lines = content_from.splitlines(keepends=True)
        new_lines = content_to.splitlines(keepends=True)

        return "".join(difflib.unified_diff(
            old_lines, new_lines,
            fromfile=f"v{from_version}/{path}",
            tofile=f"v{to_version}/{path}",
            lineterm=""))

    def list_tracked_files(self) -> list[FileState]:
        """List all tracked files with their HEAD state."""
        with self._get_conn() as conn:
            rows = conn.execute(
                "SELECT id, path, content, version, last_updated, content_hash "
                "FROM files ORDER BY path"
            ).fetchall()
            return [FileState(
                file_id=r["id"], path=r["path"],
                content=r["content"] or "",
                version=r["version"],
                last_updated=r["last_updated"],
                content_hash=r["content_hash"] or "",
            ) for r in rows]

    def delete_file(self, path: str, author: str = "user") -> bool:
        """Soft-delete: log the deletion, clear HEAD content."""
        now = datetime.datetime.utcnow().isoformat()
        with self._get_conn() as conn:
            row = conn.execute(
                "SELECT id, content, version FROM files WHERE path = ?",
                (path,)
            ).fetchone()
            if not row:
                return False

            file_id = row["id"]
            old_content = row["content"] or ""
            new_version = (row["version"] or 0) + 1

            # Store reverse diff (full content as reverse, for resurrection)
            reverse_diff = old_content  # special: full content for undelete
            self._log_diff(
                conn, file_id, version=new_version, change_type="DELETE",
                forward_diff="[File Deleted]", reverse_diff=reverse_diff,
                author=author, timestamp=now, content_hash="")

            conn.execute(
                "UPDATE files SET content = '', version = ?, "
                "content_hash = '', last_updated = ? WHERE id = ?",
                (new_version, now, file_id))

            return True

    # ── Helpers ───────────────────────────────────────────────────────────

    def _file_id_for_path(self, conn, path: str) -> Optional[str]:
        row = conn.execute(
            "SELECT id FROM files WHERE path = ?", (path,)
        ).fetchone()
        return row["id"] if row else None

    @staticmethod
    def _apply_unified_diff(content: str, diff_text: str) -> str:
        """
        Apply a unified diff to content.

        Parses the unified diff format and applies additions/removals.
        This is the core reconstruction engine.
        """
        lines = content.split("\n")
        # Remove trailing empty element from split if content ends with \n
        if lines and lines[-1] == "":
            lines.pop()

        result = []
        line_idx = 0  # current position in source lines (0-indexed)

        hunks = DiffEngine._parse_unified_hunks(diff_text)

        for hunk_start, hunk_len, operations in hunks:
            # hunk_start is 1-indexed; copy unchanged lines before this hunk
            target_idx = hunk_start - 1
            while line_idx < target_idx and line_idx < len(lines):
                result.append(lines[line_idx])
                line_idx += 1

            # Apply hunk operations
            for op, text in operations:
                if op == " ":
                    # Context line — advance past it in source
                    if line_idx < len(lines):
                        result.append(lines[line_idx])
                        line_idx += 1
                elif op == "-":
                    # Remove line from source (skip it)
                    if line_idx < len(lines):
                        line_idx += 1
                elif op == "+":
                    # Add line to result
                    result.append(text)

        # Copy remaining lines after last hunk
        while line_idx < len(lines):
            result.append(lines[line_idx])
            line_idx += 1

        return "\n".join(result) + "\n" if result else ""

    @staticmethod
    def _parse_unified_hunks(diff_text: str
                             ) -> list[tuple[int, int, list[tuple[str, str]]]]:
        """
        Parse unified diff into list of (start_line, length, operations).
        Each operation is (op_char, text) where op is ' ', '+', or '-'.
        """
        hunks = []
        current_ops: list[tuple[str, str]] = []
        current_start = 0
        current_len = 0

        for line in diff_text.split("\n"):
            # Skip file headers
            if line.startswith("---") or line.startswith("+++"):
                continue

            # Hunk header: @@ -start,len +start,len @@ optional context
            if line.startswith("@@"):
                # Flush previous hunk
                if current_ops:
                    hunks.append((current_start, current_len, current_ops))
                    current_ops = []

                # Parse the "from" side
                match = re.search(
                    r"@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@", line)
                if match:
                    current_start = int(match.group(1))
                    current_len = int(match.group(2) or 1)
                continue

            # Operation lines
            if line.startswith("+"):
                current_ops.append(("+", line[1:]))
            elif line.startswith("-"):
                current_ops.append(("-", line[1:]))
            elif line.startswith(" "):
                current_ops.append((" ", line[1:]))
            # Skip "\ No newline at end of file" etc.

        # Flush last hunk
        if current_ops:
            hunks.append((current_start, current_len, current_ops))

        return hunks


# ══════════════════════════════════════════════════════════════════════════════
#  TOKENIZED PATCH ENGINE — whitespace-immune line matching
# ══════════════════════════════════════════════════════════════════════════════

class PatchEngine:
    """
    Applies patches using tokenized line matching.

    Lines are decomposed into: leading_whitespace | content | trailing_whitespace
    Matching operates on content only, making patches immune to
    indentation changes. When a match is found, the *original* whitespace
    is preserved unless the patch explicitly specifies new whitespace.

    Patch format (JSON list of operations):
    [
        {
            "op": "replace",           // replace | insert_after | insert_before | delete
            "match": "old content",    // content to find (whitespace-stripped)
            "value": "new content",    // replacement content (for replace/insert)
            "context_before": "...",   // optional: line before match (for disambiguation)
            "context_after": "...",    // optional: line after match
            "preserve_indent": true    // default true: keep original indentation
        }
    ]
    """

    @staticmethod
    def apply_patch(content: str, operations: list[dict],
                    ) -> tuple[str, list[dict]]:
        """
        Apply a list of patch operations to content.

        Returns (patched_content, results) where results is a list of
        dicts with {"op": ..., "status": "applied"|"skipped"|"error", ...}
        """
        tokens = tokenize_content(content)
        results = []

        for op_spec in operations:
            op = op_spec.get("op", "replace")
            match_content = op_spec.get("match", "").strip()
            value = op_spec.get("value", "")
            preserve_indent = op_spec.get("preserve_indent", True)
            ctx_before = op_spec.get("context_before", "").strip()
            ctx_after = op_spec.get("context_after", "").strip()

            if not match_content:
                results.append({"op": op, "status": "error",
                                "reason": "empty match"})
                continue

            # Find matching line(s)
            match_idx = PatchEngine._find_match(
                tokens, match_content, ctx_before, ctx_after)

            if match_idx is None:
                results.append({"op": op, "status": "skipped",
                                "reason": f"no match for: {match_content[:50]}"})
                continue

            matched_token = tokens[match_idx]

            if op == "replace":
                new_raw = PatchEngine._build_line(
                    value, matched_token if preserve_indent else None)
                tokens[match_idx] = tokenize_line(match_idx, new_raw)
                results.append({"op": op, "status": "applied",
                                "line": match_idx + 1})

            elif op == "delete":
                tokens.pop(match_idx)
                # Re-index
                for i in range(match_idx, len(tokens)):
                    tokens[i] = TokenizedLine(
                        line_num=i, raw=tokens[i].raw,
                        leading=tokens[i].leading,
                        content=tokens[i].content,
                        trailing=tokens[i].trailing,
                        content_hash=tokens[i].content_hash)
                results.append({"op": op, "status": "applied",
                                "line": match_idx + 1})

            elif op == "insert_after":
                new_raw = PatchEngine._build_line(
                    value, matched_token if preserve_indent else None)
                new_token = tokenize_line(match_idx + 1, new_raw)
                tokens.insert(match_idx + 1, new_token)
                results.append({"op": op, "status": "applied",
                                "line": match_idx + 2})

            elif op == "insert_before":
                new_raw = PatchEngine._build_line(
                    value, matched_token if preserve_indent else None)
                new_token = tokenize_line(match_idx, new_raw)
                tokens.insert(match_idx, new_token)
                results.append({"op": op, "status": "applied",
                                "line": match_idx + 1})

            else:
                results.append({"op": op, "status": "error",
                                "reason": f"unknown op: {op}"})

        patched = "".join(t.raw for t in tokens)
        return patched, results

    @staticmethod
    def _find_match(tokens: list[TokenizedLine], match_content: str,
                    ctx_before: str = "", ctx_after: str = ""
                    ) -> Optional[int]:
        """
        Find a line by content match with optional context disambiguation.

        Searches content field only (whitespace-immune).
        If multiple matches, uses context_before/context_after to narrow.
        """
        candidates = []
        for i, tok in enumerate(tokens):
            if tok.content == match_content:
                candidates.append(i)

        if not candidates:
            # Fuzzy fallback: substring match
            for i, tok in enumerate(tokens):
                if match_content in tok.content or tok.content in match_content:
                    candidates.append(i)

        if len(candidates) == 0:
            return None

        if len(candidates) == 1:
            return candidates[0]

        # Disambiguate with context
        if ctx_before or ctx_after:
            for idx in candidates:
                score = 0
                if ctx_before and idx > 0:
                    if tokens[idx - 1].content == ctx_before:
                        score += 2
                    elif ctx_before in tokens[idx - 1].content:
                        score += 1
                if ctx_after and idx < len(tokens) - 1:
                    if tokens[idx + 1].content == ctx_after:
                        score += 2
                    elif ctx_after in tokens[idx + 1].content:
                        score += 1
                if score > 0:
                    return idx

        # Default: first match
        return candidates[0]

    @staticmethod
    def _build_line(value: str, template: Optional[TokenizedLine] = None
                    ) -> str:
        """Build a raw line, optionally preserving indentation from template."""
        if template and value.strip() == value:
            # Value has no explicit whitespace — use template's indentation
            return f"{template.leading}{value.strip()}\n"
        elif not value.endswith("\n"):
            return value + "\n"
        return value

    @staticmethod
    def validate_patch(operations: list[dict]) -> list[str]:
        """
        Validate patch operations before applying.
        Returns list of error strings (empty = valid).
        """
        errors = []
        valid_ops = {"replace", "insert_after", "insert_before", "delete"}

        for i, op_spec in enumerate(operations):
            if not isinstance(op_spec, dict):
                errors.append(f"Op {i}: not a dict")
                continue

            op = op_spec.get("op")
            if op not in valid_ops:
                errors.append(f"Op {i}: invalid op '{op}' "
                              f"(valid: {', '.join(valid_ops)})")

            if not op_spec.get("match"):
                errors.append(f"Op {i}: missing 'match' field")

            if op in ("replace", "insert_after", "insert_before"):
                if "value" not in op_spec:
                    errors.append(f"Op {i}: '{op}' requires 'value' field")

        return errors

    @staticmethod
    def preview_patch(content: str, operations: list[dict]
                      ) -> tuple[str, str]:
        """
        Generate a side-by-side preview of what the patch will change.
        Returns (before_marked, after_marked) with change indicators.
        """
        patched, results = PatchEngine.apply_patch(content, operations)

        before_lines = content.splitlines(keepends=True)
        after_lines = patched.splitlines(keepends=True)

        diff = difflib.unified_diff(
            before_lines, after_lines,
            fromfile="before", tofile="after",
            lineterm="")

        return content, "".join(diff)
