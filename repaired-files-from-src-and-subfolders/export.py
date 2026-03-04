"""
tripartite/export.py

Export functions for reconstructing original files and generating hierarchy dumps.

Two export modes:
1. Reconstruct original files to disk (inverse of ingest)
2. Generate file dump + folder tree (like the input format)
"""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Optional


# ── Export to Original Files ──────────────────────────────────────────────────

def export_to_files(
    conn: sqlite3.Connection,
    output_dir: Path,
    on_progress=None
) -> dict:
    """
    Reconstruct original files from the database and write to disk.
    
    Args:
        conn: Database connection
        output_dir: Root directory to write files to
        on_progress: Optional callback(file_count, total_files, current_file)
    
    Returns:
        {"files_written": N, "bytes_written": N, "errors": [...]}
    """
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    
    # Get all source files
    rows = conn.execute("""
        SELECT file_cid, path, name, line_cids
        FROM source_files
        ORDER BY path
    """).fetchall()
    
    total = len(rows)
    stats = {"files_written": 0, "bytes_written": 0, "errors": []}
    
    for idx, (file_cid, path, name, line_cids_json) in enumerate(rows):
        if on_progress:
            on_progress(idx + 1, total, name)
        
        try:
            # Parse line_cids
            line_cids = json.loads(line_cids_json)
            
            # Fetch all lines for this file
            if not line_cids:
                # Empty file
                content = ""
            else:
                placeholders = ",".join("?" * len(line_cids))
                lines = conn.execute(
                    f"SELECT content FROM verbatim_lines WHERE line_cid IN ({placeholders})",
                    line_cids
                ).fetchall()
                
                # Join lines (they're already normalized without \n)
                content = "\n".join(line[0] for line in lines)
            
            # Determine output path
            # The 'path' in DB is absolute - we want to preserve structure relative to some root
            # For now, just use the filename to avoid conflicts
            out_path = output_dir / name
            
            # Write file
            out_path.write_text(content, encoding="utf-8")
            
            stats["files_written"] += 1
            stats["bytes_written"] += len(content.encode("utf-8"))
            
        except Exception as e:
            stats["errors"].append({"file": name, "error": str(e)})
    
    return stats


def export_with_structure(
    conn: sqlite3.Connection,
    output_dir: Path,
    preserve_paths: bool = True,
    on_progress=None
) -> dict:
    """
    Export files preserving their directory structure.
    
    If preserve_paths=True, recreates the original folder hierarchy.
    If False, flattens to output_dir with sanitized names.
    """
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    
    rows = conn.execute("""
        SELECT file_cid, path, name, line_cids
        FROM source_files
        ORDER BY path
    """).fetchall()
    
    total = len(rows)
    stats = {"files_written": 0, "bytes_written": 0, "errors": []}
    
    for idx, (file_cid, orig_path, name, line_cids_json) in enumerate(rows):
        if on_progress:
            on_progress(idx + 1, total, name)
        
        try:
            # Reconstruct content
            line_cids = json.loads(line_cids_json)
            
            if not line_cids:
                content = ""
            else:
                placeholders = ",".join("?" * len(line_cids))
                lines = conn.execute(
                    f"SELECT content FROM verbatim_lines WHERE line_cid IN ({placeholders})",
                    line_cids
                ).fetchall()
                content = "\n".join(line[0] for line in lines)
            
            # Determine output path
            if preserve_paths:
                # Try to preserve relative structure
                # The path in DB might be absolute - make it relative
                try:
                    rel_path = Path(orig_path).relative_to(Path(orig_path).anchor)
                except ValueError:
                    rel_path = Path(name)
                
                out_path = output_dir / rel_path
                out_path.parent.mkdir(parents=True, exist_ok=True)
            else:
                out_path = output_dir / name
            
            # Write
            out_path.write_text(content, encoding="utf-8")
            
            stats["files_written"] += 1
            stats["bytes_written"] += len(content.encode("utf-8"))
            
        except Exception as e:
            stats["errors"].append({"file": name, "error": str(e)})
    
    return stats


# ── Export to Hierarchy Dump ───────────────────────────────────────────────────

def generate_folder_tree(conn: sqlite3.Connection) -> str:
    """
    Generate a folder tree visualization like _project_folder_tree.txt.
    
    Returns a string with the tree structure.
    """
    # Get all source files
    rows = conn.execute("""
        SELECT path, name, source_type
        FROM source_files
        ORDER BY path
    """).fetchall()
    
    # Build tree structure
    tree = {}
    for path, name, source_type in rows:
        parts = Path(path).parts
        current = tree
        for part in parts[:-1]:  # All but filename
            if part not in current:
                current[part] = {}
            current = current[part]
        # Add file
        current[name] = None  # Leaf node
    
    # Format as tree
    lines = [
        f"Project Tree: Tripartite Export",
        f"Generated: {datetime.now()}",
        "",
    ]
    
    def format_tree(node, prefix="", is_last=True):
        items = sorted(node.items(), key=lambda x: (x[1] is not None, x[0]))
        for idx, (name, children) in enumerate(items):
            is_last_item = idx == len(items) - 1
            
            if children is None:  # File
                icon = "📄"
                connector = "└── " if is_last_item else "├── "
                lines.append(f"{prefix}{connector}{icon} {name}")
            else:  # Directory
                icon = "📁"
                connector = "└── " if is_last_item else "├── "
                lines.append(f"{prefix}{connector}{icon} {name}/")
                
                # Recurse
                extension = "    " if is_last_item else "│   "
                format_tree(children, prefix + extension, is_last_item)
    
    format_tree(tree)
    
    return "\n".join(lines)


