import tkinter as tk
from tkinter import filedialog, messagebox
import os

def normalize_file():
    # 1. Pick the file
    file_path = filedialog.askopenfilename(
        title="Select Batch Script to Normalize",
        filetypes=[("Batch Files", "*.bat"), ("All Files", "*.*")]
    )
    
    if not file_path:
        return

    try:
        # 2. Read content (detecting encoding errors)
        with open(file_path, 'rb') as f:
            raw_data = f.read()

        # Remove UTF-8 BOM if it exists
        if raw_data.startswith(b'\xef\xbb\xbf'):
            raw_data = raw_data[3:]

        # Decode and normalize line endings
        content = raw_data.decode('utf-8', errors='ignore')
        normalized_content = content.replace('\r\n', '\n').replace('\n', '\r\n')

        # 3. Overwrite with clean UTF-8
        with open(file_path, 'w', encoding='utf-8', newline='') as f:
            f.write(normalized_content)

        messagebox.showinfo("Success", f"Normalized:\n{os.path.basename(file_path)}")
    
    except Exception as e:
        messagebox.showerror("Error", f"Failed to normalize: {str(e)}")

# Minimalistic UI Setup
root = tk.Tk()
root.title("Batch Normalizer")
root.geometry("300x150")

label = tk.Label(root, text="TripartiteDataSTORE\nFile Normalizer", pady=10)
label.pack()

btn = tk.Button(root, text="Select & Fix .bat File", command=normalize_file, bg="#2ecc71", fg="white")
btn.pack(expand=True)

root.mainloop()