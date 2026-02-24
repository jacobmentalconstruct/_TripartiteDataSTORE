# UI Mapper Report
_Generated: 2026-02-24T09:28:34_

**Project Root:** `C:\Users\jacob\Documents\_UsefulDataCurationTools\_TripartiteDataStore`

## Summary
- Windows detected: **0**
- Widgets detected: **13**
- Unknown cases: **0**
- Parse errors: **0**

## Windows
_None detected._

## Widgets
### Button (1)
- **w8** (parent: `w6`) — created at `C:\Users\jacob\Documents\_UsefulDataCurationTools\_TripartiteDataStore\tripartite\settings_dialog.py:212:8`
  - kwargs:
    - `activebackground` = `'#3a3a5e'`
    - `bg` = `BG2`
    - `cursor` = `'hand2'`
    - `fg` = `FG`
    - `font` = `FONT_SM`
    - `padx` = `10`
    - `pady` = `3`
    - `relief` = `'flat'`
    - `text` = `'⬇  Download'`
  - layout:
    - `pack(side='left', padx=Tuple)`
  - config:
    - `configure(command=on_download)`
    - `configure(text='⬇  Re-download', fg=FG_DIM)`
    - `configure(text='⬇  Download', fg=ACCENT2)`
    - `configure(state='disabled')`
    - `configure(state='normal')`

### Combobox (1)
- **w5** (parent: `w4`) — created at `C:\Users\jacob\Documents\_UsefulDataCurationTools\_TripartiteDataStore\tripartite\settings_dialog.py:194:8`
  - kwargs:
    - `state` = `'readonly'`
    - `textvariable` = `combo_var`
    - `values` = `display_names`
    - `width` = `52`
  - layout:
    - `pack(anchor='w')`
  - binds:
    - `'<<ComboboxSelected>>' -> on_combo_change`

### Frame (8)
- **w1** (parent: `None`) — created at `C:\Users\jacob\Documents\_UsefulDataCurationTools\_TripartiteDataStore\tripartite\settings_dialog.py:113:8`
  - kwargs:
    - `bg` = `BG2`
    - `pady` = `10`
  - layout:
    - `pack(fill='x')`
- **w10** (parent: `w9`) — created at `C:\Users\jacob\Documents\_UsefulDataCurationTools\_TripartiteDataStore\tripartite\gui.py:222:8`
  - kwargs:
    - `bg` = `BG2`
  - layout:
    - `pack(fill='x', padx=10, pady=Tuple)`
- **w12** (parent: `w9`) — created at `C:\Users\jacob\Documents\_UsefulDataCurationTools\_TripartiteDataStore\tripartite\gui.py:242:8`
  - kwargs:
    - `bg` = `BG2`
  - layout:
    - `pack(fill='x', padx=10, pady=Tuple)`
- **w2** (parent: `None`) — created at `C:\Users\jacob\Documents\_UsefulDataCurationTools\_TripartiteDataStore\tripartite\settings_dialog.py:118:8`
  - kwargs:
    - `bg` = `BG`
  - layout:
    - `pack(fill='both', expand=True, padx=18, pady=12)`
- **w3** (parent: `None`) — created at `C:\Users\jacob\Documents\_UsefulDataCurationTools\_TripartiteDataStore\tripartite\settings_dialog.py:157:8`
  - kwargs:
    - `bg` = `BG2`
    - `pady` = `8`
  - layout:
    - `pack(fill='x', side='bottom')`
- **w4** (parent: `None`) — created at `C:\Users\jacob\Documents\_UsefulDataCurationTools\_TripartiteDataStore\tripartite\settings_dialog.py:179:8`
  - kwargs:
    - `bg` = `BG`
  - layout:
    - `pack(fill='x', pady=Tuple)`
- **w6** (parent: `w4`) — created at `C:\Users\jacob\Documents\_UsefulDataCurationTools\_TripartiteDataStore\tripartite\settings_dialog.py:204:8`
  - kwargs:
    - `bg` = `BG`
  - layout:
    - `pack(fill='x')`
- **w9** (parent: `None`) — created at `C:\Users\jacob\Documents\_UsefulDataCurationTools\_TripartiteDataStore\tripartite\gui.py:216:8`
  - kwargs:
    - `bg` = `BG2`
  - layout:
    - `pack(fill='x', side='bottom')`

### Label (1)
- **w7** (parent: `w6`) — created at `C:\Users\jacob\Documents\_UsefulDataCurationTools\_TripartiteDataStore\tripartite\settings_dialog.py:208:8`
  - kwargs:
    - `bg` = `BG`
    - `font` = `FONT_SM`
    - `textvariable` = `status_var`
  - layout:
    - `pack(side='left')`
  - config:
    - `configure(fg=SUCCESS)`
    - `configure(fg=FG_DIM)`

### Progressbar (2)
- **w11** (parent: `w10`) — created at `C:\Users\jacob\Documents\_UsefulDataCurationTools\_TripartiteDataStore\tripartite\gui.py:228:8`
  - kwargs:
    - `length` = `180`
    - `maximum` = `1`
    - `mode` = `'determinate'`
- **w13** (parent: `w12`) — created at `C:\Users\jacob\Documents\_UsefulDataCurationTools\_TripartiteDataStore\tripartite\gui.py:248:8`
  - kwargs:
    - `length` = `180`
    - `maximum` = `1`
    - `mode` = `'determinate'`


## Unknown Cases
_None._

## Parse Errors
_None._