def generate_file_dump(conn: sqlite3.Connection) -> str:
    """
    Generate a concatenated file dump like _filedump.txt.
    
    Returns a string with all file contents separated by headers.
    """
    rows = conn.execute("""
        SELECT path, name, line_cids
        FROM source_files
        ORDER BY path
    """).fetchall()
    
    lines = [f"Dump: Tripartite Export", ""]
    
    for path, name, line_cids_json in rows:
        # Separator
        lines.append("")
        lines.append("-" * 80)
        lines.append(f"FILE: {path}")
        lines.append("-" * 80)
        
        # Reconstruct content
        line_cids = json.loads(line_cids_json)
        
        if not line_cids:
            lines.append("(empty file)")
        else:
            placeholders = ",".join("?" * len(line_cids))
            content_rows = conn.execute(
                f"SELECT content FROM verbatim_lines WHERE line_cid IN ({placeholders})",
                line_cids
            ).fetchall()
            
            for content_row in content_rows:
                lines.append(content_row[0])
    
    return "\n".join(lines)


def export_hierarchy_dump(
    conn: sqlite3.Connection,
    output_dir: Path,
    prefix: str = "export"
) -> dict:
    """
    Generate folder tree + file dump files.
    
    Creates:
        - {prefix}_folder_tree.txt
        - {prefix}_filedump.txt
    
    Returns:
        {"tree_path": Path, "dump_path": Path}
    """
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    
    # Generate tree
    tree_content = generate_folder_tree(conn)
    tree_path = output_dir / f"{prefix}_folder_tree.txt"
    tree_path.write_text(tree_content, encoding="utf-8")
    
    # Generate dump
    dump_content = generate_file_dump(conn)
    dump_path = output_dir / f"{prefix}_filedump.txt"
    dump_path.write_text(dump_content, encoding="utf-8")
    
    return {
        "tree_path": tree_path,
        "dump_path": dump_path,
    }


# ── CLI Export ────────────────────────────────────────────────────────────────

def export_all(
    db_path: Path,
    output_dir: Path,
    mode: str = "dump",
    verbose: bool = True
) -> dict:
    """
    Export everything from a database.
    
    Args:
        db_path: Path to .db file
        output_dir: Where to write exports
        mode: 'dump' (hierarchy dump) | 'files' (reconstruct files) | 'both'
        verbose: Print progress
    
    Returns:
        Stats dict
    """
    conn = sqlite3.connect(str(db_path))
    stats = {}
    
    if mode in ("dump", "both"):
        if verbose:
            print("[export] Generating hierarchy dump...")
        result = export_hierarchy_dump(conn, output_dir)
        if verbose:
            print(f"[export] ✓ Tree: {result['tree_path']}")
            print(f"[export] ✓ Dump: {result['dump_path']}")
        stats["dump"] = result
    
    if mode in ("files", "both"):
        if verbose:
            print("[export] Reconstructing files...")
        
        def progress(current, total, name):
            if verbose:
                print(f"[export] {current}/{total} - {name}")
        
        result = export_to_files(conn, output_dir, on_progress=progress)
        if verbose:
            print(f"[export] ✓ {result['files_written']} files written")
            print(f"[export] ✓ {result['bytes_written']} bytes")
            if result['errors']:
                print(f"[export] ✗ {len(result['errors'])} errors")
                for err in result['errors']:
                    print(f"         {err['file']}: {err['error']}")
        stats["files"] = result
    
    conn.close()
    return stats


# ── Utility Functions ─────────────────────────────────────────────────────────

def get_export_stats(conn: sqlite3.Connection) -> dict:
    """Get info about what would be exported."""
    stats = {}
    
    # Count files
    stats["file_count"] = conn.execute("SELECT COUNT(*) FROM source_files").fetchone()[0]
    
    # Total lines
    stats["line_count"] = conn.execute("SELECT COUNT(*) FROM verbatim_lines").fetchone()[0]
    
    # Total bytes (approximate from line content)
    row = conn.execute("SELECT SUM(byte_len) FROM verbatim_lines").fetchone()
    stats["total_bytes"] = row[0] if row[0] else 0
    
    # File types
    rows = conn.execute("""
        SELECT source_type, COUNT(*) 
        FROM source_files 
        GROUP BY source_type
    """).fetchall()
    stats["by_type"] = {r[0]: r[1] for r in rows}
    
    # Languages
    rows = conn.execute("""
        SELECT language, COUNT(*) 
        FROM source_files 
        WHERE language IS NOT NULL
        GROUP BY language
    """).fetchall()
    stats["by_language"] = {r[0]: r[1] for r in rows}
    
    return stats
