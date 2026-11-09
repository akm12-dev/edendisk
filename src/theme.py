"""Charte visuelle d'EdenDisk : couleurs d'origine (noir + vert sarcelle), en aplat, sans dégradé.

Toutes les couleurs de l'interface viennent d'ici : pour changer l'apparence, modifier ce fichier.
"""
import tkinter as tk
from tkinter import ttk

# Couleurs d'origine d'EdenDisk
TEAL = "#00B4A5"          # accent principal (boutons, sélection, progression)
TEAL_DARK = "#1B544F"     # survol / appui, élément de menu actif
TEAL_LIGHT = "#0ABB9E"    # liseré de l'élément actif
TEAL_TINT = "#DDF4F1"     # fond de ligne sélectionnée
SIDEBAR = "#151515"
SIDEBAR_HOVER = "#232323"
SIDEBAR_TEXT = "#E5E7EB"
SIDEBAR_MUTED = "#9CA3AF"

APP_BG = "#F0F2F5"
CARD = "#FFFFFF"
BORDER = "#E2E5EA"
FIELD_BORDER = "#C9CED6"
TEXT = "#1F2328"
MUTED = "#6B7280"
SUBTLE = "#9AA1AC"
HEADER_BG = "#F5F6F8"
BUTTON_BG = "#EEF0F3"
BUTTON_HOVER = "#E2E5EA"
BUTTON_PRESSED = "#D6DAE0"
DANGER = "#B42318"
DANGER_DARK = "#8F1B12"
DANGER_TINT = "#FDECEA"

FONT = "Segoe UI"
MONO = "Consolas"
F_TITLE = (FONT, 17, "bold")
F_SUBTITLE = (FONT, 10)
F_BODY = (FONT, 10)
F_BODY_BOLD = (FONT, 10, "bold")
F_SECTION = (FONT, 10, "bold")
F_NAV = (FONT, 11)
F_NAV_ACTIVE = (FONT, 11, "bold")


def apply(root: tk.Tk) -> ttk.Style:
    """Configure les styles ttk (base « clam », seule à permettre des boutons colorés sous Windows)."""
    style = ttk.Style(root)
    style.theme_use("clam")
    root.option_add("*Font", (FONT, 10))
    root.option_add("*TCombobox*Listbox.font", (FONT, 10))
    root.option_add("*TCombobox*Listbox.selectBackground", TEAL)

    style.configure(".", font=(FONT, 10), background=CARD, foreground=TEXT, bordercolor=BORDER,
                    focuscolor=TEAL, troughcolor=BORDER)

    # Boutons : secondaire (par défaut), principal (sarcelle), danger (rouge)
    style.configure("TButton", padding=(10, 3), background=BUTTON_BG, foreground=TEXT, bordercolor=FIELD_BORDER,
                    lightcolor=BUTTON_BG, darkcolor=BUTTON_BG, relief="flat", borderwidth=1)
    style.map("TButton",
              background=[("disabled", HEADER_BG), ("pressed", BUTTON_PRESSED), ("active", BUTTON_HOVER)],
              lightcolor=[("disabled", HEADER_BG), ("pressed", BUTTON_PRESSED), ("active", BUTTON_HOVER)],
              darkcolor=[("disabled", HEADER_BG), ("pressed", BUTTON_PRESSED), ("active", BUTTON_HOVER)],
              foreground=[("disabled", SUBTLE)],
              bordercolor=[("disabled", BORDER), ("focus", TEAL)])
    for name, base, dark in (("Accent", TEAL, TEAL_DARK), ("Danger", DANGER, DANGER_DARK)):
        style.configure(f"{name}.TButton", background=base, foreground="#FFFFFF", bordercolor=base,
                        lightcolor=base, darkcolor=base, font=(FONT, 10, "bold"), padding=(12, 3))
        style.map(f"{name}.TButton",
                  background=[("disabled", "#D5D9DF"), ("pressed", dark), ("active", dark)],
                  foreground=[("disabled", "#FFFFFF")],
                  bordercolor=[("disabled", "#D5D9DF"), ("active", dark)])

    # Champs
    for widget in ("TEntry", "TCombobox"):
        style.configure(widget, fieldbackground=CARD, background=CARD, foreground=TEXT, bordercolor=FIELD_BORDER,
                        lightcolor=CARD, darkcolor=CARD, arrowcolor=MUTED, padding=4)
        style.map(widget, bordercolor=[("focus", TEAL)], lightcolor=[("focus", TEAL)],
                  fieldbackground=[("readonly", CARD), ("disabled", HEADER_BG)],
                  foreground=[("disabled", SUBTLE)])

    # Cases à cocher
    style.configure("TCheckbutton", background=CARD, foreground=TEXT, indicatorbackground=CARD,
                    indicatorforeground=TEAL, indicatormargin=(0, 0, 6, 0))
    style.map("TCheckbutton", indicatorbackground=[("selected", TEAL), ("active", TEAL_TINT)],
              indicatorforeground=[("selected", "#FFFFFF")], background=[("active", CARD)])

    # Listes (Treeview)
    style.configure("Treeview", background=CARD, fieldbackground=CARD, foreground=TEXT, rowheight=26,
                    bordercolor=BORDER, lightcolor=BORDER, darkcolor=BORDER, borderwidth=1)
    style.map("Treeview", background=[("selected", TEAL_TINT)], foreground=[("selected", TEXT)])
    style.configure("Treeview.Heading", background=HEADER_BG, foreground=MUTED, font=(FONT, 9, "bold"),
                    bordercolor=BORDER, lightcolor=HEADER_BG, darkcolor=HEADER_BG, relief="flat", padding=(6, 4))
    style.map("Treeview.Heading", background=[("active", "#ECEEF1")])

    # Progression et barres de défilement
    style.configure("TProgressbar", background=TEAL, troughcolor="#E6E8EC", bordercolor="#E6E8EC",
                    lightcolor=TEAL, darkcolor=TEAL, thickness=8)
    style.configure("Vertical.TScrollbar", background=HEADER_BG, troughcolor=CARD, bordercolor=CARD,
                    arrowcolor=MUTED, lightcolor=HEADER_BG, darkcolor=HEADER_BG)
    return style


