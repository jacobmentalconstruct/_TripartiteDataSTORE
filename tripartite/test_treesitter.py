# test_treesitter.py
from pathlib import Path
from tripartite.pipeline.detect import detect
from tripartite.chunkers.treesitter import get_treesitter_chunker

# Test JavaScript
js_code = '''
class UserManager {
    constructor() {
        this.users = [];
    }
    
    addUser(name, email) {
        this.users.push({name, email});
    }
    
    getUser(name) {
        return this.users.find(u => u.name === name);
    }
}

function validateEmail(email) {
    return email.includes('@');
}
'''

# Create a temp JS file
test_file = Path("test.js")
test_file.write_text(js_code)

# Detect and chunk
source = detect(test_file)
if source:
    chunker = get_treesitter_chunker(source)
    if chunker:
        chunks = chunker.chunk(source)
        
        print(f"Found {len(chunks)} chunks:")
        for i, chunk in enumerate(chunks):
            print(f"{i+1}. {chunk.chunk_type}: {chunk.name} (lines {chunk.line_start}-{chunk.line_end})")
    else:
        print("Tree-sitter not available")

# Cleanup
test_file.unlink()