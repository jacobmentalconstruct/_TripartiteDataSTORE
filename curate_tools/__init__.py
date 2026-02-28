"""
tripartite/curate_tools/ — Drop-in curation tool package.

Any .py file in this directory that defines a subclass of BaseCurationTool
will be auto-discovered by studio.py's CuratePanel on startup.

To create a new tool:
  1. Create a .py file in this directory (e.g. my_tool.py)
  2. Import and subclass BaseCurationTool
  3. Implement: name, description, build_config_ui(), run()
  4. Restart Tripartite Studio — your tool appears automatically

Example minimal tool:

    from tripartite.studio import BaseCurationTool
    import tkinter as tk
    import sqlite3

    class MyTool(BaseCurationTool):
        @property
        def name(self): return "My Tool"
        @property
        def description(self): return "Does something useful"
        @property
        def icon(self): return "🔧"
        @property
        def priority(self): return 50

        def build_config_ui(self, parent):
            frame = tk.Frame(parent, bg="#1e1e2e")
            tk.Label(frame, text="No config needed", bg="#1e1e2e", fg="#cdd6f4").pack()
            return frame

        def run(self, conn, selection, on_progress=None, on_log=None):
            log = on_log or (lambda m, t="info": None)
            log("Running my tool…")
            # Do work with conn (sqlite3.Connection)
            return {"status": "done"}

External tool directories can also be registered via Settings → Tool Dirs.
"""
