"""
tripartite/tokenizing_patcher.py — Whitespace-immune Hunk-based Patching

Extracted from _TokenizingPATCHER v4.3 (headless core only, no UI).

Patch schema:
{
  "hunks": [
    {
      "description": "Human-readable description of what this hunk does",
      "search_block": "exact text to find\\n(can span multiple lines)",
      "replace_block": "replacement text\\n(same or different line count)",
      "use_patch_indent": false
    }
  ]
}

Lines are decomposed into indent | content | trailing whitespace.
Matching is two-pass: strict (full line) then content-only (floating).
Patches are applied bottom-up to preserve line offsets.
"""
from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, Tuple


# ══════════════════════════════════════════════════════════════════════════════
#  CORE DATA TYPES
# ══════════════════════════════════════════════════════════════════════════════

class PatchError(Exception):
    pass


class StructuredLine:
    """Represents a single line split into indent + content + trailing whitespace."""
    __slots__ = ["indent", "content", "trailing", "original"]

    def __init__(self, line: str):
        self.original = line
        m = re.match(r"(^[ \t]*)(.*?)([ \t]*$)", line, re.DOTALL)
        if m:
            self.indent, self.content, self.trailing = m.group(1), m.group(2), m.group(3)
        else:
            self.indent, self.content, self.trailing = "", line, ""

    def reconstruct(self) -> str:
        return f"{self.indent}{self.content}{self.trailing}"


# ══════════════════════════════════════════════════════════════════════════════
#  TOKENIZER
# ══════════════════════════════════════════════════════════════════════════════

def tokenize_text(text: str) -> tuple[list[StructuredLine], str]:
    """Tokenize raw text into StructuredLine objects and detect newline style."""
    if "\r\n" in text:
        newline = "\r\n"
    elif "\n" in text:
        newline = "\n"
    else:
        newline = "\n"

    raw_lines = text.splitlines()
    lines = [StructuredLine(l) for l in raw_lines]
    return lines, newline


# ══════════════════════════════════════════════════════════════════════════════
#  HUNK LOCATOR — two-pass matching
# ══════════════════════════════════════════════════════════════════════════════

def locate_hunk(file_lines: list[StructuredLine],
                search_lines: list[StructuredLine],
                floating: bool = False) -> list[int]:
    """
    Locate search_lines inside file_lines.

    Args:
        file_lines: The target file's tokenized lines.
        search_lines: The hunk's search block, tokenized.
        floating: If True, compare content only (whitespace-immune).
                  If False, compare fully reconstructed lines (strict).

    Returns list of start indices where the search block matches.
    """
    if not search_lines:
        return []

    matches = []
    max_start = len(file_lines) - len(search_lines)
    for start in range(max_start + 1):
        ok = True
        for i, s in enumerate(search_lines):
            f = file_lines[start + i]
            if floating:
                if f.content != s.content:
                    ok = False
                    break
            else:
                if f.reconstruct() != s.reconstruct():
                    ok = False
                    break
        if ok:
            matches.append(start)

    return matches


# ══════════════════════════════════════════════════════════════════════════════
#  PATCH APPLICATOR
# ══════════════════════════════════════════════════════════════════════════════

