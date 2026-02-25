  * **Dark Mode UI:** A custom-styled Tkinter interface designed for low-eye-strain environments.
### Specify a different repository
Open Source. Feel free to modify and integrate into your own workflows.
### Porcelain Status
## 🛡️ Safety Mechanisms
### Push Only (Skip commit)
The tool utilizes `git status --porcelain` to programmatically ensure the working tree actually has changes before attempting a commit, preventing empty commit errors.
2.  That's it. There are no external requirements to install.
python app.py -m "Refactored the core engine"
> **Note:** If you launch the app from within a git repository, it will automatically detect the root and prepopulate the path.
### Basic Commit & Push
  * **Hybrid Interface:** Run it as a GUI application or a Command Line utility.
### CLI Arguments Reference
| `--force-without-gitignore` | Bypasses the safety check for missing `.gitignore` files. |
Based on the code provided, here is a professional, comprehensive, and clean `README.md` file. It highlights the dual nature of the tool (GUI + CLI), its zero-dependency architecture, and its safety features.
## ⌨️ Usage: CLI Mode
One of the most common mistakes in rapid development is running `git add .` inside a folder containing a `venv/` or `node_modules/`.
## 📋 Prerequisites
A lightweight, zero-dependency Python tool designed to streamline the `git add .` $\to$ `git commit` $\to$ `git push` workflow. It features a modern Dark Mode GUI for desktop use and a fully functional CLI for automation scripts.
Simply run the script without arguments:
-----
## 🚀 Features
By default, the CLI will fail if `.gitignore` is missing. You can override this:
  * **Commit Message:** Enter your message here. Press `<Enter>` to trigger the commit.
| `-r`, `--repo` | Path to the target repository (Default: current dir). |
  * **Recursion Detection:** Intelligently detects if you are using the tool to commit changes to the tool's own repository.
### The `.gitignore` Check
  * **Zero Dependencies:** Built entirely with the Python Standard Library (`tkinter`, `subprocess`, etc.). No `pip install` required.
python app.py -m "Initial commit" --force-without-gitignore
| :--- | :--- |
## 🛠️ Installation
  * **Repository:** Defaults to the current working directory. You can type a path or use the **"…"** button to browse.
## 🖥️ Usage: GUI Mode
  * **Log Window:** Displays real-time output from the Git subprocesses.
You can use the tool in headless environments or build scripts by passing arguments.
## 📄 License
```bash
python app.py --repo "C:/Projects/MyWebsite" -m "Update CSS"
| `--push-only` | Skips `add` and `commit`, executes only `git push`. |
### Force commit without .gitignore
  * **Safety First:**
python app.py
      * **Stop-gap Logic:** Warns you (or blocks operation) if a `.gitignore` file is missing, preventing the accidental commit of virtual environments or build artifacts.
  * **Workflow Automation:** Performs `add`, `commit`, and `push` in a single action.
  * **CLI:** Aborts immediately unless the `--force-without-gitignore` flag is used.
1.  Clone this repository or download `app.py`.
# Git Commit & Push Helper
| Argument | Description |
### interface Controls
python app.py --push-only

| `-m`, `--message` | The commit message (Required unless using `--push-only`). |
```
  * **Python 3.x**
  * **Git** (Must be installed and accessible via system PATH)
      * Validates that the target folder is a Git repository.
  * **GUI:** Prompts a Human-in-the-Loop (HITL) warning dialog asking for confirmation before proceeding.