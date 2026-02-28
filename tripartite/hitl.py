"""
tripartite/hitl.py — Human-in-the-Loop Decision Gateway

All confirmation dialogs, ambiguity resolution, and review queues
route through this single class. This makes every human decision
point discoverable (grep for 'hitl.'), testable (swap for auto-accept
in CI), and consistent in presentation.

Theme colors are hardcoded here (mirrors VS Code Dark from datastore.py)
to avoid circular imports.
"""
from __future__ import annotations

import tkinter as tk
from tkinter import messagebox
from dataclasses import dataclass, field
from typing import Any, Callable, Optional
from enum import Enum, auto


# ══════════════════════════════════════════════════════════════════════════════
#  THEME (mirrors datastore.py constants — no import needed)
# ══════════════════════════════════════════════════════════════════════════════

_BG      = "#1e1e1e"
_BG2     = "#252526"
_BORDER  = "#3c3c3c"
_ACCENT  = "#007acc"
_ACCENT2 = "#0e639c"
_FG      = "#d4d4d4"
_FG_DIM  = "#858585"
_SUCCESS = "#6a9955"
_WARNING = "#dcdcaa"
_ERROR   = "#f44747"

_FONT_UI = ("Segoe UI", 10)
_FONT_SM = ("Segoe UI", 9)
_FONT_MONO = ("Consolas", 9)


# ══════════════════════════════════════════════════════════════════════════════
#  DATA TYPES
# ══════════════════════════════════════════════════════════════════════════════

class Decision(Enum):
    """Possible outcomes of a HITL decision point."""
    ACCEPT = auto()
    REJECT = auto()
    SKIP = auto()
    ACCEPT_ALL = auto()


@dataclass
class ReviewItem:
    """A single item queued for human review."""
    item_id: str
    title: str
    description: str
    context: str
    candidates: list[dict] = field(default_factory=list)
    metadata: dict = field(default_factory=dict)
    decision: Optional[Decision] = None
    chosen_index: Optional[int] = None


@dataclass
class ReviewResult:
    """Outcome of a batch review session."""
    items: list[ReviewItem]
    completed: bool

    @property
    def accepted(self) -> list[ReviewItem]:
        return [i for i in self.items if i.decision == Decision.ACCEPT]

    @property
    def rejected(self) -> list[ReviewItem]:
        return [i for i in self.items if i.decision == Decision.REJECT]

    @property
    def skipped(self) -> list[ReviewItem]:
        return [i for i in self.items if i.decision == Decision.SKIP]


# ══════════════════════════════════════════════════════════════════════════════
#  HITL GATEWAY
# ══════════════════════════════════════════════════════════════════════════════

