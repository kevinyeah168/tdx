from __future__ import annotations

from pathlib import Path


def pick_directory(initial_path: str | None = None) -> str | None:
    """Open a native folder picker on the machine running the API."""
    import tkinter as tk
    from tkinter import filedialog

    initialdir: str | None = None
    if initial_path:
        candidate = Path(initial_path).expanduser()
        if candidate.is_dir():
            initialdir = str(candidate)

    root = tk.Tk()
    root.withdraw()
    root.attributes("-topmost", True)
    try:
        selected = filedialog.askdirectory(
            initialdir=initialdir,
            mustexist=True,
            title="选择通达信导出目录",
        )
    finally:
        root.destroy()

    if not selected:
        return None
    return str(Path(selected))
