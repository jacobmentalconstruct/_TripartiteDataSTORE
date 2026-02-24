"""
Tests for the Tripartite ingest pipeline — pure unittest, no pytest required.
Runs in lazy mode (no model download needed).
"""

import json
import sqlite3
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from tripartite.db.schema import open_db
from tripartite.pipeline.detect import detect, walk_source
from tripartite.pipeline.ingest import ingest
from tripartite.utils import cid, chunk_cid, estimate_tokens, split_lines


PYTHON_SRC = textwrap.dedent("""\
    \"\"\"Sample module for testing.\"\"\"
    import os
    import sys

    CONSTANT = 42


    def add(a, b):
        \"\"\"Return the sum of a and b.\"\"\"
        return a + b


    def multiply(x, y):
        \"\"\"Return the product.\"\"\"
        return x * y


    class Calculator:
        \"\"\"A simple calculator.\"\"\"

        def __init__(self, name):
            self.name = name
            self.history = []

        def compute(self, op, a, b):
            \"\"\"Perform an operation.\"\"\"
            if op == 'add':
                result = add(a, b)
            else:
                result = multiply(a, b)
            self.history.append(result)
            return result
""")

MARKDOWN_SRC = textwrap.dedent("""\
    # Project Overview

    This is the main README for the project.

    ## Installation

    Run the following command to install:

        pip install mypackage

    ## Usage

    Import and use the package as follows.

    ## Contributing

    Contributions are welcome. Please open a pull request.
""")

TEXT_SRC = textwrap.dedent("""\
    Project Notes

    This project builds a portable knowledge store.
    It combines three complementary memory layers.

    The verbatim layer stores exact content with CIDs.
    Each line gets a unique identifier based on its hash.

    The semantic layer stores vector embeddings for retrieval.
    Embeddings allow conceptual search beyond keyword matching.
""")


def _write_sample_dir(tmp: Path) -> dict[str, Path]:
    files = {}
    files["py"] = tmp / "sample.py"
    files["py"].write_text(PYTHON_SRC)
    files["md"] = tmp / "README.md"
    files["md"].write_text(MARKDOWN_SRC)
    files["txt"] = tmp / "notes.txt"
    files["txt"].write_text(TEXT_SRC)
    (tmp / ".hidden").write_text("skip me")
    (tmp / "image.png").write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 100)
    skip_dir = tmp / "__pycache__"
    skip_dir.mkdir()
    (skip_dir / "sample.pyc").write_bytes(b"\x00\x01")
    return files


class TestUtils(unittest.TestCase):
    def test_cid_stable(self):
        self.assertEqual(cid("hello world"), cid("hello world"))

    def test_cid_differs_on_content(self):
        self.assertNotEqual(cid("hello"), cid("world"))

    def test_cid_normalizes_trailing_whitespace(self):
        self.assertEqual(cid("hello   "), cid("hello"))

    def test_chunk_cid_format(self):
        self.assertTrue(chunk_cid("some text").startswith("cid:sha256:"))

    def test_estimate_tokens_small(self):
        self.assertLess(estimate_tokens("hello"), 10)

    def test_estimate_tokens_large(self):
        self.assertGreater(estimate_tokens("x" * 400), 50)

    def test_split_lines_crlf(self):
        self.assertEqual(split_lines("a\r\nb\r\nc"), ["a", "b", "c"])

    def test_split_lines_empty(self):
        self.assertEqual(split_lines(""), [])