class NavItem(tk.Frame):
    """Élément du menu latéral : texte à plat, liseré sarcelle et fond foncé quand il est actif."""

    def __init__(self, master, text, icon, command):
        super().__init__(master, bg=SIDEBAR, cursor="hand2")
        self.command = command
        self.active = False
        self.bar = tk.Frame(self, bg=SIDEBAR, width=4)
        self.bar.pack(side="left", fill="y")
        # Icône dans une police de symboles, jamais en gras (le gras de Segoe UI n'a pas tous les symboles)
        self.icon = tk.Label(self, text=icon, bg=SIDEBAR, fg=SIDEBAR_TEXT, font=("Segoe UI Symbol", 11),
                             width=2, padx=0, pady=10)
        self.icon.pack(side="left", padx=(16, 8))
        self.label = tk.Label(self, text=text, bg=SIDEBAR, fg=SIDEBAR_TEXT, font=F_NAV, anchor="w", pady=10)
        self.label.pack(side="left", fill="x", expand=True)
        for w in (self, self.icon, self.label, self.bar):
            w.bind("<Button-1>", lambda e: self.command())
            w.bind("<Enter>", lambda e: self._paint(hover=True))
            w.bind("<Leave>", lambda e: self._paint(hover=False))

    def set_active(self, active: bool):
        self.active = active
        self._paint(hover=False)

    def _paint(self, hover: bool):
        if self.active:
            bg, bar, font = TEAL_DARK, TEAL_LIGHT, F_NAV_ACTIVE
        else:
            bg, bar, font = (SIDEBAR_HOVER if hover else SIDEBAR), (SIDEBAR_HOVER if hover else SIDEBAR), F_NAV
        self.configure(bg=bg)
        self.label.configure(bg=bg, font=font, fg="#FFFFFF" if self.active else SIDEBAR_TEXT)
        self.icon.configure(bg=bg, fg=TEAL_LIGHT if self.active else SIDEBAR_TEXT)
        self.bar.configure(bg=bar)


class Card(tk.Frame):
    """Panneau blanc à bordure fine."""

    def __init__(self, master, **kwargs):
        super().__init__(master, bg=CARD, highlightbackground=BORDER, highlightthickness=1, bd=0, **kwargs)


def page_header(parent, title, subtitle=None, warning=False):
    """Titre de page aligné à gauche + sous-titre (rouge si l'écran efface des données)."""
    box = tk.Frame(parent, bg=CARD)
    box.pack(fill="x", padx=24, pady=(18, 10))
    tk.Label(box, text=title, font=F_TITLE, fg=TEXT, bg=CARD, anchor="w").pack(fill="x")
    if subtitle:
        tk.Label(box, text=subtitle, font=F_SUBTITLE, fg=DANGER if warning else MUTED, bg=CARD, anchor="w",
                 justify="left", wraplength=840).pack(fill="x", pady=(2, 0))
    return box


def label(parent, text="", muted=False, bold=False, **kwargs):
    kwargs.setdefault("anchor", "w")
    return tk.Label(parent, text=text, bg=CARD, fg=MUTED if muted else TEXT,
                    font=F_BODY_BOLD if bold else F_BODY, **kwargs)
