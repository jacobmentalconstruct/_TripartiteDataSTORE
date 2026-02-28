import os
import sys
import subprocess
import shutil
import urllib.request
import urllib.error
import tkinter as tk
from tkinter import messagebox, ttk
import stat

# --- 1. THE PAYLOADS ---
REQUIREMENTS_TEXT = """fastapi==0.110.0
uvicorn==0.29.0
pydantic==2.6.4
llama-cpp-python==0.2.56
requests==2.31.0
"""

WRAPPER_TEXT = """from fastapi import FastAPI
from pydantic import BaseModel
from llama_cpp import Llama
import os
import json
from contextlib import asynccontextmanager

NODE_NAME = os.getenv("NODE_NAME", "unknown_node")
PORT = os.getenv("PORT", "8080")
# The registry lives one folder up (alongside the installer)
REGISTRY_FILE = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "swarm_registry.json"))

def update_registry(add=True):
    registry = {}
    if os.path.exists(REGISTRY_FILE):
        try:
            with open(REGISTRY_FILE, "r") as f:
                registry = json.load(f)
        except Exception:
            pass
    
    node_key = f"{NODE_NAME}_{PORT}"
    if add:
        registry[node_key] = {
            "name": NODE_NAME,
            "port": PORT,
            "url": f"http://127.0.0.1:{PORT}/generate"
        }
    else:
        if node_key in registry:
            del registry[node_key]
            
    with open(REGISTRY_FILE, "w") as f:
        json.dump(registry, f, indent=4)

@asynccontextmanager
async def lifespan(app: FastAPI):
    # On Startup: Register node
    update_registry(add=True)
    yield
    # On Shutdown: Unregister node
    update_registry(add=False)

app = FastAPI(lifespan=lifespan)
MODEL_PATH = os.getenv("MODEL_PATH", "./models/model.gguf")

print(f"\\n[SWARM NODE] Booting '{NODE_NAME}' from: {MODEL_PATH}")
llm = Llama(model_path=MODEL_PATH, n_ctx=2048, n_threads=2, use_mmap=True)

class QueryRequest(BaseModel):
    prompt: str

@app.post("/generate")
def generate(request: QueryRequest):
    response = llm.create_chat_completion(
        messages=[{"role": "user", "content": request.prompt}],
        max_tokens=128
    )
    return {"result": response["choices"]["message"]["content"]}
"""

RUN_BAT_TEXT = """@echo off
set PORT=%1
if "%PORT%"=="" set PORT=8080

set NODE_NAME={NODE_NAME}
set PORT=%PORT%

echo [SWARM NODE] Starting %NODE_NAME% on port %PORT%...
cd /d "%~dp0"
call .venv\\Scripts\\activate.bat

uvicorn wrapper:app --host 0.0.0.0 --port %PORT%
pause
"""

RUN_SH_TEXT = """#!/bin/bash
PORT=${1:-8080}

export PORT=$PORT
export NODE_NAME="{NODE_NAME}"

echo "[SWARM NODE] Starting $NODE_NAME on port $PORT..."
cd "$(dirname "$0")"
source .venv/bin/activate

uvicorn wrapper:app --host 0.0.0.0 --port $PORT
"""

KILL_SCRIPT_TEXT = """import os
import sys
import subprocess

port = sys.argv if len(sys.argv) > 1 else "8080"
print(f"Hunting for processes holding port {port}...")

try:
    if os.name == 'nt':
        # Windows
        output = subprocess.check_output(f"netstat -ano | findstr :{port}", shell=True, text=True)
        pids = set()
        for line in output.splitlines():
            if f":{port}" in line and "LISTENING" in line:
                parts = line.strip().split()
                if parts:
                    pids.add(parts[-1])
        if not pids:
            print(f"No listening process found on port {port}.")
            sys.exit(0)
        for pid in pids:
            if pid == "0": continue
            print(f"Killing PID {pid}...")
            subprocess.call(f"taskkill /PID {pid} /F", shell=True)
    else:
        # Unix/Mac
        output = subprocess.check_output(f"lsof -t -i:{port}", shell=True, text=True)
        pids = set(output.strip().splitlines())
        if not pids:
            print(f"No listening process found on port {port}.")
            sys.exit(0)
        for pid in pids:
            print(f"Killing PID {pid}...")
            subprocess.call(f"kill -9 {pid}", shell=True)
            
    print(f"Successfully cleared port {port}!")
except subprocess.CalledProcessError:
    print(f"No active processes found holding port {port}.")
except Exception as e:
    print(f"Error occurred: {e}")
"""

