"""
tripartite-ingest CLI

Usage:
  tripartite-ingest <source> [--output <path>] [--lazy] [--verbose]

  <source>    File or directory to ingest (required)
  --output    Path to output .db file [default: <source_name>.tripartite.db]
  --lazy      Skip embedding and entity extraction (structural pipeline only)
  --verbose   Print per-file progress [default: True]
  --info      Print info about an existing .db instead of ingesting
"""

import argparse
import sys
from pathlib import Path


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="tripartite-ingest",
        description=(
            "Ingest files into a Tripartite knowledge store (.db artifact).\n"
            "Supports plain text, Markdown, and Python source files.\n\n"
            "First run will download embedding and extraction models (~672 MB).\n"
            "Subsequent runs are fully offline."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p.add_argument(
        "source",
        nargs="?",
        help="File or folder to ingest",
    )
    p.add_argument(
        "--output", "-o",
        metavar="PATH",
        help="Output .db path (default: <source>.tripartite.db)",
    )
    p.add_argument(
        "--lazy",
        action="store_true",
        help="Skip embedding and entity extraction (fast structural pass)",
    )
    p.add_argument(
        "--quiet", "-q",
        action="store_true",
        help="Suppress per-file progress output",
    )
    p.add_argument(
        "--info",
        action="store_true",
        help="Print statistics about an existing .db file and exit",
    )
    return p


def _resolve_output(source: Path, override: str | None) -> Path:
    if override:
        return Path(override)
    stem = source.stem if source.is_file() else source.name
    return source.parent / f"{stem}.tripartite.db"


def _print_db_info(db_path: Path) -> None:
    """Print statistics about an existing database."""
    import sqlite3

    if not db_path.exists():
        print(f"Error: {db_path} does not exist.", file=sys.stderr)
        sys.exit(1)

    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row

    def q(sql, *args):
        return conn.execute(sql, args).fetchone()[0]

    print(f"\n  Tripartite Knowledge Store: {db_path}")
    print(f"  File size     : {db_path.stat().st_size / 1_048_576:.1f} MB")
    print(f"  ─────────────────────────────────────────")
    print(f"  Source files  : {q('SELECT COUNT(*) FROM source_files')}")
    print(f"  Verbatim lines: {q('SELECT COUNT(*) FROM verbatim_lines')}")
    print(f"  Tree nodes    : {q('SELECT COUNT(*) FROM tree_nodes')}")
    print(f"  Chunks total  : {q('SELECT COUNT(*) FROM chunk_manifest')}")
    print(f"  Embedded      : {q(\"SELECT COUNT(*) FROM chunk_manifest WHERE embed_status='done'\")}")
    print(f"  Pending embed : {q(\"SELECT COUNT(*) FROM chunk_manifest WHERE embed_status='pending'\")}")
    print(f"  Graph nodes   : {q('SELECT COUNT(*) FROM graph_nodes')}")
    print(f"  Graph edges   : {q('SELECT COUNT(*) FROM graph_edges')}")
    print(f"  Ingest runs   : {q('SELECT COUNT(*) FROM ingest_runs')}")
    print()

    # Source type breakdown
    rows = conn.execute(
        "SELECT source_type, COUNT(*) as n FROM source_files GROUP BY source_type ORDER BY n DESC"
    ).fetchall()
    if rows:
        print("  Source types:")
        for r in rows:
            print(f"    {r['source_type']:<14} {r['n']} file(s)")

    # Chunk type breakdown
    rows = conn.execute(
        "SELECT chunk_type, COUNT(*) as n FROM chunk_manifest GROUP BY chunk_type ORDER BY n DESC LIMIT 10"
    ).fetchall()
    if rows:
        print("\n  Chunk types:")
        for r in rows:
            print(f"    {r['chunk_type']:<20} {r['n']}")

    conn.close()
    print()


def main():
    parser = _build_parser()
    args = parser.parse_args()

    # ── --info mode ────────────────────────────────────────────────────────
    if args.info:
        if not args.source:
            parser.error("--info requires a .db path as <source>")
        _print_db_info(Path(args.source))
        return

    # ── Ingest mode ────────────────────────────────────────────────────────
    if not args.source:
        parser.print_help()
        sys.exit(0)

    source = Path(args.source)
    if not source.exists():
        print(f"Error: '{source}' does not exist.", file=sys.stderr)
        sys.exit(1)

    db_path = _resolve_output(source, args.output)
    verbose = not args.quiet

    # Import here so startup is fast for --help / --info
    from .pipeline.ingest import ingest

    result = ingest(
        source_root=source,
        db_path=db_path,
        lazy=args.lazy,
        verbose=verbose,
    )

    sys.exit(0 if not result["errors"] else 1)


if __name__ == "__main__":
    main()
