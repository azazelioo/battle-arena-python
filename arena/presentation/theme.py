"""Shared palette and original vector artwork for the desktop arena."""
from __future__ import annotations

import math
import tkinter as tk
from tkinter import font, ttk

BG = "#131a20"
SURFACE = "#1c2730"
RAISED = "#25333d"
LINE = "#35454e"
TEXT = "#e8e5da"
MUTED = "#a3b0b6"
GOLD = "#d5b77a"
HEALTH = "#83b697"
ENERGY = "#7baac7"
CLASS_COLORS = {"warrior": "#d5b77a", "mage": "#9db9da", "ranger": "#95b99c"}


def configure(root: tk.Tk, size: int) -> tuple[ttk.Style, str, str]:
    available = set(font.families(root))
    display = next((f for f in ("Georgia", "Constantia", "DejaVu Serif") if f in available), "serif")
    body = next((f for f in ("Avenir Next", "Segoe UI", "DejaVu Sans") if f in available), "sans-serif")
    root.configure(background=BG)
    style = ttk.Style(root)
    style.theme_use("clam")
    style.configure(".", background=BG, foreground=TEXT, font=(body, size), borderwidth=0)
    style.configure("TFrame", background=BG)
    style.configure("Card.TFrame", background=SURFACE)
    style.configure("TLabel", background=BG, foreground=TEXT)
    style.configure("Muted.TLabel", foreground=MUTED)
    style.configure("Gold.TLabel", foreground=GOLD)
    style.configure("Title.TLabel", font=(display, 30), foreground=TEXT)
    style.configure("Heading.TLabel", font=(body, 15, "bold"))
    style.configure("Card.TLabel", background=SURFACE)
    style.configure("CardMuted.TLabel", background=SURFACE, foreground=MUTED, font=(body, max(10, size - 1)))
    style.configure("CardName.TLabel", background=SURFACE, font=(display, 18))
    style.configure("TButton", background=RAISED, foreground=TEXT, padding=(16, 10),
                    borderwidth=1, bordercolor=LINE, lightcolor=RAISED, darkcolor=RAISED,
                    focuscolor=GOLD, focusthickness=2)
    style.map("TButton", background=[("disabled", SURFACE), ("pressed", LINE), ("active", "#33444e")],
              foreground=[("disabled", "#829099")], bordercolor=[("focus", GOLD), ("active", GOLD)])
    style.configure("Primary.TButton", background=GOLD, foreground=BG, font=(body, size, "bold"))
    style.map("Primary.TButton", background=[("disabled", SURFACE), ("pressed", "#b99b61"), ("active", "#e5cd9b")],
              foreground=[("disabled", MUTED), ("!disabled", BG)])
    style.configure("Action.TButton", padding=(10, 9), font=(body, max(10, size - 1)))
    style.configure("TEntry", fieldbackground=SURFACE, foreground=TEXT, insertcolor=GOLD,
                    bordercolor=LINE, padding=8)
    style.configure("TCombobox", fieldbackground=SURFACE, background=RAISED,
                    foreground=TEXT, arrowcolor=GOLD, padding=7, bordercolor=LINE)
    style.map("TCombobox", fieldbackground=[("readonly", SURFACE)],
              foreground=[("readonly", TEXT)], selectbackground=[("readonly", SURFACE)],
              selectforeground=[("readonly", TEXT)])
    root.option_add("*TCombobox*Listbox.background", SURFACE)
    root.option_add("*TCombobox*Listbox.foreground", TEXT)
    root.option_add("*TCombobox*Listbox.selectBackground", LINE)
    style.configure("TSpinbox", fieldbackground=SURFACE, foreground=TEXT,
                    arrowcolor=GOLD, background=RAISED, bordercolor=LINE, padding=8)
    style.configure("TLabelframe", background=BG, bordercolor=LINE, borderwidth=1)
    style.configure("TLabelframe.Label", background=BG, foreground=GOLD, font=(body, size, "bold"))
    for name, color in (("Health", HEALTH), ("Energy", ENERGY)):
        style.configure(f"{name}.Horizontal.TProgressbar", background=color,
                        troughcolor=BG, bordercolor=BG, borderwidth=0, lightcolor=color, darkcolor=color,
                        thickness=7)
    style.configure("Vertical.TScrollbar", background=LINE, troughcolor=SURFACE,
                    arrowcolor=MUTED, borderwidth=0, arrowsize=12)
    style.configure("Treeview", background=SURFACE, fieldbackground=SURFACE,
                    foreground=TEXT, rowheight=34, borderwidth=0)
    style.configure("Treeview.Heading", background=RAISED, foreground=GOLD, padding=10)
    style.map("Treeview", background=[("selected", LINE)], foreground=[("selected", TEXT)])
    return style, display, body