CHAT_UI_TEXT = """import tkinter as tk
from tkinter import ttk, scrolledtext, messagebox
import requests
import threading
import json
import os

# _ProjectMAPPER Theme Colors
BG_COLOR = "#1E1E1E"
FG_COLOR = "#D4D4D4"
BTN_COLOR = "#007ACC"
USER_COLOR = "#569CD6" # Blue
BOT_COLOR = "#4EC9B0"  # Teal/Green
ERR_COLOR = "#F44747"  # Red

REGISTRY_FILE = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "swarm_registry.json"))

class SwarmChatUI:
    def __init__(self, root):
        self.root = root
        self.root.title("Swarm Node Chat UI")
        self.root.geometry("650x500")
        self.root.configure(bg=BG_COLOR)
        
        self.registry_data = {}

        # Top Bar: Registry Selector
        top_frame = tk.Frame(root, bg=BG_COLOR, pady=10)
        top_frame.pack(fill=tk.X, padx=10)
        
        lbl = tk.Label(top_frame, text="Active Swarm Node:", bg=BG_COLOR, fg=FG_COLOR, font=("Helvetica", 10, "bold"))
        lbl.pack(side=tk.LEFT, padx=(0, 5))
        
        self.node_var = tk.StringVar()
        self.node_selector = ttk.Combobox(top_frame, textvariable=self.node_var, state="readonly", width=45)
        self.node_selector.pack(side=tk.LEFT)
        
        refresh_btn = tk.Button(top_frame, text="Refresh Registry", command=self.load_registry, bg="#333333", fg="white", relief=tk.FLAT)
        refresh_btn.pack(side=tk.LEFT, padx=10)

        # Middle: Chat History
        self.chat_display = scrolledtext.ScrolledText(root, wrap=tk.WORD, state='disabled', bg="#252526", fg=FG_COLOR, font=("Consolas", 10), insertbackground=FG_COLOR, relief=tk.FLAT)
        self.chat_display.pack(fill=tk.BOTH, expand=True, padx=10, pady=(0, 10))
        
        self.chat_display.tag_config("user", foreground=USER_COLOR, font=("Consolas", 10, "bold"))
        self.chat_display.tag_config("bot", foreground=BOT_COLOR, font=("Consolas", 10, "bold"))
        self.chat_display.tag_config("err", foreground=ERR_COLOR, font=("Consolas", 10, "bold"))

        # Bottom: Input Area
        bottom_frame = tk.Frame(root, bg=BG_COLOR)
        bottom_frame.pack(fill=tk.X, padx=10, pady=(0, 10))
        
        self.input_box = tk.Entry(bottom_frame, bg="#2D2D2D", fg=FG_COLOR, insertbackground=FG_COLOR, font=("Consolas", 11), relief=tk.FLAT)
        self.input_box.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 10), ipady=5)
        self.input_box.bind("<Return>", lambda event: self.send_message())
        
        self.send_btn = tk.Button(bottom_frame, text="Send", command=self.send_message, bg=BTN_COLOR, fg="white", activebackground="#005A9E", activeforeground="white", relief=tk.FLAT, font=("Helvetica", 10, "bold"))
        self.send_btn.pack(side=tk.RIGHT, ipadx=10, ipady=2)

        self.load_registry()
        self.append_to_chat("System", "Ready. Select an active node from the dropdown.", "bot")

    def load_registry(self):
        self.registry_data = {}
        if os.path.exists(REGISTRY_FILE):
            try:
                with open(REGISTRY_FILE, "r") as f:
                    self.registry_data = json.load(f)
            except Exception:
                pass
                
        options = []
        for key, data in self.registry_data.items():
            options.append(f"{data['name']} (Port {data['port']}) - {data['url']}")
            
        if options:
            self.node_selector['values'] = options
            self.node_selector.current(0)
        else:
            self.node_selector['values'] = ["-- No active nodes found in registry --"]
            self.node_selector.current(0)

    def append_to_chat(self, sender, message, tag):
        self.chat_display.config(state='normal')
        self.chat_display.insert(tk.END, f"[{sender}]\\n", tag)
        self.chat_display.insert(tk.END, f"{message}\\n\\n")
        self.chat_display.config(state='disabled')
        self.chat_display.yview(tk.END)

    def send_message(self):
        prompt = self.input_box.get().strip()
        selection = self.node_var.get()
        
        if not prompt: return
        if "-- No active nodes" in selection:
            self.append_to_chat("System Error", "Please start a node server and refresh.", "err")
            return
            
        target_url = selection.split(" - ")[-1]
        
        self.input_box.delete(0, tk.END)
        self.append_to_chat("You", prompt, "user")

        threading.Thread(target=self.fetch_response, args=(target_url, prompt, selection), daemon=True).start()

    def fetch_response(self, url, prompt, selection):
        self.send_btn.config(state="disabled", bg="#555555")
        try:
            response = requests.post(url, json={"prompt": prompt})
            result_text = response.json().get("result", "Error: No result field.")
            self.root.after(0, self.append_to_chat, "Model", result_text, "bot")
        except Exception as e:
            self.root.after(0, self.handle_bad_connection, url, selection, e)
        finally:
            self.root.after(0, lambda: self.send_btn.config(state="normal", bg=BTN_COLOR))
            
    def handle_bad_connection(self, url, selection, error):
        self.append_to_chat("System Error", f"Connection failed to {url}. Was the node improperly closed?", "err")
        ans = messagebox.askyesno("Dead Node Detected", f"Could not connect to this node.\\n\\nDo you want to unregister it to clean up the list?")
        if ans:
            # Find key to delete
            key_to_delete = None
            for k, v in self.registry_data.items():
                if v['url'] == url:
                    key_to_delete = k
                    break
            if key_to_delete:
                del self.registry_data[key_to_delete]
                with open(REGISTRY_FILE, "w") as f:
                    json.dump(self.registry_data, f, indent=4)
                self.load_registry()
                self.append_to_chat("System", "Stale node unregistered successfully.", "bot")

if __name__ == "__main__":
    root = tk.Tk()
    app = SwarmChatUI(root)
    root.mainloop()
"""

