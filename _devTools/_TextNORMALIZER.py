import tkinter as tk
from tkinter import filedialog, messagebox, scrolledtext
import os

class TripartiteNormalizer:
    def __init__(self, root):
        self.root = root
        self.root.title("Tripartite File Utility")
        self.root.geometry("500x450")

        # --- UI Layout ---
        tk.Label(root, text="Target File:", font=('Arial', 10, 'bold')).pack(pady=(10, 0))
        self.file_label = tk.Label(root, text="No file selected", fg="gray")
        self.file_label.pack()

        tk.Button(root, text="Select File", command=self.select_file).pack(pady=5)

        tk.Frame(root, height=2, bd=1, relief=tk.SUNKEN).pack(fill=tk.X, padx=20, pady=10)

        # Search & Replace Fields
        tk.Label(root, text="Search For:").pack()
        self.search_entry = tk.Entry(root, width=50)
        self.search_entry.pack(pady=2)

        tk.Label(root, text="Replace With:").pack()
        self.replace_entry = tk.Entry(root, width=50)
        self.replace_entry.pack(pady=2)

        # Action Buttons
        btn_frame = tk.Frame(root)
        btn_frame.pack(pady=15)
        
        tk.Button(btn_frame, text="Dry Run (Preview)", command=self.dry_run, bg="#3498db", fg="white").pack(side=tk.LEFT, padx=5)
        tk.Button(btn_frame, text="Normalize & Apply", command=self.apply_changes, bg="#2ecc71", fg="white").pack(side=tk.LEFT, padx=5)

        # Preview Area
        tk.Label(root, text="Status/Preview:").pack()
        self.log = scrolledtext.ScrolledText(root, height=8, width=55, font=('Consolas', 9))
        self.log.pack(padx=10, pady=5)

        self.current_file = None

    def select_file(self):
        self.current_file = filedialog.askopenfilename(filetypes=[("All Files", "*.*")])
        if self.current_file:
            self.file_label.config(text=os.path.basename(self.current_file), fg="black")
            self.log.insert(tk.END, f"Selected: {self.current_file}\n")

    def process_content(self):
        if not self.current_file:
            messagebox.showwarning("Warning", "Select a file first!")
            return None, None

        with open(self.current_file, 'rb') as f:
            raw = f.read()

        # Strip BOM if exists
        if raw.startswith(b'\xef\xbb\xbf'):
            raw = raw[3:]

        content = raw.decode('utf-8', errors='ignore')
        
        # Apply Search & Replace
        search_term = self.search_entry.get()
        replace_term = self.replace_entry.get()
        
        if search_term:
            new_content = content.replace(search_term, replace_term)
        else:
            new_content = content

        # Normalize Line Endings to Windows CRLF
        new_content = new_content.replace('\r\n', '\n').replace('\n', '\r\n')
        return content, new_content

    def dry_run(self):
        old, new = self.process_content()
        if old is not None:
            if old == new:
                self.log.insert(tk.END, "> No changes detected (Encoding only).\n")
            else:
                self.log.insert(tk.END, f"> Found matches. Previewing update...\n")
                # Show a snippet of changes
                self.log.insert(tk.END, f"  Searching for: '{self.search_entry.get()}'\n")

    def apply_changes(self):
        old, new = self.process_content()
        if new is not None:
            with open(self.current_file, 'w', encoding='utf-8', newline='') as f:
                f.write(new)
            messagebox.showinfo("Success", "File normalized and saved as clean UTF-8.")
            self.log.insert(tk.END, ">>> Saved successfully.\n")

if __name__ == "__main__":
    root = tk.Tk()
    app = TripartiteNormalizer(root)
    root.mainloop()