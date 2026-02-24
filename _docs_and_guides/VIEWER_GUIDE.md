# Tripartite Viewer - Installation & Usage Guide

## Files Generated

### Task 1 & 2 Fixes (Completed)
- `manager.py` → `tripartite/models/manager.py`
- `embed.py` → `tripartite/pipeline/embed.py`
- `settings_store.py` → `tripartite/settings_store.py`
- `settings_dialog.py` → `tripartite/settings_dialog.py`
- `gui.py` → `tripartite/gui.py`

### Task 3: Viewer App (New)
- `query.py` → `tripartite/db/query.py`
- `__init__.py` → `tripartite/db/__init__.py`
- `viewer.py` → `tripartite/viewer.py`

---

## Installation Steps

### 1. Copy Task 1 & 2 Fixed Files
Replace these files in your project with the updated versions:

```bash
cp manager.py tripartite/models/manager.py
cp embed.py tripartite/pipeline/embed.py
cp settings_store.py tripartite/settings_store.py
cp settings_dialog.py tripartite/settings_dialog.py
cp gui.py tripartite/gui.py
```

### 2. Install Task 3 Viewer Files
Create the new viewer module:

```bash
# Create the db package if it doesn't exist
mkdir -p tripartite/db

# Copy query module
cp query.py tripartite/db/query.py
cp __init__.py tripartite/db/__init__.py

# Copy viewer
cp viewer.py tripartite/viewer.py
```

---

## Usage

### Running the Ingest GUI
```bash
python -m tripartite.gui
```

**Changes in this version:**
- Lazy mode is now in Settings (⚙ button) under "Diagnostics"
- Settings are persistent across sessions
- Models reload automatically when changed in Settings
- Embedding failures are now logged (no silent failures)

### Running the Viewer
```bash
# Open with file picker
python -m tripartite.viewer

# Open specific database
python -m tripartite.viewer --db path/to/your/store.db
```

---

## Viewer Features

### Browse Panel (Left)
- **File Tree**: Shows all ingested source files
- **Chunks List**: Click a file to see its chunks
- **Detail View**: Click a chunk to see full text, metadata, and graph neighbors

**Metadata shown:**
- Chunk type, token count, line range
- Embedding status (✓ done, ○ pending, ✗ error)
- Context prefix (heading path)
- Entities mentioned in the chunk
- Related chunks (PRECEDES, FOLLOWS, RELATES_TO)

### Search Panel (Middle)
- **Hybrid Search**: Combines semantic (vector) + FTS (keyword) search
- **Automatic Fallback**: Uses FTS-only if embedder unavailable
- **Search Types**:
  - 🎯 Semantic (vector similarity)
  - 🔍 FTS (keyword match)
  - ⚡ Hybrid (both)
- **Results**: Shows score and context prefix
- **Detail View**: Click result to see full chunk

**How it works:**
1. Embedder loads lazily on first search
2. Query is embedded (if embedder available)
3. Cosine similarity computed against all chunk vectors
4. FTS runs in parallel against `fts_chunks`
5. Results merged and ranked by score

### Graph Panel (Right)
- **Entity List**: All entities extracted from the knowledge base
- **Type Filter**: Filter by entity type (PERSON, ORG, PRODUCT, TECH, LOCATION, CONCEPT)
- **Salience Scores**: Entities sorted by importance
- **Mentions**: Click entity to see which chunks mention it

**Entity data shown:**
- Label (entity text)
- Type (PERSON, ORG, etc.)
- Salience (0.0-1.0 importance score)
- List of chunks that mention the entity

### Status Bar (Bottom)
Shows database statistics:
- Total files ingested
- Total chunks created
- Total embeddings
- Total entities extracted

---

## Keyboard Shortcuts

- **Enter** in search box → Run search
- **Copy Text** button → Copy current chunk to clipboard

---

## Technical Details

### Text Reconstruction Path
The viewer correctly reconstructs chunk text following the schema:

```
chunk_manifest.spans (JSON)
  → [{source_cid: "...", line_start: N, line_end: M}, ...]
  → source_files.line_cids (JSON array of line_cid strings)
  → slice [line_start : line_end+1]
  → verbatim_lines WHERE line_cid IN (...)
  → JOIN .content with newlines
```

