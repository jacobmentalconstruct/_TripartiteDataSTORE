"""
src/gui_constants.py

VS Code Dark theme constants — colours, fonts, icons.
Single source of truth for all GUI modules.
"""

# ══════════════════════════════════════════════════════════════════════════════
#  THEME
# ══════════════════════════════════════════════════════════════════════════════

# VS Code Dark — all colour constants
BG       = "#1e1e1e"       # main background
BG2      = "#252526"       # panels, toolbars
BG3      = "#2d2d2d"       # elevated surfaces
BORDER   = "#3c3c3c"       # borders/separators
ACCENT   = "#007acc"       # primary accent (selection, active tab)
ACCENT2  = "#0e639c"       # buttons
ACCENT3  = "#1177bb"       # hover states
FG       = "#d4d4d4"       # primary text
FG_DIM   = "#858585"       # secondary text
FG_MUTED = "#6a6a6a"       # disabled/hint text
SUCCESS  = "#6a9955"       # green
WARNING  = "#dcdcaa"       # yellow
ERROR    = "#f44747"       # red
INFO     = "#9cdcfe"       # light blue (info text)

FONT_UI   = ("Segoe UI", 10)
FONT_SM   = ("Segoe UI", 9)
FONT_XS   = ("Segoe UI", 8)
FONT_H    = ("Segoe UI Semibold", 11)
FONT_MONO = ("Consolas", 10)
FONT_MONO_SM = ("Consolas", 9)
FONT_MONO_XS = ("Consolas", 8)

PAD = 8


# ══════════════════════════════════════════════════════════════════════════════
#  NODE ICONS (used in explorer + results)
# ══════════════════════════════════════════════════════════════════════════════

NODE_ICONS = {
    "root": "\U0001f5c4", "directory": "\U0001f4c1", "file": "\U0001f4c4", "virtual_file": "\U0001f4ce",
    "compound_summary": "\U0001f4cb", "module": "\U0001f4e6", "class_def": "\U0001f537",
    "function_def": "\u26a1", "method_def": "\u26a1", "async_function": "\u26a1",
    "decorator": "\U0001f3f7", "import": "\U0001f4ce", "document": "\U0001f4c4",
    "document_summary": "\U0001f4cb", "section": "\u00a7", "subsection": "\u00a7",
    "heading": "\u00a7", "paragraph": "\u00b6", "list_item": "\u2022",
    "object": "{ }", "array": "[ ]", "key_value": "\u2192", "table": "\u25a6",
    "html_element": "\u25c7", "html_section": "\u25c8", "css_rule": "\U0001f3a8",
    "xml_element": "\u25c7", "chunk": "\u25aa",
}