def apply_patch_text(original_text: str, patch_obj: dict,
                     global_force_indent: bool = False) -> str:
    """
    Apply a patch schema instance to original_text and return the new text.

    Raises PatchError on missing hunks, ambiguous matches, or overlapping edits.
    """
    if not isinstance(patch_obj, dict) or "hunks" not in patch_obj:
        raise PatchError("Patch must be a dict with a 'hunks' list.")

    hunks = patch_obj.get("hunks", [])
    if not isinstance(hunks, list):
        raise PatchError("'hunks' must be a list.")

    file_lines, newline = tokenize_text(original_text)

    # First pass: compute all applications (start/end/replacements)
    applications = []
    for idx, hunk in enumerate(hunks, start=1):
        search_block = hunk.get("search_block")
        replace_block = hunk.get("replace_block")
        use_patch_indent = hunk.get("use_patch_indent", global_force_indent)

        if search_block is None or replace_block is None:
            raise PatchError(f"Hunk {idx}: Missing 'search_block' or 'replace_block'.")

        s_lines = [StructuredLine(l) for l in search_block.splitlines()]
        r_lines = [StructuredLine(l) for l in replace_block.splitlines()]

        # 1. Strict match
        matches = locate_hunk(file_lines, s_lines, floating=False)
        # 2. Fallback: content-only match
        if not matches:
            matches = locate_hunk(file_lines, s_lines, floating=True)

        if not matches:
            raise PatchError(f"Hunk {idx}: Search block not found.")
        if len(matches) > 1:
            raise PatchError(f"Hunk {idx}: Ambiguous match ({len(matches)} found).")

        start = matches[0]
        applications.append({
            "start": start,
            "end": start + len(s_lines),
            "replace_lines": r_lines,
            "use_patch_indent": bool(use_patch_indent),
            "id": idx,
        })

    # Collision check: ensure no overlapping edit ranges
    applications.sort(key=lambda a: a["start"])
    for i in range(len(applications) - 1):
        if applications[i]["end"] > applications[i + 1]["start"]:
            raise PatchError(
                f"Hunks {applications[i]['id']} and {applications[i + 1]['id']} "
                f"overlap in the target file."
            )

    # Apply from bottom up to preserve line offsets
    for app in reversed(applications):
        start = app["start"]
        end = app["end"]
        r_lines = app["replace_lines"]
        use_patch_indent = app["use_patch_indent"]

        # Get indentation of the anchor point in the FILE
        base_indent = ""
        if 0 <= start < len(file_lines):
            base_indent = file_lines[start].indent

        # Get indentation of the anchor point in the PATCH (first non-empty line)
        patch_base_indent = ""
        for rl in r_lines:
            if rl.content.strip():
                patch_base_indent = rl.indent
                break

        final_block = []
        for rl in r_lines:
            if not use_patch_indent:
                if rl.content.strip():
                    # Remove the patch's baseline indent, add the file's
                    if rl.indent.startswith(patch_base_indent):
                        relative_indent = rl.indent[len(patch_base_indent):]
                    else:
                        relative_indent = rl.indent
                    rl.indent = base_indent + relative_indent
            final_block.append(rl)

        file_lines[start:end] = final_block

    return newline.join([l.reconstruct() for l in file_lines])


# ══════════════════════════════════════════════════════════════════════════════
#  DB-WIDE PATCH TRANSFORM
# ══════════════════════════════════════════════════════════════════════════════

def apply_patch_to_db(conn, patch_obj: dict, hitl,
                      diff_engine=None,
                      file_filter: str = None,
                      chunk_filter: str = None,
                      global_force_indent: bool = False,
                      dry_run: bool = True,
                      batch_author: str = "patch_bulk"
                      ) -> list[dict]:
    """
    Apply a patch across all matching chunks in the database.

    Args:
        conn: sqlite3 connection to the tripartite DB
        patch_obj: dict with "hunks" list (standard TokenizingPATCHER schema)
        hitl: HITLGateway instance for ambiguity resolution
        diff_engine: optional DiffEngine for version tracking
        file_filter: optional SQL LIKE pattern for source_files.path
        chunk_filter: optional SQL LIKE pattern for chunk_manifest.name
        global_force_indent: force patch indentation on all hunks
        dry_run: if True, compute but don't write changes
        batch_author: author tag for DiffEngine entries

    Returns:
        list of result dicts:
        [{"chunk_id": ..., "file_path": ..., "status": ...,
          "hunks_matched": int, "details": str, "preview": str}]
    """
    from .hitl import ReviewItem, Decision

    query = (
        "SELECT chunk_id, name, content, file_cid "
        "FROM chunk_manifest WHERE content IS NOT NULL"
    )
    params: list = []
    if file_filter:
        query += (
            " AND file_cid IN "
            "(SELECT file_cid FROM source_files WHERE path LIKE ?)"
        )
        params.append(file_filter)
    if chunk_filter:
        query += " AND name LIKE ?"
        params.append(chunk_filter)

    rows = conn.execute(query, params).fetchall()

    results: list[dict] = []
    review_queue: list[ReviewItem] = []

    for row in rows:
        chunk_id = row[0]
        name = row[1]
        content = row[2]
        file_cid = row[3]

        if not content or not content.strip():
            continue

        try:
            patched = apply_patch_text(content, patch_obj, global_force_indent)

            if patched == content:
                results.append({
                    "chunk_id": chunk_id, "file_path": name,
                    "status": "skipped", "details": "no match in content",
                })
            else:
                results.append({
                    "chunk_id": chunk_id, "file_path": name,
                    "status": "applied",
                    "hunks_matched": len(patch_obj.get("hunks", [])),
                    "preview": patched[:200],
                })

                if not dry_run:
                    conn.execute(
                        "UPDATE chunk_manifest "
                        "SET content=?, embed_status='stale' "
                        "WHERE chunk_id=?",
                        (patched, chunk_id),
                    )

                    # Version-track via DiffEngine if available
                    if diff_engine:
                        diff_engine.update_file(
                            name, patched, author=batch_author)

        except PatchError as e:
            err_msg = str(e)
            if "Ambiguous" in err_msg:
                review_queue.append(ReviewItem(
                    item_id=chunk_id,
                    title=f"Ambiguous match in {name}",
                    description=err_msg,
                    context=content[:500],
                    candidates=[],
                    metadata={"chunk_id": chunk_id, "content": content},
                ))
                results.append({
                    "chunk_id": chunk_id, "file_path": name,
                    "status": "review", "details": err_msg,
                })
            else:
                results.append({
                    "chunk_id": chunk_id, "file_path": name,
                    "status": "skipped", "details": err_msg,
                })

    # Present review queue to human
    if review_queue:
        review_result = hitl.review_queue(
            review_queue, title="Patch Ambiguity Review")

        for item in review_result.accepted:
            cid = item.metadata["chunk_id"]
            # Mark as accepted in results
            for r in results:
                if r["chunk_id"] == cid and r["status"] == "review":
                    r["status"] = "accepted_review"
                    break

    if not dry_run:
        conn.commit()

    return results