def draw_emblem(canvas: tk.Canvas, archetype: str, x: float, y: float,
                radius: float) -> None:
    color = CLASS_COLORS[archetype]
    def line(*coords: float, width: float = 2) -> None:
        canvas.create_line(*coords, fill=color, width=width, capstyle="round", joinstyle="round")
    canvas.create_oval(x-radius, y-radius, x+radius, y+radius, outline=LINE, width=1)
    r = radius * .84
    canvas.create_oval(x-r, y-r, x+r, y+r, outline=color, width=1)
    s = radius * .62
    if archetype == "warrior":
        canvas.create_polygon(x, y-s, x+s*.17, y-s*.68, x+s*.12, y+s*.3,
                              x-s*.12, y+s*.3, x-s*.17, y-s*.68,
                              fill="", outline=color, width=2)
        line(x-s*.45, y+s*.25, x, y+s*.4, x+s*.45, y+s*.25)
        line(x, y+s*.35, x, y+s*.8, width=3)
        canvas.create_oval(x-3, y+s*.8-3, x+3, y+s*.8+3, fill=color, outline="")
    elif archetype == "mage":
        canvas.create_oval(x-s*.5, y-s*.5, x+s*.5, y+s*.5, outline=color, width=2)
        canvas.create_arc(x-s, y-s*.3, x+s, y+s*.3, start=10, extent=320,
                          outline=color, style="arc", width=1)
        for angle in (0, 90, 180, 270):
            a = math.radians(angle)
            line(x+math.cos(a)*s*.7, y+math.sin(a)*s*.7,
                 x+math.cos(a)*s, y+math.sin(a)*s)
        canvas.create_polygon(x, y-7, x+5, y, x, y+7, x-5, y, fill=color, outline="")
    else:
        canvas.create_arc(x-s*.7, y-s, x+s*.8, y+s, start=-80, extent=160,
                          outline=color, style="arc", width=2)
        line(x+s*.17, y-s*.98, x-s*.4, y, x+s*.17, y+s*.98)
        line(x-s*.95, y, x+s*.9, y)
        line(x+s*.65, y-s*.22, x+s*.95, y, x+s*.65, y+s*.22)
        line(x-s*.72, y, x-s*.93, y-s*.2)
        line(x-s*.72, y, x-s*.93, y+s*.2)


class Emblem(tk.Canvas):
    def __init__(self, parent: tk.Misc, archetype: str, size: int = 86) -> None:
        super().__init__(parent, width=size, height=size, background=SURFACE,
                         highlightthickness=0, borderwidth=0)
        draw_emblem(self, archetype, size/2, size/2, size*.44)


class ArenaArt(tk.Canvas):
    """Scalable arena engraving drawn locally; no external assets or fonts."""
    def __init__(self, parent: tk.Misc) -> None:
        super().__init__(parent, background=BG, highlightthickness=0, width=430, height=470)
        self.bind("<Configure>", self.redraw)

    def redraw(self, event: tk.Event[tk.Misc]) -> None:
        self.delete("all")
        w, h = event.width, event.height
        x, y = w*.5, h*.49
        r = min(w*.42, h*.36)
        for factor in (1, .92, .68):
            self.create_oval(x-r*factor, y-r*factor, x+r*factor, y+r*factor,
                             outline=LINE, width=1)
        for index in range(48):
            angle = math.tau*index/48
            inner = r*(.94 if index % 4 else .87)
            self.create_line(x+math.cos(angle)*inner, y+math.sin(angle)*inner,
                             x+math.cos(angle)*r, y+math.sin(angle)*r,
                             fill=GOLD if index % 4 == 0 else LINE)
        for offset in (-1, 1):
            px = x+offset*r*.92
            self.create_line(px, y+r*.7, px, y+r*1.35, fill=LINE)
            self.create_line(px-15, y+r*1.35, px+15, y+r*1.35, fill=GOLD)
        self.create_polygon(x, y-r*.62, x+r*.48, y+r*.25, x-r*.48, y+r*.25,
                            outline=LINE, fill="", width=1)
        for archetype, dx, dy in (("warrior", 0, -.42), ("mage", -.43, .3), ("ranger", .43, .3)):
            cx, cy = x+dx*r, y+dy*r
            self.create_oval(cx-r*.29, cy-r*.29, cx+r*.29, cy+r*.29, fill=BG, outline="")
            draw_emblem(self, archetype, cx, cy, r*.27)
        self.create_line(x-r*.45, y+r*1.12, x+r*.45, y+r*1.12, fill=LINE)
        self.create_text(x, y+r*1.28, text="Воин   /   Маг   /   Следопыт", fill=MUTED, font=("Helvetica", 11))