class TestSchema(unittest.TestCase):
    def test_creates_all_tables(self):
        with tempfile.TemporaryDirectory() as d:
            conn = open_db(Path(d) / "test.db")
            tables = {r[0] for r in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()}
            required = {
                "verbatim_lines", "source_files", "tree_nodes",
                "chunk_manifest", "embeddings", "graph_nodes",
                "graph_edges", "diff_chain", "snapshots", "ingest_runs",
            }
            self.assertTrue(required.issubset(tables))
            conn.close()

    def test_open_db_idempotent(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "test.db"
            open_db(p).close()
            open_db(p).close()  # must not raise


class TestDetect(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)
        self.files = _write_sample_dir(self.tmp)

    def tearDown(self):
        self._tmp.cleanup()

    def test_detect_python_type(self):
        src = detect(self.files["py"])
        self.assertIsNotNone(src)
        self.assertEqual(src.source_type, "code")
        self.assertEqual(src.language, "python")

    def test_detect_markdown_type(self):
        src = detect(self.files["md"])
        self.assertIsNotNone(src)
        self.assertEqual(src.source_type, "prose")
        self.assertEqual(src.language, "markdown")

    def test_walk_skips_binary(self):
        names = [p.name for p in walk_source(self.tmp)]
        self.assertNotIn("image.png", names)

    def test_walk_skips_hidden(self):
        names = [p.name for p in walk_source(self.tmp)]
        self.assertNotIn(".hidden", names)

    def test_walk_skips_pycache(self):
        paths = list(walk_source(self.tmp))
        self.assertFalse(any("__pycache__" in str(p) for p in paths))

    def test_walk_finds_all_text_files(self):
        names = [p.name for p in walk_source(self.tmp)]
        for fname in ("sample.py", "README.md", "notes.txt"):
            self.assertIn(fname, names)


class TestPythonChunker(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        p = Path(self._tmp.name) / "sample.py"
        p.write_text(PYTHON_SRC)
        self.source = detect(p)

    def tearDown(self):
        self._tmp.cleanup()

    def test_produces_multiple_chunks(self):
        from tripartite.chunkers.code import PythonChunker
        chunks = PythonChunker().chunk(self.source)
        self.assertGreater(len(chunks), 2)

    def test_has_function_def_chunks(self):
        from tripartite.chunkers.code import PythonChunker
        types = {c.chunk_type for c in PythonChunker().chunk(self.source)}
        self.assertIn("function_def", types)

    def test_all_chunks_have_text(self):
        from tripartite.chunkers.code import PythonChunker
        for chunk in PythonChunker().chunk(self.source):
            self.assertTrue(chunk.text.strip(), f"Empty chunk: {chunk.name}")

    def test_sibling_links_wired(self):
        from tripartite.chunkers.code import PythonChunker
        chunks = PythonChunker().chunk(self.source)
        self.assertTrue(any(c.next_chunk_idx is not None for c in chunks))


class TestProseChunker(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def test_markdown_split_on_headings(self):
        from tripartite.chunkers.prose import ProseChunker
        p = self.tmp / "README.md"
        p.write_text(MARKDOWN_SRC)
        chunks = ProseChunker().chunk(detect(p))
        self.assertGreater(len(chunks), 2)

    def test_first_chunk_is_summary(self):
        from tripartite.chunkers.prose import ProseChunker
        p = self.tmp / "README.md"
        p.write_text(MARKDOWN_SRC)
        chunks = ProseChunker().chunk(detect(p))
        self.assertEqual(chunks[0].chunk_type, "document_summary")

    def test_plain_text_splits_on_paragraphs(self):
        from tripartite.chunkers.prose import ProseChunker
        p = self.tmp / "notes.txt"
        p.write_text(TEXT_SRC)
        chunks = ProseChunker().chunk(detect(p))
        self.assertGreater(len(chunks), 1)


class TestIngestLazy(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)
        self.files = _write_sample_dir(self.tmp)
        self.db = self.tmp / "out.db"

    def tearDown(self):
        self._tmp.cleanup()

    def _q(self, sql, *args):
        conn = sqlite3.connect(str(self.db))
        result = conn.execute(sql, args).fetchone()[0]
        conn.close()
        return result

    def test_single_python_file_processed(self):
        r = ingest(self.files["py"], self.db, lazy=True, verbose=False)
        self.assertEqual(r["files_processed"], 1)
        self.assertGreater(r["chunks_created"], 0)
        self.assertFalse(r["errors"])

    def test_single_markdown_file_processed(self):
        r = ingest(self.files["md"], self.db, lazy=True, verbose=False)
        self.assertEqual(r["files_processed"], 1)
        self.assertGreater(r["chunks_created"], 0)

    def test_folder_ingest_finds_all_files(self):
        r = ingest(self.tmp, self.db, lazy=True, verbose=False)
        self.assertGreaterEqual(r["files_processed"], 3)
        self.assertFalse(r["errors"])

    def test_verbatim_layer_populated(self):
        ingest(self.files["py"], self.db, lazy=True, verbose=False)
        self.assertGreater(self._q("SELECT COUNT(*) FROM verbatim_lines"), 0)

    def test_source_file_record_written(self):
        ingest(self.files["py"], self.db, lazy=True, verbose=False)
        self.assertEqual(self._q("SELECT COUNT(*) FROM source_files"), 1)

    def test_tree_nodes_written(self):
        ingest(self.files["py"], self.db, lazy=True, verbose=False)
        self.assertGreater(self._q("SELECT COUNT(*) FROM tree_nodes"), 0)

    def test_chunk_manifest_written(self):
        ingest(self.files["py"], self.db, lazy=True, verbose=False)
        self.assertGreater(self._q("SELECT COUNT(*) FROM chunk_manifest"), 0)

    def test_graph_edges_written(self):
        ingest(self.files["py"], self.db, lazy=True, verbose=False)
        self.assertGreater(self._q("SELECT COUNT(*) FROM graph_edges"), 0)

    def test_chunk_ids_are_cids(self):
        ingest(self.files["py"], self.db, lazy=True, verbose=False)
        conn = sqlite3.connect(str(self.db))
        rows = conn.execute("SELECT chunk_id FROM chunk_manifest").fetchall()
        conn.close()
        for (cid_val,) in rows:
            self.assertTrue(cid_val.startswith("cid:sha256:"), cid_val)

    def test_spans_are_valid_json(self):
        ingest(self.files["py"], self.db, lazy=True, verbose=False)
        conn = sqlite3.connect(str(self.db))
        rows = conn.execute("SELECT spans FROM chunk_manifest").fetchall()
        conn.close()
        for (spans_json,) in rows:
            spans = json.loads(spans_json)
            self.assertIsInstance(spans, list)
            self.assertGreater(len(spans), 0)
            self.assertIn("source_cid", spans[0])

    def test_verbatim_deduplication(self):
        """Re-ingesting the same file must not duplicate verbatim lines."""
        ingest(self.files["py"], self.db, lazy=True, verbose=False)
        before = self._q("SELECT COUNT(*) FROM verbatim_lines")
        ingest(self.files["py"], self.db, lazy=True, verbose=False)
        after = self._q("SELECT COUNT(*) FROM verbatim_lines")
        self.assertEqual(before, after)

    def test_ingest_run_recorded(self):
        r = ingest(self.files["py"], self.db, lazy=True, verbose=False)
        conn = sqlite3.connect(str(self.db))
        run = conn.execute(
            "SELECT status FROM ingest_runs WHERE run_id = ?", (r["run_id"],)
        ).fetchone()
        conn.close()
        self.assertIsNotNone(run)
        self.assertIn(run[0], ("done", "done_with_errors"))

    def test_context_prefix_non_empty(self):
        ingest(self.files["py"], self.db, lazy=True, verbose=False)
        conn = sqlite3.connect(str(self.db))
        rows = conn.execute("SELECT context_prefix FROM chunk_manifest").fetchall()
        conn.close()
        self.assertTrue(any(r[0] for r in rows))


if __name__ == "__main__":
    unittest.main(verbosity=2)