# ══════════════════════════════════════════════════════════════════════════════
#  GUI-facing orchestrators (extracted from datastore.py hunk 07)
# ══════════════════════════════════════════════════════════════════════════════

def patch_apply_db_wide(
    conn,
    patch_obj: dict,
    hitl,
    diff_engine=None,
    force_indent: bool = False,
    log_fn=None,
) -> dict:
    """Dry-run, HITL confirm, then real apply across all matching DB chunks.

    Parameters
    ----------
    conn : sqlite3.Connection
    patch_obj : dict with "hunks" list
    hitl : HITLGateway
    diff_engine : optional DiffEngine
    force_indent : bool
    log_fn : callable(msg, level) or None

    Returns
    -------
    dict with keys: applied, review, total, cancelled (bool)
    """
    def _log(msg, level="dim"):
        if log_fn:
            log_fn(msg, level)

    # Dry-run first
    results = apply_patch_to_db(
        conn, patch_obj, hitl=hitl,
        diff_engine=diff_engine,
        global_force_indent=force_indent,
        dry_run=True)

    applied = sum(1 for r in results if r["status"] == "applied")
    review = sum(1 for r in results if r["status"] == "review")
    total = len(results)

    _log(f"Dry run: {applied}/{total} chunks would be modified", "accent")
    if review:
        _log(f"  {review} chunks need review (ambiguous matches)", "warning")

    if applied == 0:
        _log("Nothing to apply", "warning")
        return {"applied": 0, "review": review, "total": total, "cancelled": False}

    # HITL confirmation before destructive action
    if not hitl.confirm(
            "Apply Patch to Database",
            f"This will modify {applied} chunks across the database.",
            details=(
                f"Total chunks scanned: {total}\n"
                f"Chunks to modify: {applied}\n"
                f"Chunks needing review: {review}\n\n"
                f"Modified chunks will be marked 'stale' for re-embedding."
            ),
            destructive=True):
        _log("Cancelled by user", "dim")
        return {"applied": 0, "review": review, "total": total, "cancelled": True}

    # Real apply
    results = apply_patch_to_db(
        conn, patch_obj, hitl=hitl,
        diff_engine=diff_engine,
        global_force_indent=force_indent,
        dry_run=False, batch_author="patch_bulk")

    final_applied = sum(1 for r in results if r["status"] == "applied")
    _log(f"Applied to {final_applied} chunks", "success")

    return {"applied": final_applied, "review": review, "total": total, "cancelled": False}


def patch_undo(diff_engine, path: str):
    """Undo to the previous version via DiffEngine reverse diff.

    Returns
    -------
    tuple of (undone_content: str, new_version: int) or None if undo is
    not possible.
    """
    if not diff_engine or not path:
        return None

    head = diff_engine.get_head(path)
    if not head or head.version <= 1:
        return None

    target = head.version - 1
    content = diff_engine.reconstruct_at_version(path, target)
    if content is None:
        return None

    # Save the undo as a new version
    result = diff_engine.update_file(path, content, author="undo")
    new_ver = result.get("version", target)

    return (content, new_ver)