class HITLGateway:
    """
    Central gateway for all human-in-the-loop decisions.

    Usage throughout the app:
        if self.app.hitl.confirm("Re-ingest?", "File already exists..."):
            do_reingest()

        result = self.app.hitl.review_queue(ambiguous_items)
        for item in result.accepted:
            apply(item)
    """

    def __init__(self, root: tk.Tk, log_callback: Optional[Callable] = None):
        self.root = root
        self._log = log_callback or (lambda src, msg, tag="info": None)

    # ── Simple decisions ──────────────────────────────────────────────

    def confirm(self, title: str, message: str,
                details: str = None, destructive: bool = False) -> bool:
        """
        Yes/No confirmation for single-action decisions.

        Args:
            title: Dialog title
            message: Main question
            details: Optional extra context shown below the question
            destructive: If True, default button is "Cancel" (safety bias)

        Returns True if human confirms, False otherwise.
        """
        full_msg = message
        if details:
            full_msg += f"\n\n{details}"

        self._log("HITL", f"Confirm: {title}", "dim")

        if destructive:
            result = messagebox.askokcancel(title, full_msg,
                                            icon="warning", default="cancel")
        else:
            result = messagebox.askyesno(title, full_msg)

        self._log("HITL", f"  → {'Accepted' if result else 'Rejected'}", "dim")
        return result

    def choose(self, title: str, message: str,
               options: list[str]) -> Optional[int]:
        """
        Pick one option from a list. Returns index or None if cancelled.
        """
        self._log("HITL", f"Choose: {title} ({len(options)} options)", "dim")

        dialog = tk.Toplevel(self.root)
        dialog.title(title)
        dialog.configure(bg=_BG)
        dialog.transient(self.root)
        dialog.grab_set()
        dialog.resizable(False, False)

        result = {"index": None}

        tk.Label(dialog, text=message, bg=_BG, fg=_FG,
                 font=_FONT_UI, wraplength=400,
                 justify="left").pack(padx=16, pady=(16, 8))

        selected = tk.IntVar(value=-1)
        for i, opt in enumerate(options):
            tk.Radiobutton(dialog, text=opt, variable=selected, value=i,
                           bg=_BG, fg=_FG, selectcolor=_BG2,
                           activebackground=_BG, activeforeground=_FG,
                           font=_FONT_SM).pack(anchor="w", padx=24, pady=2)

        btn_frame = tk.Frame(dialog, bg=_BG)
        btn_frame.pack(fill="x", padx=16, pady=(8, 16))

        def on_ok():
            if selected.get() >= 0:
                result["index"] = selected.get()
            dialog.destroy()

        def on_cancel():
            dialog.destroy()

        tk.Button(btn_frame, text="OK", command=on_ok, bg=_ACCENT2,
                  fg="white", relief="flat", padx=20,
                  font=_FONT_SM).pack(side="right", padx=4)
        tk.Button(btn_frame, text="Cancel", command=on_cancel, bg=_BG2,
                  fg=_FG, relief="flat", padx=20,
                  font=_FONT_SM).pack(side="right", padx=4)

        # Center on parent
        dialog.update_idletasks()
        x = self.root.winfo_x() + (self.root.winfo_width() - dialog.winfo_width()) // 2
        y = self.root.winfo_y() + (self.root.winfo_height() - dialog.winfo_height()) // 2
        dialog.geometry(f"+{x}+{y}")

        dialog.wait_window()

        self._log("HITL",
                  f"  → {'Option ' + str(result['index']) if result['index'] is not None else 'Cancelled'}",
                  "dim")
        return result["index"]

    def warn(self, title: str, message: str):
        """Non-blocking warning to OUTPUT log."""
        self._log("HITL", f"⚠ {title}: {message}", "warning")

    def info(self, title: str, message: str):
        """Non-blocking info message to OUTPUT log."""
        self._log("HITL", f"ℹ {title}: {message}", "dim")

    # ── Batch review ──────────────────────────────────────────────────

    def review_queue(self, items: list[ReviewItem],
                     title: str = "Review Required",
                     on_complete: Optional[Callable] = None
                     ) -> ReviewResult:
        """
        Open a batch review window for multiple items needing decisions.

        Supports Accept / Reject / Skip per item, plus "Accept All Remaining"
        for efficiency on large batches.

        Args:
            items: List of ReviewItems to present
            title: Window title
            on_complete: Optional callback when review is done

        Returns ReviewResult with all decisions.
        """
        if not items:
            return ReviewResult(items=[], completed=True)

        self._log("HITL", f"Review queue: {len(items)} items", "accent")

        dialog = tk.Toplevel(self.root)
        dialog.title(f"{title} — {len(items)} items")
        dialog.geometry("700x500")
        dialog.configure(bg=_BG)
        dialog.transient(self.root)
        dialog.grab_set()

        state = {"current": 0, "completed": False}

        # ── Header ────────────────────────────────────────────────────
        header = tk.Frame(dialog, bg=_BG2)
        header.pack(fill="x")
        progress_label = tk.Label(header, text="", bg=_BG2, fg=_ACCENT,
                                  font=("Segoe UI Semibold", 10))
        progress_label.pack(side="left", padx=12, pady=8)

        # ── Content area ──────────────────────────────────────────────
        content_frame = tk.Frame(dialog, bg=_BG)
        content_frame.pack(fill="both", expand=True, padx=12, pady=8)

        title_label = tk.Label(content_frame, text="", bg=_BG, fg=_FG,
                               font=("Segoe UI Semibold", 11), anchor="w")
        title_label.pack(fill="x")

        desc_label = tk.Label(content_frame, text="", bg=_BG, fg=_FG_DIM,
                              font=_FONT_SM, anchor="w", wraplength=650,
                              justify="left")
        desc_label.pack(fill="x", pady=(4, 8))

        context_text = tk.Text(content_frame, bg=_BG2, fg=_FG,
                               font=_FONT_MONO, borderwidth=0, wrap="word",
                               height=12, state="disabled")
        context_text.pack(fill="both", expand=True)

        # Candidate radio buttons (for items with multiple options)
        candidate_frame = tk.Frame(content_frame, bg=_BG)
        candidate_frame.pack(fill="x", pady=(8, 0))
        candidate_var = tk.IntVar(value=0)

        # ── Action buttons ────────────────────────────────────────────
        btn_frame = tk.Frame(dialog, bg=_BG)
        btn_frame.pack(fill="x", padx=12, pady=(0, 12))

        def update_display():
            idx = state["current"]
            item = items[idx]
            progress_label.configure(text=f"Item {idx + 1} of {len(items)}")
            title_label.configure(text=item.title)
            desc_label.configure(text=item.description)

            context_text.configure(state="normal")
            context_text.delete("1.0", "end")
            context_text.insert("1.0", item.context or "(no context)")
            context_text.configure(state="disabled")

            # Rebuild candidate radio buttons
            for w in candidate_frame.winfo_children():
                w.destroy()
            candidate_var.set(0)

            if item.candidates:
                tk.Label(candidate_frame, text="Choose:", bg=_BG,
                         fg=_FG_DIM, font=_FONT_SM).pack(anchor="w")
                for i, c in enumerate(item.candidates):
                    label = c.get("label", f"Option {i + 1}")
                    detail = c.get("detail", "")
                    text = f"{label}  {detail}" if detail else label
                    tk.Radiobutton(candidate_frame, text=text,
                                   variable=candidate_var, value=i,
                                   bg=_BG, fg=_FG, selectcolor=_BG2,
                                   font=_FONT_MONO
                                   ).pack(anchor="w", padx=8)

        def decide(decision: Decision):
            idx = state["current"]
            items[idx].decision = decision
            if items[idx].candidates and decision == Decision.ACCEPT:
                items[idx].chosen_index = candidate_var.get()

            state["current"] += 1
            if state["current"] >= len(items):
                state["completed"] = True
                dialog.destroy()
            else:
                update_display()

        def accept_all():
            for i in range(state["current"], len(items)):
                items[i].decision = Decision.ACCEPT
                if items[i].candidates:
                    items[i].chosen_index = 0
            state["completed"] = True
            dialog.destroy()

        def cancel_all():
            dialog.destroy()

        tk.Button(btn_frame, text="✓ Accept", bg=_SUCCESS, fg="white",
                  relief="flat", font=("Segoe UI", 9, "bold"), padx=16,
                  command=lambda: decide(Decision.ACCEPT)
                  ).pack(side="left", padx=4)
        tk.Button(btn_frame, text="✗ Reject", bg=_ERROR, fg="white",
                  relief="flat", font=_FONT_SM, padx=12,
                  command=lambda: decide(Decision.REJECT)
                  ).pack(side="left", padx=4)
        tk.Button(btn_frame, text="→ Skip", bg=_BG2, fg=_FG,
                  relief="flat", font=_FONT_SM, padx=12,
                  command=lambda: decide(Decision.SKIP)
                  ).pack(side="left", padx=4)
        tk.Button(btn_frame, text="✓✓ Accept All", bg=_BG2, fg=_SUCCESS,
                  relief="flat", font=_FONT_SM, padx=12,
                  command=accept_all
                  ).pack(side="right", padx=4)
        tk.Button(btn_frame, text="Cancel", bg=_BG2, fg=_FG_DIM,
                  relief="flat", font=_FONT_SM, padx=12,
                  command=cancel_all
                  ).pack(side="right", padx=4)

        # Center on parent
        dialog.update_idletasks()
        x = self.root.winfo_x() + (self.root.winfo_width() - dialog.winfo_width()) // 2
        y = self.root.winfo_y() + (self.root.winfo_height() - dialog.winfo_height()) // 2
        dialog.geometry(f"+{x}+{y}")

        update_display()
        dialog.wait_window()

        result = ReviewResult(items=items, completed=state["completed"])
        self._log("HITL",
                  f"Review done: {len(result.accepted)} accepted, "
                  f"{len(result.rejected)} rejected, "
                  f"{len(result.skipped)} skipped", "dim")

        if on_complete:
            on_complete(result)

        return result
