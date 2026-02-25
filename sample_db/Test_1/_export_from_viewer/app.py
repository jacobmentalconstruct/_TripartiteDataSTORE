        selected_root = find_git_root(selected)
    def get_status_porcelain(self, log_callback=None) -> str | None:
                    self._update_status("Push complete (no new commit).")
        self.txt_log = tk.Text(
        self.f_mono = font.Font(family="Consolas", size=10)
        if log_callback is None:
            insertbackground="#f0f0f0",
        if not self.engine.is_valid_repo():
                capture_output=True,
    if not args.force_without_gitignore and not engine.has_gitignore():
    def _update_status(self, text: str):
            self._update_status("Error: invalid repo path.")
        self._log("-" * 40 + "\n")
        repo_frame = tk.Frame(container, bg="#050505")
    Small dark-themed Tk GUI for commit + push operations.
        btn_frame.pack(fill=tk.X, pady=(0, 8))
            result = subprocess.run(
        sys.exit(0 if ok else 1)
            log_callback("ERROR: git push failed.\n")
            messagebox.showerror("Error", "Git is not available on PATH.")
            combined = (commit_out + "\n" + commit_err).lower()
        self.root = root
        self.btn_commit = tk.Button(
                log_callback=log_cb
        """Return True if `git` is available on PATH."""
        self.msg_var = tk.StringVar(value="")
    def is_valid_repo(self) -> bool:
            if not proceed:
        self.btn_commit.configure(state="disabled")
            self._update_status("Error: not a git repo.")
        if not s.endswith("\n"):
    def log_cb(s: str):
    engine = GitOpsEngine(repo_path=args.repo)
            bg="#333333",
                log_callback("INFO: Nothing to commit after git add.\n")
            log_callback(stderr + "\n")
            self._log("WARNING: Commit message is empty.\n")
        self.txt_log.insert("end", text)
            norm_self = _norm_path(self._self_repo_root)
        # --- STATE ---
        self.engine.repo_path = repo
        stdout = result.stdout.strip()
        def log_cb(s: str):
        stderr = result.stderr.strip()
    except Exception:
            log_callback(stdout + "\n")
                    self._update_status("Push failed.")
            log_callback("ERROR: Unable to determine git status.\n")
                self._log("No local changes detected (working tree clean).\n")
                "No .gitignore found",
        self.txt_log.configure(state="disabled")
            text="…",
        return True
    def _is_self_repo_selected(self) -> bool:
            log_frame,
        container = tk.Frame(self.root, bg="#050505")
            return False
        # --- Recursion UX state ---
def main():
            activeforeground="#ffffff",
        log_callback: optional function that accepts a string for UI logging.
        self.repo_var = tk.StringVar(value=self.engine.repo_path)
        args: list of arguments, e.g. ["git", "status", "--porcelain"]
class GitCommitGUI:
                    self._update_status("Aborted (nothing to commit).")
    engine = GitOpsEngine()
        self.root.title("Git Commit & Push Helper")
        self.root.update_idletasks()
    # --- Status Helpers -------------------------------------------------------
            success = self.engine.commit_and_push(
                "This will add and commit ALL files, including build artifacts, virtualenvs, etc.\n\n"
            if self._self_repo_note_shown_for != norm_self:
        if (parent / ".git").is_dir():
            if success:
if __name__ == "__main__":
        - Autofilling commit message gracefully.
        message: str,
    if args.push_only:
        gitignore_path = os.path.join(self.repo_path, ".gitignore")
    # Helpers ------------------------------------------------------------------
            relief=tk.SUNKEN,
                self._update_status("Commit & push complete.")
                return
        self.status_var = tk.StringVar(value="Ready.")
        tk.Entry(
    def __init__(self, repo_path=None):
        tk.Button(
        ).pack(side=tk.RIGHT)
    def __init__(self, root, engine: GitOpsEngine):
        print("ERROR: Selected folder is not a Git repository (missing .git).", file=sys.stderr)
            command=self._on_commit_push
        ).pack(side=tk.LEFT)
            text="Close",
    GitCommitGUI(root, engine)
        log_callback("SUCCESS: Push completed.\n")
            command=self.root.destroy
    parser.add_argument("--push-only", action="store_true", help="Skip commit and just run git push.")
        self._build_ui()
        p = Path(start_path)
        self.btn_commit.pack(side=tk.LEFT)
                text=True
        """
        tk.Label(msg_frame, text="Commit message:", bg="#050505", fg="#f0f0f0", font=self.f_ui).pack(side=tk.LEFT)
        log_frame.pack(fill=tk.BOTH, expand=True)
            highlightthickness=1,
        self._self_repo_root = find_git_root(Path(__file__).resolve().parent)
    if len(sys.argv) > 1:
        message=args.message,
    def _log(self, text: str):
        status_label = tk.Label(
    if not engine.is_valid_repo():
        self.root.geometry("600x260")
                messagebox.showerror("Error", "Commit and/or push failed. See log for details.")
            self._update_status("Awaiting commit message.")
        """Return True if repo_path contains a .git directory."""
    def push_only(self, log_callback=None) -> bool:
        self.txt_log.configure(state="normal")
        entry_msg = tk.Entry(
        msg = self.msg_var.get().strip()
        Triggered when repo_var changes. Handles:
        self.root.configure(bg="#050505")
        if not self._self_repo_root:
            activebackground="#555555",
    Encapsulates Git-related operations for a single repository.
    sys.exit(0 if ok else 1)
import shutil
        self.txt_log.delete("1.0", "end")
        print("ERROR: No .gitignore found. Use --force-without-gitignore to override.", file=sys.stderr)
            self._update_status("Error: git missing.")
    root.mainloop()
        container.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)
            font=self.f_mono
    parser = argparse.ArgumentParser(description="Git Commit & Push Helper CLI")
# 2. GUI LAYER (The Visual Cortex)
        else:
        return os.path.normcase(os.path.abspath(p))
    if p.is_file():
                if not push_anyway:
            bg="#111111",
class GitOpsEngine:
                success = self.engine.push_only(log_cb)
                self._update_status("Error: git status failed.")
        log_callback("Running: git add .\n")
# 1. CORE ENGINE (Business Logic)
        repo = self.repo_var.get().strip()
        return os.path.exists(gitignore_path)
            messagebox.showerror("Error", "Repository folder does not exist.")
            log_callback
            relief="flat",
        if not selected:
            btn_frame,
            messagebox.showerror("Error", "Selected folder is not a Git repository (missing .git).")
        initial = self.repo_var.get() or os.getcwd()
from pathlib import Path
        folder = filedialog.askdirectory(initialdir=initial)
    def _on_repo_change(self, *_):
                    self._log("User aborted: no changes to commit; push skipped.\n")
        self.engine = engine
            proceed = messagebox.askyesno(
        sys.stdout.flush()
        self._on_repo_change()
            return
                )
        Execute: git add ., git commit -m message, git push.
            font=self.f_ui
                        help="Allow commit/push even if .gitignore is missing.")
from tkinter import filedialog, messagebox, font
    def _browse_repo(self):
            self.txt_log.insert("end", "\n")
        # COMMIT MESSAGE ROW
        - Logging a note if operating on its own repo (informational only).
def run_cli():
            log_callback("ERROR: Git executable not found.\n")
            bg="#101010",
        code, _, _ = self._run_git(["git", "add", "."], log_callback)
    def _run_git(self, args, log_callback=None):
        self.txt_log.pack(fill=tk.BOTH, expand=True)
    def has_gitignore(self) -> bool:
            log_callback("WARNING: No .gitignore detected; operation blocked by policy.\n")
import subprocess
                self._update_status("Self-repo detected.")
            current_msg = self.msg_var.get().strip()
        git_dir = os.path.join(self.repo_path, ".git")
        if not allow_without_gitignore and not self.has_gitignore():
            textvariable=self.msg_var,
            fg="#f0f0f0",
    # Main action --------------------------------------------------------------
                self.msg_var.set(self._autofill_message)
    # Recursion UX -------------------------------------------------------------
        log_callback=None
            textvariable=self.repo_var,
                args,
        selected = self.repo_var.get().strip()
        if not self.engine.is_git_available():
                    "No changes to commit",
    # UI Construction ----------------------------------------------------------
        except FileNotFoundError:
            log_callback("ERROR: git add failed.\n")
            status_out = self.engine.get_status_porcelain(log_cb)
            # Autofill only if helpful (don't override custom messages)
        sys.stdout.write(s)
            anchor="w",
        if self._is_self_repo_selected():
        status_label.pack(side=tk.BOTTOM, fill=tk.X)
        if not selected_root:
            repo_frame,
    root = tk.Tk()
                "Continue anyway?"
            )
                self._self_repo_note_shown_for = norm_self
            self._log("ERROR: No .git directory found in selected folder.\n")
            log_callback("ERROR: Commit message is empty.\n")
            bd=1,
        if not self.engine.has_gitignore():
        self._update_status("Running git operations...")
            return str(parent)
        msg_frame = tk.Frame(container, bg="#050505")
        run_cli()
            self._log("ERROR: Invalid repository path.\n")
            textvariable=self.status_var,
                messagebox.showinfo("Success", "Commit & push completed successfully.")
                self._log("User aborted: no .gitignore present.\n")
        log_frame = tk.Frame(container, bg="#050505")
    Normalize paths for robust equality comparisons on Windows/macOS/Linux.
            text="Commit & Push",
        allow_without_gitignore=args.force_without_gitignore,
                    messagebox.showinfo("Success", "Push completed successfully (no new commit).")
import tkinter as tk
# 4. ENTRY POINT
        """Execute: git push."""
        self._autofill_message = "Self-test / recursion check"
    # --- Environment Checks ---------------------------------------------------
        # React to repo path edits (manual typing or folder picker)
                self._update_status("Aborted (no .gitignore).")
        self.f_ui = font.Font(family="Segoe UI", size=9)
def run_gui():
        # LOG AREA
        # BUTTON ROW
import sys
    # --- Low-Level Git Runner -------------------------------------------------
            width=3,
        if not self.is_valid_repo():
                    "Do you still want to run 'git push'?"
        Return the porcelain status output (possibly empty if clean),
        if not message.strip():
                self._update_status("Commit/push failed.")
        log_callback("SUCCESS: Commit & push completed.\n")
        self.repo_path = repo_path or os.getcwd()
                    messagebox.showerror("Push failed", "git push failed. See log for details.")
        if not self.repo_path or not os.path.isdir(self.repo_path):
    # If a file is passed, start from its parent
        # REPO ROW
            self.repo_var.set(folder)
        log_callback=log_cb
            height=6,
    main()
        )
        if stderr:
        if folder:
    return None
        return os.path.isdir(git_dir)
        self._log(f"Commit message: {msg}\n")
        if status_out is None:
                cwd=self.repo_path,
        self.txt_log.see("end")
        btn_frame = tk.Frame(container, bg="#050505")
            msg_frame,
# 3. CLI LAYER (Utility)
            log_callback("INFO: Nothing to commit (working tree clean).\n")
        return shutil.which("git") is not None
        self,
        log_callback("Running: git commit\n")
        return out
        log_callback("Running: git push\n")
                return False
        finally:
        return result.returncode, stdout, stderr
    parser.add_argument("-r", "--repo", default=os.getcwd(), help="Path to the Git repository.")
        # --- FONTS ---
                self._log("NOTE: Self-repo detected (operating on this tool's own repository).\n")
            return None
        if not repo or not os.path.isdir(repo):
            self.root,
                    "No changes detected to commit.\n\n"
                log_callback("ERROR: git commit failed.\n")
        if not msg:
            self._log("WARNING: No .gitignore detected.\n")
            command=self._browse_repo
        if not self.is_git_available():
            if status_out is None:
        msg_frame.pack(fill=tk.X, pady=(0, 8))
    """
            self._update_status("Ready.")
    try:
    Returns the repo root path or None.
        or None on error.
        run_gui()
        if not text.endswith("\n"):
            ["git", "commit", "-m", message],
            log_callback("ERROR: Selected folder is not a valid Git repository.\n")
    args = parser.parse_args()
        sys.exit(1)
        Returns True on success, False on failure.
    def _on_commit_push(self, event=None):
        entry_msg.bind("<Return>", self._on_commit_push)
def find_git_root(start_path: str) -> str | None:
        # Apply initial self-repo behavior on startup (if launching in repo root)
            messagebox.showwarning("Missing commit message", "Please enter a commit message.")
        entry_msg.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(8, 0))
# ==============================================================================
    parser.add_argument("--force-without-gitignore", action="store_true",
            if not status_out.strip():
        repo_frame.pack(fill=tk.X, pady=(0, 8))
        # .gitignore HITL
                    return
                if success:
    # --- Core Operation -------------------------------------------------------
        try:
                allow_without_gitignore=True,
        self.status_var.set(text)
            bg="#222222",
        ok = engine.push_only(log_cb)
        Run a git command inside repo_path.
def _norm_path(p: str) -> str:
            return 1, "", "Git executable not found."
            def log_callback(_: str):
            self.btn_commit.configure(state="normal")
            fg="#888888",
import os
            if current_msg == "" or current_msg == self._autofill_message:
            highlightbackground="#444444",
            log_callback("ERROR: Git not found on PATH.\n")
        True if the selected repo (or its git root) equals this script's repo root.
        allow_without_gitignore: bool = False,
    for parent in [p] + list(p.parents):

        print("ERROR: Git is not available on PATH.", file=sys.stderr)
        p = p.parent
    Walk upward from start_path to find a directory containing `.git`.
        if not status_out.strip():
    if not engine.is_git_available():
    ok = engine.commit_and_push(
                "No .gitignore file detected.\n\n"
            log_callback = lambda s: None
                message=msg,
        self._self_repo_note_shown_for = None  # normalized path or None
                else:
            else:
        self._log("Git Commit & Push Helper ready.\n")
            self._log(s)
    def is_git_available(self) -> bool:
    else:
    def commit_and_push(
        tk.Label(repo_frame, text="Repository:", bg="#050505", fg="#f0f0f0", font=self.f_ui).pack(side=tk.LEFT)
        code, out, _ = self._run_git(["git", "status", "--porcelain"], log_callback)
        """Return True if a .gitignore exists in the repo root."""
                push_anyway = messagebox.askyesno(
        code, commit_out, commit_err = self._run_git(
        return _norm_path(selected_root) == _norm_path(self._self_repo_root)
            wrap="word",
    ) -> bool:
        status_out = self.get_status_porcelain(log_callback)
            sys.stdout.write("\n")
import argparse
            if "nothing to commit" in combined:
        code, _, _ = self._run_git(["git", "push"], log_callback)
                messagebox.showerror("Error", "Failed to run 'git status'. See log for details.")
            self._log("ERROR: Git not found on PATH.\n")
        self._log(f"Using repo: {repo}\n")
        if code != 0:
        self.repo_var.trace_add("write", self._on_repo_change)
        self.root.resizable(False, False)
        ).pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(8, 4))
        if stdout:
        p = Path(start_path).resolve()
    parser.add_argument("-m", "--message", required=True, help="Commit message.")
    )
    def _build_ui(self):
        return os.path.normcase(os.path.realpath(os.path.abspath(p)))
        tk.Label(log_frame, text="Log:", bg="#050505", fg="#f0f0f0", font=self.f_ui).pack(anchor="w")