### Graph Neighbor Queries
For a chunk's graph node, finds:

1. **Entities**: 
   - `graph_edges WHERE edge_type='MENTIONS' → graph_nodes WHERE node_type='entity'`

2. **Related Chunks**:
   - `graph_edges WHERE edge_type IN ('PRECEDES', 'FOLLOWS', 'RELATES_TO') → chunk_manifest`

### Search Implementation

**FTS Search**: SQLite full-text search with snippet highlighting
```sql
SELECT snippet(fts_chunks, 1, '<mark>', '</mark>', '...', 32)
FROM fts_chunks WHERE fts_chunks MATCH ?
ORDER BY rank
```

**Semantic Search**: Vector cosine similarity
1. Embed query using nomic model
2. Fetch all vectors from `embeddings` table
3. Compute `cosine_similarity(query_vec, chunk_vec)` for each
4. Sort by score descending

**Hybrid Search**: Combines both, prefers semantic when available

---

## Error Handling

### Graceful Degradation
- **No embedder**: Semantic search disabled, FTS still works
- **Corrupt JSON**: Individual chunks skip gracefully
- **Missing data**: Shows "(no text)" / "(no context)" instead of crashing

### User Feedback
- Search status shows "FTS only" if embedder unavailable
- Console logs embedder load status
- Clear error messages in UI

---

## Performance Notes

### Large Databases
- Semantic search loads ALL vectors into memory (may be slow on huge DBs)
- Consider adding progress indicator if needed
- Results limited to top 20 by default

### Optimization Opportunities
- Cache reconstructed chunk text (currently rebuilds on each view)
- Index graph_edges for faster neighbor lookups
- Batch vector comparisons for semantic search

---

## Testing Checklist

Using your 4-file populated .db:

### Browse Panel
- [ ] Files appear in tree
- [ ] Click file → chunks populate
- [ ] Click chunk → text reconstructs correctly
- [ ] Metadata shows: type, tokens, lines, embed status
- [ ] Entities section shows mentioned entities
- [ ] Related chunks section shows neighbors

### Search Panel
- [ ] Enter query → results appear
- [ ] Status shows "semantic + FTS" or "FTS only"
- [ ] Click result → chunk detail loads
- [ ] Scores are reasonable (0.0-1.0)
- [ ] Snippet highlighting works

### Graph Panel
- [ ] Entities populate on startup
- [ ] Filter by type works
- [ ] Click entity → chunks appear
- [ ] Entity detail shows label, type, salience

### General
- [ ] Status bar shows correct counts
- [ ] Copy text button works
- [ ] WM_DELETE_WINDOW closes gracefully
- [ ] No crashes on missing data

---

## Troubleshooting

### "No module named 'tripartite.db'"
Make sure `tripartite/db/__init__.py` exists (even if empty)

### "Embedder failed to load"
Check that llama-cpp-python is installed and models are cached.
Viewer will fall back to FTS-only search.

### "Chunk text is empty"
Verify the `spans` JSON in `chunk_manifest` is valid.
Check that `source_files.line_cids` contains the expected line_cid values.

### "Search returns no results"
- FTS: Check that `fts_chunks` was populated during ingest
- Semantic: Verify embeddings exist in `embeddings` table
- Try simpler query terms

---

## Next Steps / Future Enhancements

### Performance
- Add progress bar for semantic search on large DBs
- Cache reconstructed chunk text
- Batch vector operations

### Features
- Export search results to file
- Bookmark/favorite chunks
- Graph visualization (entity relationship network)
- Chunk similarity explorer
- Timeline view for temporal entities

### UI Polish
- Dark/light theme toggle
- Configurable result limits
- Advanced search filters (by file, by type, by date)
- Keyboard navigation
- Search history

---

## Summary

All three tasks are complete:

✅ **Task 1**: Model reload bug fixed in `manager.py`
✅ **Task 2**: Lazy mode moved to Settings dialog  
✅ **Task 3**: Full viewer/query app with Browse, Search, and Graph panels

The viewer provides a complete interface for exploring your Tripartite knowledge store with:
- File/chunk browsing
- Hybrid semantic + FTS search
- Entity-based graph navigation
- Graceful degradation when embedder unavailable
- Dark theme matching the ingest GUI
