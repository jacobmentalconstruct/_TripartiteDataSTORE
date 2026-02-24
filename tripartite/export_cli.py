#!/usr/bin/env python3
"""
tripartite/export_cli.py

Standalone CLI tool for exporting Tripartite databases.

Usage:
    python -m tripartite.export_cli store.db output_dir --mode dump
    python -m tripartite.export_cli store.db output_dir --mode files
    python -m tripartite.export_cli store.db output_dir --mode both
"""

import argparse
import sys
from pathlib import Path

from . import export


def main():
    parser = argparse.ArgumentParser(
        description="Export Tripartite database to files or hierarchy dump",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Export Modes:
  dump   - Generate folder tree + file dump (like the input format)
  files  - Reconstruct original files and write to disk
  both   - Both dump and files

Examples:
  # Generate hierarchy dump
  python -m tripartite.export_cli my_store.db ./export --mode dump
  
  # Reconstruct original files
  python -m tripartite.export_cli my_store.db ./export --mode files
  
  # Do both
  python -m tripartite.export_cli my_store.db ./export --mode both
        """
    )
    
    parser.add_argument("db_path", type=str, help="Path to .db file")
    parser.add_argument("output_dir", type=str, help="Output directory")
    parser.add_argument("--mode", type=str, default="dump",
                       choices=["dump", "files", "both"],
                       help="Export mode (default: dump)")
    parser.add_argument("--prefix", type=str, default="export",
                       help="Prefix for dump files (default: export)")
    parser.add_argument("--quiet", action="store_true",
                       help="Suppress progress output")
    
    args = parser.parse_args()
    
    # Validate inputs
    db_path = Path(args.db_path)
    if not db_path.exists():
        print(f"Error: Database not found: {db_path}", file=sys.stderr)
        sys.exit(1)
    
    output_dir = Path(args.output_dir)
    
    # Show what we're doing
    if not args.quiet:
        print(f"[export] Database: {db_path}")
        print(f"[export] Output:   {output_dir}")
        print(f"[export] Mode:     {args.mode}")
        print()
    
    # Run export
    try:
        stats = export.export_all(
            db_path=db_path,
            output_dir=output_dir,
            mode=args.mode,
            verbose=not args.quiet
        )
        
        if not args.quiet:
            print()
            print("[export] ✓ Export complete!")
            
            if "dump" in stats:
                print(f"[export]   Tree: {stats['dump']['tree_path']}")
                print(f"[export]   Dump: {stats['dump']['dump_path']}")
            
            if "files" in stats:
                print(f"[export]   Files written: {stats['files']['files_written']}")
                print(f"[export]   Bytes written: {stats['files']['bytes_written']:,}")
                
                if stats['files']['errors']:
                    print(f"[export]   Errors: {len(stats['files']['errors'])}")
                    for err in stats['files']['errors'][:5]:  # Show first 5
                        print(f"[export]     - {err['file']}: {err['error']}")
    
    except Exception as e:
        print(f"[export] ✗ Export failed: {e}", file=sys.stderr)
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
