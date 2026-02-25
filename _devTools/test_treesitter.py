"""
Test script for tree-sitter integration in Tripartite.

This script creates sample files in multiple languages, runs the tree-sitter
chunker on them, and verifies the output chunks are correct.

Run with: python test_treesitter_integration.py
"""

import tempfile
from pathlib import Path
import sys

# Sample code in different languages
SAMPLE_FILES = {
    "main.py": '''
"""Main module docstring."""

import os
import sys
from typing import List

class DataProcessor:
    """Process data efficiently."""
    
    def __init__(self, name: str):
        self.name = name
        self.data = []
    
    def process(self, items: List[str]) -> int:
        """Process items and return count."""
        self.data.extend(items)
        return len(self.data)
    
    def clear(self):
        """Clear all data."""
        self.data = []

def validate_input(text: str) -> bool:
    """Validate input text."""
    return len(text) > 0 and text.strip() != ""

if __name__ == "__main__":
    processor = DataProcessor("test")
    print(processor.process(["a", "b", "c"]))
''',

    "utils.js": '''
/**
 * Utility functions for the application.
 */

import { format } from './formatter.js';
import * as validators from './validators.js';

export class UserManager {
    constructor(config) {
        this.users = [];
        this.config = config;
    }
    
    addUser(name, email) {
        const user = { name, email };
        this.users.push(user);
        return user;
    }
    
    findUser(email) {
        return this.users.find(u => u.email === email);
    }
    
    removeUser(email) {
        this.users = this.users.filter(u => u.email !== email);
    }
}

export function validateEmail(email) {
    return email.includes('@') && email.includes('.');
}

export const normalizeString = (str) => {
    return str.trim().toLowerCase();
};
''',

    "server.go": '''
package main

import (
    "fmt"
    "net/http"
    "log"
)

type Server struct {
    port int
    handler http.Handler
}

func NewServer(port int) *Server {
    return &Server{
        port: port,
        handler: http.DefaultServeMux,
    }
}

func (s *Server) Start() error {
    addr := fmt.Sprintf(":%d", s.port)
    log.Printf("Starting server on %s", addr)
    return http.ListenAndServe(addr, s.handler)
}

func (s *Server) Stop() {
    log.Println("Stopping server")
}

func handleRequest(w http.ResponseWriter, r *http.Request) {
    fmt.Fprintf(w, "Hello, World!")
}

func main() {
    server := NewServer(8080)
    http.HandleFunc("/", handleRequest)
    server.Start()
}
''',

    "model.rs": '''
//! Data models for the application.

use serde::{Deserialize, Serialize};
use std::collections::HashMap;

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct User {
    pub id: u64,
    pub name: String,
    pub email: String,
}

impl User {
    pub fn new(id: u64, name: String, email: String) -> Self {
        User { id, name, email }
    }
    
    pub fn is_valid(&self) -> bool {
        !self.name.is_empty() && self.email.contains('@')
    }
}

#[derive(Debug, Default)]
pub struct UserStore {
    users: HashMap<u64, User>,
}

impl UserStore {
    pub fn new() -> Self {
        UserStore {
            users: HashMap::new(),
        }
    }
    
    pub fn add_user(&mut self, user: User) {
        self.users.insert(user.id, user);
    }
    
    pub fn get_user(&self, id: u64) -> Option<&User> {
        self.users.get(&id)
    }
}

pub fn validate_email(email: &str) -> bool {
    email.contains('@') && email.contains('.')
}
''',
}


def test_treesitter_chunker():
    """Test tree-sitter chunker with sample files."""
    print("=" * 70)
    print("Tree-Sitter Integration Test")
    print("=" * 70)
    
    # Check if tree-sitter is available
    try:
        import tree_sitter_language_pack
        print("✓ tree-sitter-language-pack installed")
    except ImportError:
        print("✗ tree-sitter-language-pack NOT installed")
        print("\nInstall with: pip install tree-sitter tree-sitter-language-pack")
        return False
    
    # Try to import the treesitter chunker
    try:
        # Add project root to path (works from tests/ subdirectory)
        project_root = Path(__file__).parent.parent
        if project_root not in sys.path:
            sys.path.insert(0, str(project_root))
        
        # Use absolute imports (no dots)
        from tripartite.chunkers.treesitter import (
            TreeSitterChunker, 
            get_treesitter_chunker,
            EXTENSION_TO_LANGUAGE
        )
        from tripartite.pipeline.detect import detect
        print("✓ TreeSitterChunker imported successfully")
    except ImportError as e:
        print(f"✗ Failed to import TreeSitterChunker: {e}")
        print("\nMake sure treesitter.py is in tripartite/chunkers/")
        return False
    
    print(f"\n✓ Supports {len(EXTENSION_TO_LANGUAGE)} languages")
    print("\nTesting language support:")
    
    results = {}
    
    # Create temp directory for test files
    with tempfile.TemporaryDirectory() as tmpdir:
        tmpdir = Path(tmpdir)
        
        for filename, code in SAMPLE_FILES.items():
            print(f"\n{'-' * 70}")
            print(f"Testing: {filename}")
            print(f"{'-' * 70}")
            
            # Write test file
            test_file = tmpdir / filename
            test_file.write_text(code)
            
            # Detect source
            source = detect(test_file)
            if not source:
                print(f"  ✗ Failed to detect {filename}")
                results[filename] = {"status": "detection_failed"}
                continue
            
            print(f"  Source type: {source.source_type}")
            print(f"  Language: {source.language}")
            
            # Get chunker
            chunker = get_treesitter_chunker(source)
            if not chunker:
                print(f"  ⚠ Tree-sitter not available for {source.language}")
                results[filename] = {"status": "unsupported"}
                continue
            
            # Chunk the file
            try:
                chunks = chunker.chunk(source)
                print(f"  ✓ Generated {len(chunks)} chunks")
                
                results[filename] = {
                    "status": "success",
                    "chunks": len(chunks),
                    "types": {}
                }
                
                # Display chunk details
                for i, chunk in enumerate(chunks, 1):
                    chunk_type = chunk.chunk_type
                    results[filename]["types"][chunk_type] = \
                        results[filename]["types"].get(chunk_type, 0) + 1
                    
                    lines = f"L{chunk.line_start+1}-{chunk.line_end+1}"
                    context = " > ".join(chunk.heading_path)
                    print(f"    {i}. [{chunk_type:15s}] {context:40s} {lines}")
                
            except Exception as e:
                print(f"  ✗ Chunking failed: {e}")
                import traceback
                traceback.print_exc()
                results[filename] = {"status": "error", "error": str(e)}
    
    # Print summary
    print("\n" + "=" * 70)
    print("Test Summary")
    print("=" * 70)
    
    success_count = sum(1 for r in results.values() if r["status"] == "success")
    total_count = len(results)
    
    print(f"\nFiles tested: {total_count}")
    print(f"Successful: {success_count}")
    print(f"Failed: {total_count - success_count}")
    
    for filename, result in results.items():
        status = result["status"]
        if status == "success":
            chunk_count = result["chunks"]
            types = ", ".join(f"{k}={v}" for k, v in result["types"].items())
            print(f"  ✓ {filename:20s} → {chunk_count} chunks ({types})")
        else:
            print(f"  ✗ {filename:20s} → {status}")
    
    return success_count == total_count


if __name__ == "__main__":
    success = test_treesitter_chunker()
    sys.exit(0 if success else 1)