# --- 2. PYTHON DISCOVERY ENGINE ---
def get_valid_pythons():
    valid_interpreters = {}
    target_versions = ['3.11', '3.10', '3.9', '3.8']
    
    for v in target_versions:
        if os.name == 'nt':
            try:
                out = subprocess.check_output(
                    ['py', f'-{v}', '-c', 'import sys; print(sys.executable)'], 
                    text=True, stderr=subprocess.DEVNULL
                )
                valid_interpreters[f"Python {v} (Windows Launcher)"] = out.strip()
            except Exception:
                pass
                
        exe_name = f'python{v}'
        path = shutil.which(exe_name)
        if path:
            valid_interpreters[f"Python {v} (System PATH)"] = path
            
    return valid_interpreters

# --- 3. THE UNIFIED GUI & INSTALLER ---
def start_installer():
    root = tk.Tk()
    root.title("Model Server Bootstrapper")
    root.geometry("600x500")
    root.eval('tk::PlaceWindow . center')

    # Step 1: Python Selection
    ttk.Label(root, text="Step 1: Select Stable Python Environment", font=("Helvetica", 10, "bold")).pack(pady=(15, 5))
    valid_pythons = get_valid_pythons()
    python_selector = ttk.Combobox(root, width=65, state="readonly")
    if valid_pythons:
        python_selector['values'] = list(valid_pythons.keys())
        python_selector.current(0)
    else:
        python_selector.set("No valid Python (3.8-3.11) found on system!")
        python_selector.config(state="disabled")
    python_selector.pack(pady=5)

    # Step 2: Custom Node Folder Name
    ttk.Label(root, text="Step 2: Custom Node / Folder Name", font=("Helvetica", 10, "bold")).pack(pady=(15, 5))
    name_entry = ttk.Entry(root, width=40)
    name_entry.insert(0, "my_qwen_node")
    name_entry.pack(pady=5)

    # Step 3: Model URL
    ttk.Label(root, text="Step 3: Model GGUF Download URL", font=("Helvetica", 10, "bold")).pack(pady=(15, 5))
    url_entry = ttk.Entry(root, width=70)
    url_entry.insert(0, "https://huggingface.co/Qwen/Qwen2.5-0.5B-Instruct-GGUF/resolve/main/qwen2.5-0.5b-instruct-q4_k_m.gguf")
    url_entry.pack(pady=5)

    status_var = tk.StringVar()
    status_var.set("Ready to install.")
    status_label = ttk.Label(root, textvariable=status_var, foreground="blue")
    status_label.pack(pady=15)

    def execute_installation():
        if not valid_pythons:
            messagebox.showerror("Error", "You must install Python 3.11 on this machine first.")
            return
            
        selected_key = python_selector.get()
        target_python_exe = valid_pythons[selected_key]
        
        target_dir = name_entry.get().strip()
        if not target_dir:
            messagebox.showwarning("Input Error", "Please provide a valid folder name.")
            return

        model_url = url_entry.get().strip()
        if not model_url:
            messagebox.showwarning("Input Error", "Please enter a model URL.")
            return

        install_btn.config(state="disabled")
        
        try:
            # --- PHASE A: BUILD DIRECTORY ---
            status_var.set("Creating directories and payloads...")
            root.update()
            
            os.makedirs(os.path.join(target_dir, "models"), exist_ok=True)
            with open(os.path.join(target_dir, "requirements.txt"), "w") as f:
                f.write(REQUIREMENTS_TEXT)
            with open(os.path.join(target_dir, "wrapper.py"), "w") as f:
                f.write(WRAPPER_TEXT)
            with open(os.path.join(target_dir, "chat_ui.py"), "w") as f:
                f.write(CHAT_UI_TEXT)
            with open(os.path.join(target_dir, "killtheUVICORN.py"), "w") as f:
                f.write(KILL_SCRIPT_TEXT)
            
            # Runner scripts (Injecting the dynamic target_dir as the NODE_NAME)
            with open(os.path.join(target_dir, "run.bat"), "w") as f:
                f.write(RUN_BAT_TEXT.replace("{NODE_NAME}", target_dir))
            sh_path = os.path.join(target_dir, "run.sh")
            with open(sh_path, "w", newline='\n') as f:
                f.write(RUN_SH_TEXT.replace("{NODE_NAME}", target_dir))
            os.chmod(sh_path, os.stat(sh_path).st_mode | stat.S_IEXEC)

            # --- PHASE B: COMMAND THE TARGET PYTHON TO BUILD VENV ---
            status_var.set(f"Building .venv using {selected_key}...")
            root.update()
            
            venv_dir = os.path.join(target_dir, ".venv")
            subprocess.check_call([target_python_exe, "-m", "venv", venv_dir])

            if os.name == 'nt':
                pip_exe = os.path.join(venv_dir, "Scripts", "pip.exe")
            else:
                pip_exe = os.path.join(venv_dir, "bin", "pip")

            # --- PHASE C: INSTALL WHEELS ---
            status_var.set("Downloading & Installing AI engines (this takes a moment)...")
            root.update()
            subprocess.check_call([pip_exe, "install", "-r", os.path.join(target_dir, "requirements.txt")])

            # --- PHASE D: DOWNLOAD MODEL ---
            status_var.set("Downloading Model... Please wait.")
            root.update()
            
            target_model_path = os.path.join(target_dir, "models", "model.gguf")
            req = urllib.request.Request(model_url, headers={'User-Agent': 'Mozilla/5.0'})
            with urllib.request.urlopen(req) as response, open(target_model_path, 'wb') as out_file:
                out_file.write(response.read())

            status_var.set("Success! All done.")
            msg = f"Installation Complete!\\n\\nTarget Environment: {selected_key}\\n\\n1. Open '{target_dir}' and run 'run.bat' to start the server.\\n2. Run 'python chat_ui.py' to test!\\n3. Run 'python killtheUVICORN.py' if you need to force-free a port."
            messagebox.showinfo("Done", msg)
            root.destroy()

        except PermissionError as e:
            status_var.set("Failed: Access Denied.")
            abs_path = os.path.abspath(target_dir)
            err_file = getattr(e, 'filename', abs_path)
            msg = (f"Windows blocked access to a file or folder.\\n\\n"
                   f"Blocked Path: {err_file}\\n\\n"
                   "Common Fixes:\\n"
                   "1. If a node is currently running, its terminal holds a lock on these files. Close the terminal window first.\\n"
                   "2. Check Task Manager for hidden 'python.exe' processes and end them.\\n"
                   "3. Pick a completely different folder name.")
            messagebox.showerror("Access Denied", msg)
            install_btn.config(state="normal")
        except subprocess.CalledProcessError as e:
            status_var.set("Failed during environment build.")
            messagebox.showerror("Install Error", f"Failed to build environment or install pip packages.\\n{e}")
            install_btn.config(state="normal")
        except Exception as e:
            status_var.set("Failed.")
            messagebox.showerror("Error", f"An error occurred: {e}")
            install_btn.config(state="normal")

    install_btn = ttk.Button(root, text="Bootstrap Environment & Download Model", command=execute_installation)
    install_btn.pack(pady=10)
    
    root.mainloop()

if __name__ == "__main__":
    start_installer()