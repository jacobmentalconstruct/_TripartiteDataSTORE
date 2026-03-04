import tkinter as tk
from tkinter import messagebox, filedialog
import os

# --- THEME ---
BG = "#1e1e1e"
FG = "#d4d4d4"
ACCENT = "#007acc"
BORDER = "#3c3c3c"

# --- SEMANTIC CHUNKS FOR DATASTORE.PY ---
# These are the "Anchor Lines" where the file should be cut.
SEMANTIC_HUNKS = [
    "class TreeItem:",                       # Data Models
    "class BaseCurationTool(ABC):",          # Tool Interface
    "class ViewerPanel(tk.Frame):",          # Viewer Component
    "class ViewerStack(tk.Frame):",          # Viewer Stack
    "class TripartiteDataStore:",            # Main App Start
    "def _build_workspace(self):",           # Tab Layouts
    "def _patch_validate(self):",            # Patching Logic
    "def _run_ingest(self, source_path: str):", # Ingest Engine
    "def _query_semantic_layer(self, query: str, top_k: int):" # Search Engine
]

class SemanticSplitter:
    def __init__(self, root):
        self.root = root
        self.root.title("Semantic Hunk Splitter")
        self.root.geometry("500x400")
        self.root.configure(bg=BG)
        self.target_file = None
        self._build_ui()

    def _build_ui(self):
        tk.Label(self.root, text="SEMANTIC HUNK SPLITTER", bg=BG, fg=ACCENT, 
                 font=("Segoe UI Semibold", 12)).pack(pady=20)

        self.file_label = tk.Label(self.root, text="No file selected", bg=BG, fg=FG)
        self.file_label.pack(pady=10)

        tk.Button(self.root, text="SELECT DATASTORE.PY", command=self._browse, 
                  bg="#333", fg=FG, relief="flat").pack(pady=5)

        # Show the hunks we are looking for
        hunk_box = tk.Text(self.root, bg="#111", fg="#858585", font=("Consolas", 8), height=10)
        hunk_box.pack(padx=20, pady=10, fill="both")
        hunk_box.insert("1.0", "Split Anchors:\n" + "\n".join(SEMANTIC_HUNKS))
        hunk_box.configure(state="disabled")

        tk.Button(self.root, text="EXECUTE SEMANTIC SPLIT", command=self._execute_split,
                  bg=ACCENT, fg="white", font=("Segoe UI", 10, "bold")).pack(pady=20)

    def _browse(self):
        path = filedialog.askopenfilename()
        if path:
            self.target_file = path
            self.file_label.configure(text=os.path.basename(path))

    def _execute_split(self):
        if not self.target_file: return
        
        with open(self.target_file, 'r', encoding='utf-8', errors='ignore') as f:
            lines = f.readlines()

        split_indices = [0]
        for hunk in SEMANTIC_HUNKS:
            # Find the line that matches the hunk exactly (ignoring leading whitespace)
            matches = [i for i, line in enumerate(lines) if line.strip().startswith(hunk)]
            
            if len(matches) == 1:
                split_indices.append(matches[0])
            elif len(matches) > 1:
                print(f"Ambiguous hunk: '{hunk}' found {len(matches)} times. Skipping.")
        
        split_indices.append(len(lines))
        split_indices = sorted(list(set(split_indices)))

        file_dir, file_name = os.path.split(self.target_file)
        name_part, ext_part = os.path.splitext(file_name)

        for i in range(len(split_indices) - 1):
            start = split_indices[i]
            end = split_indices[i+1]
            chunk_lines = lines[start:end]
            
            output_name = f"{name_part}_hunk_{i:02d}{ext_part}"
            with open(os.path.join(file_dir, output_name), 'w', encoding='utf-8') as out_f:
                out_f.writelines(chunk_lines)

        messagebox.showinfo("Success", f"Split into {len(split_indices)-1} semantic parts.")

if __name__ == "__main__":
    root = tk.Tk()
    SemanticSplitter(root)
    root.mainloop()