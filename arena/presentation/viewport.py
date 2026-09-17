"""Scrollable desktop content keeps large user-selected text reachable."""

from __future__ import annotations

import tkinter as tk
from tkinter import ttk

from . import theme


class ScrollViewport(ttk.Frame):
    def __init__(self, parent: tk.Misc) -> None:
        super().__init__(parent)
        self.canvas = tk.Canvas(
            self,
            background=theme.BG,
            highlightthickness=0,
            borderwidth=0,
            width=1,
            height=1,
        )
        self.scrollbar = ttk.Scrollbar(
            self,
            orient="vertical",
            command=self.canvas.yview,
        )
        self.scrollbar.pack(side="right", fill="y")
        self.canvas.pack(side="left", fill="both", expand=True)
        self.canvas.configure(yscrollcommand=self.scrollbar.set)
        self.content = ttk.Frame(self.canvas, padding=24)
        self._window = self.canvas.create_window(
            0,
            0,
            anchor="nw",
            window=self.content,
        )
        self.canvas.bind("<Configure>", self.resize)
        self.content.bind("<Configure>", self.resize)
        self.canvas.bind("<MouseWheel>", self.wheel)
        self.canvas.bind("<Button-4>", self.wheel)
        self.canvas.bind("<Button-5>", self.wheel)
        self.content.bind("<MouseWheel>", self.wheel)

    def resize(self, event: tk.Event[tk.Misc]) -> None:
        width = max(1, self.canvas.winfo_width())
        height = max(
            self.canvas.winfo_height(), self.content.winfo_reqheight()
        )
        self.canvas.itemconfigure(self._window, width=width, height=height)
        self.canvas.configure(scrollregion=(0, 0, width, height))

    def reset(self) -> None:
        self.canvas.yview_moveto(0)

    def wheel(self, event: tk.Event[tk.Misc]) -> str:
        if event.num == 4:
            amount = -1
        elif event.num == 5:
            amount = 1
        else:
            amount = -1 if event.delta > 0 else 1
        self.canvas.yview_scroll(amount, "units")
        return "break"

    def reveal(self, widget: tk.Widget) -> None:
        self.update_idletasks()
        offset = widget.winfo_rooty() - self.content.winfo_rooty()
        total = max(1, self.content.winfo_height())
        self.canvas.yview_moveto(max(0, offset - 12) / total)
