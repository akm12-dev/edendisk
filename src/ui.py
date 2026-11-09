import tkinter as tk
from tkinter import ttk, filedialog, messagebox
from PIL import Image, ImageTk, ImageDraw
import datetime
import queue
import threading
import os
import webbrowser

# --- Import backend ---
from backend import (
    list_drives_with_labels, extract_drive_letter,
    load_preferences, save_preferences,
    get_translator, LANGUAGES
)
import disks
import theme
import transfer
from pathlib import Path

import sys

APP_VERSION = "2.0.1"
FICHE_URL = "https://akm12.com/logiciels/edendisk"

# Ordre des écrans (identique à l'ordre du menu)
PAGE_DISKS, PAGE_COPY, PAGE_CLONE, PAGE_FORMAT, PAGE_SETTINGS = range(5)

if getattr(sys, 'frozen', False):  # exécutable PyInstaller
    BASE_DIR = sys._MEIPASS
else:
    BASE_DIR = os.path.dirname(os.path.abspath(__file__))

LOGO_PATH = os.path.join(BASE_DIR, "assets", "img", "logo.png")
ICON_PATH = os.path.join(BASE_DIR, "assets", "icons", "edendisk.ico")


# ------------------- Utils -------------------
# Tkinter n'est pas thread-safe : les tâches de fond déposent leurs mises à jour d'interface
# dans cette file, que la fenêtre principale exécute toutes les 50 ms (voir _drain_ui_queue).
_ui_queue: "queue.Queue" = queue.Queue()


def run_on_ui(func, *args):
    """Exécute func(*args) dans le thread de l'interface (appel direct si on y est déjà)."""
    if threading.current_thread() is threading.main_thread():
        func(*args)
    else:
        _ui_queue.put((func, args))


def log_message(text_widget, message):
    if threading.current_thread() is not threading.main_thread():
        _ui_queue.put((log_message, (text_widget, message)))
        return
    text_widget.config(state="normal")
    timestamp = datetime.datetime.now().strftime("%H:%M:%S")
    text_widget.insert(tk.END, f"{timestamp}  {message}\n")
    text_widget.see(tk.END)
    text_widget.config(state="disabled")


def CardFrame(master, bg=None, **kwargs):
    """Panneau d'écran (conservé pour les pages existantes)."""
    return theme.Card(master, **kwargs)


# ------------------- Fenêtre principale -------------------
class EdenDiskDashboard(tk.Tk):
    def __init__(self):
        super().__init__()

        # Icône
        try:
            self.iconbitmap(ICON_PATH)
        except Exception:
            try:
                self.iconphoto(False, ImageTk.PhotoImage(Image.open(ICON_PATH)))
            except Exception:
                pass

        self.lang_code = load_preferences().get("language", "fr")
        self._ = get_translator()
        theme.apply(self)

        self.title("EdenDisk")
        self.geometry("1200x760")
        self.minsize(1100, 700)
        self.configure(bg=theme.APP_BG)

        # --- Menu latéral ---
        self.sidebar = tk.Frame(self, bg=theme.SIDEBAR, width=240)
        self.sidebar.pack(side="left", fill="y")
        self.sidebar.pack_propagate(False)

        brand = tk.Frame(self.sidebar, bg=theme.SIDEBAR)
        brand.pack(fill="x", pady=(26, 22))
        self.logo_imgtk = self.load_logo_image(84)
        tk.Label(brand, image=self.logo_imgtk, bg=theme.SIDEBAR).pack()
        tk.Label(brand, text="EdenDisk", bg=theme.SIDEBAR, fg=theme.CARD, font=(theme.FONT, 16, "bold")).pack(pady=(10, 0))
        tk.Label(brand, text=self._("Transfert de données et préparation de disques"), bg=theme.SIDEBAR,
                 fg=theme.SIDEBAR_MUTED, font=(theme.FONT, 9), wraplength=190, justify="center").pack(pady=(2, 0))

        self.menu_items = [
            {"label": self._("Disques"), "icon": "◉"},
            {"label": self._("Transfert"), "icon": "⇄"},
            {"label": self._("Copie de lecteur"), "icon": "⧉"},
            {"label": self._("Préparation"), "icon": "⚠"},
            {"label": self._("Paramètres"), "icon": "⚙"},
        ]
        self.menu_buttons = []
        for idx, item in enumerate(self.menu_items):
            nav = theme.NavItem(self.sidebar, item["label"], item["icon"], command=lambda i=idx: self.open_page(i))
            nav.pack(fill="x")
            self.menu_buttons.append(nav)

        footer = tk.Frame(self.sidebar, bg=theme.SIDEBAR)
        footer.pack(side="bottom", fill="x", pady=16)
        tk.Label(footer, text=self._("Outil gratuit AKM12") + f" · v{APP_VERSION}", bg=theme.SIDEBAR,
                 fg=theme.SIDEBAR_MUTED, font=(theme.FONT, 9)).pack()
        site = tk.Label(footer, text="akm12.com", bg=theme.SIDEBAR, fg=theme.TEAL, font=(theme.FONT, 10, "underline"),
                        cursor="hand2")
        site.pack()
        site.bind("<Button-1>", lambda e: webbrowser.open_new(FICHE_URL))

        # --- Zone principale ---
        self.main_area = tk.Frame(self, bg=theme.APP_BG)
        self.main_area.pack(side="right", fill="both", expand=True)
        self.page_container = tk.Frame(self.main_area, bg=theme.APP_BG)
        self.page_container.pack(fill="both", expand=True, padx=20, pady=(20, 10))

        # --- Journal (repliable) ---
        logs = theme.Card(self.main_area)
        logs.pack(fill="x", padx=20, pady=(0, 20))
        head = tk.Frame(logs, bg=theme.CARD)
        head.pack(fill="x", padx=14, pady=(8, 4))
        tk.Label(head, text=self._("Journal"), font=theme.F_SECTION, fg=theme.TEXT, bg=theme.CARD).pack(side="left")
        self.log_toggle = ttk.Button(head, text=self._("Masquer"), command=self.toggle_log)
        self.log_toggle.pack(side="right")
        ttk.Button(head, text=self._("Effacer"), command=self.clear_log).pack(side="right", padx=6)
        self.log_body = tk.Frame(logs, bg=theme.CARD)
        self.log_body.pack(fill="x", padx=14, pady=(0, 10))
        self.log_text = tk.Text(self.log_body, height=4, bg=theme.CARD, fg=theme.MUTED, font=(theme.MONO, 9),
                                borderwidth=0, relief="flat", highlightthickness=0, wrap="word")
        scroll = ttk.Scrollbar(self.log_body, orient="vertical", command=self.log_text.yview)
        self.log_text.configure(yscrollcommand=scroll.set, state="disabled")
        scroll.pack(side="right", fill="y")
        self.log_text.pack(side="left", fill="x", expand=True)

        # --- Écrans ---
        self.pages = [None] * len(self.menu_items)
        self.init_pages()

        # Démarrage sur l'écran Disques ; une seule lecture alimente Disques et Préparation
        self.open_page(PAGE_DISKS)
        self.protocol("WM_DELETE_WINDOW", self.on_close)
        self.after(50, self._drain_ui_queue)
        self.after(200, self.refresh_disks)

    def _drain_ui_queue(self):
        """Exécute les mises à jour d'interface envoyées par les tâches de fond."""
        try:
            while True:
                func, args = _ui_queue.get_nowait()
                try:
                    func(*args)
                except tk.TclError:
                    pass
        except queue.Empty:
            pass
        self.after(50, self._drain_ui_queue)

    def toggle_log(self):
        if self.log_body.winfo_ismapped():
            self.log_body.pack_forget()
            self.log_toggle.config(text=self._("Afficher"))
        else:
            self.log_body.pack(fill="x", padx=14, pady=(0, 10))
            self.log_toggle.config(text=self._("Masquer"))

    # --- Logo ---
    def load_logo_image(self, size):
        try:
            img = Image.open(LOGO_PATH).convert("RGBA").resize((size, size), Image.LANCZOS)
            return ImageTk.PhotoImage(img)
        except Exception:
            img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
            ImageDraw.Draw(img).ellipse((0, 0, size - 1, size - 1), fill=theme.TEAL)
            return ImageTk.PhotoImage(img)

    # --- Navigation ---
    def init_pages(self):
        self.disks = []
        self.format_running = False
        self.pages[PAGE_DISKS] = self.make_disks_page()
        self.pages[PAGE_COPY] = self.make_copy_page()
        self.pages[PAGE_CLONE] = self.make_clone_page()
        self.pages[PAGE_FORMAT] = self.make_format_page()
        self.pages[PAGE_SETTINGS] = self.make_settings_page()

    def open_page(self, idx):
        self.show_page(idx)

    def show_page(self, idx):
        for page in self.pages:
            if page:
                page.place_forget()
        self.pages[idx].place(relx=0.5, rely=0, anchor="n", relwidth=1, relheight=1)
        self.pages[idx].lift()
        for i, nav in enumerate(self.menu_buttons):
            nav.set_active(i == idx)

    # ---------------- Pages ----------------
    def make_disks_page(self):
        frame = CardFrame(self.page_container, bg=theme.CARD)
        head = tk.Frame(frame, bg=theme.CARD)
        head.pack(fill="x", padx=24, pady=(18, 4))
        tk.Label(head, text=self._("Disques"), font=theme.F_TITLE, fg=theme.TEXT, bg=theme.CARD).pack(side="left")
        # Actions toujours visibles, en haut à droite (ordre inverse car side="right")
        self.prepare_this_button = ttk.Button(head, text=self._("Préparer ce disque…"), command=self.prepare_selected_disk)
        self.prepare_this_button.pack(side="right")
        self.open_drive_button = ttk.Button(head, text=self._("Ouvrir le lecteur"), command=self.open_selected_drive)
        self.open_drive_button.pack(side="right", padx=8)
        ttk.Button(head, text=self._("Actualiser"), command=self.refresh_disks).pack(side="right")
        self.open_drive_button.state(["disabled"])
        self.prepare_this_button.state(["disabled"])
        self.overview_status = tk.Label(frame, text="", font=theme.F_BODY, fg=theme.TEXT, bg=theme.CARD, anchor="w")
        self.overview_status.pack(fill="x", padx=24)

        # Liste des disques
        columns = ("num", "name", "media", "bus", "size", "style", "health", "role")
        self.overview_tree = ttk.Treeview(frame, columns=columns, show="headings", height=3, selectmode="browse")
        headings = {
            "num": (self._("N°"), 40), "name": (self._("Modèle"), 180), "media": (self._("Type"), 110),
            "bus": (self._("Connexion"), 90), "size": (self._("Taille"), 72), "style": (self._("Style"), 52),
            "health": (self._("Santé"), 80), "role": (self._("Rôle"), 175),
        }
        for col, (text, width) in headings.items():
            self.overview_tree.heading(col, text=text)
            self.overview_tree.column(col, width=width, anchor="w", stretch=(col == "name"))
        self.overview_tree.tag_configure("attention", foreground=theme.DANGER)
        self.overview_tree.pack(fill="x", padx=24, pady=(4, 8))
        self.overview_tree.bind("<<TreeviewSelect>>", lambda e: self.on_overview_selected())

        # Détail du disque sélectionné
        detail = tk.Frame(frame, bg=theme.CARD)
        detail.pack(fill="x", padx=24)
        self.detail_values = {}
        fields = [
            ("serial", self._("Numéro de série")), ("health", self._("Santé (Windows)")),
            ("temperature", self._("Température")), ("wear", self._("Usure")),
            ("hours", self._("Heures de fonctionnement")), ("errors", self._("Erreurs de lecture non corrigées")),
        ]
        for i, (key, text) in enumerate(fields):
            # Le numéro de série (souvent très long, sans espace) occupe seul la première ligne
            row, col = (0, 0) if i == 0 else divmod(i + 1, 2)
            tk.Label(detail, text=text, font=theme.F_BODY, fg=theme.MUTED, bg=theme.CARD).grid(
                row=row, column=col * 2, sticky="w", padx=(0, 8), pady=1)
            value = tk.Label(detail, text="—", font=theme.F_BODY_BOLD, fg=theme.TEXT, bg=theme.CARD,
                             anchor="w", justify="left")
            value.grid(row=row, column=col * 2 + 1, columnspan=3 if i == 0 else 1, sticky="w", padx=(0, 24), pady=1)
            self.detail_values[key] = value
        detail.grid_columnconfigure(1, weight=1, uniform="valeurs")
        detail.grid_columnconfigure(3, weight=1, uniform="valeurs")
        self.protection_label = tk.Label(frame, text="", font=theme.F_BODY, fg=theme.TEXT, bg=theme.CARD,
                                         anchor="w", justify="left", wraplength=760)
        self.protection_label.pack(fill="x", padx=24, pady=(6, 4))

        # Partitions du disque sélectionné
        pcols = ("num", "letter", "label", "fs", "type", "size", "free", "used")
        self.partition_tree = ttk.Treeview(frame, columns=pcols, show="headings", height=4, selectmode="browse")
        pheadings = {
            "num": (self._("N°"), 40), "letter": (self._("Lecteur"), 72), "label": (self._("Nom"), 130),
            "fs": (self._("Système de fichiers"), 150), "type": (self._("Type"), 90), "size": (self._("Taille"), 80),
            "free": (self._("Libre"), 80), "used": (self._("Occupé"), 70),
        }
        for col, (text, width) in pheadings.items():
            self.partition_tree.heading(col, text=text)
            self.partition_tree.column(col, width=width, anchor="w", stretch=(col == "label"))
        self.partition_tree.pack(fill="x", padx=24, pady=(0, 8))
        self.partition_tree.bind("<<TreeviewSelect>>", lambda e: self._update_overview_buttons())
        self.partition_tree.bind("<Double-1>", lambda e: self.open_selected_drive())
        return frame

    def _fill_overview(self, found, error):
        previous = self.overview_tree.selection()
        self.overview_tree.delete(*self.overview_tree.get_children())
        if error:
            self.overview_status.config(text=self._("Impossible de lire la liste des disques : {error}").format(error=error), fg=theme.DANGER)
            self.on_overview_selected()
            return
        for d in found:
            role = []
            if d.is_system or d.is_boot:
                role.append(self._("Windows"))
            if disks.app_drive_letter() in d.letters:
                role.append("EdenDisk")
            self.overview_tree.insert(
                "", "end", iid=str(d.number), tags=("attention",) if disks.health_needs_attention(d) else (),
                values=(d.number, d.name, self._(disks.MEDIA_LABELS.get(d.media_type or "", "—")),
                        disks.BUS_LABELS.get(d.bus, d.bus or "—"), disks.format_size(d.size), d.style or "—",
                        self._(disks.health_label(d)), ", ".join(role)))
        attention = sum(1 for d in found if disks.health_needs_attention(d))
        text = self._("{count} disque(s) détecté(s).").format(count=len(found))
        if attention:
            text += " " + self._("Attention : Windows signale un problème sur {count} disque(s).").format(count=attention)
        self.overview_status.config(text=text, fg=theme.DANGER if attention else theme.TEXT)
        keep = previous[0] if previous and self.overview_tree.exists(previous[0]) else None
        if keep is None and found:
            keep = str(found[0].number)
        if keep is not None:
            self.overview_tree.selection_set(keep)
        self.on_overview_selected()

    def overview_disk(self):
        sel = self.overview_tree.selection()
        return next((d for d in self.disks if sel and str(d.number) == sel[0]), None)

    def on_overview_selected(self):
        disk = self.overview_disk()
        self.partition_tree.delete(*self.partition_tree.get_children())
        unknown = self._("Non communiqué")
        if disk is None:
            for label in self.detail_values.values():
                label.config(text="—", fg=theme.TEXT)
            self.protection_label.config(text="")
            self._update_overview_buttons()
            return
        values = {
            "serial": disk.serial or unknown,
            "health": self._(disks.health_label(disk)),
            "temperature": f"{disk.temperature} °C" if disk.temperature is not None else unknown,
            "wear": f"{disk.wear} %" if disk.wear is not None else unknown,
            "hours": f"{disk.power_on_hours:,} h".replace(",", " ") if disk.power_on_hours is not None else unknown,
            "errors": str(disk.read_errors) if disk.read_errors is not None else unknown,
        }
        for key, text in values.items():
            alert = (key == "health" and disk.health in ("Warning", "Unhealthy")) or (key == "errors" and bool(disk.read_errors))
            self.detail_values[key].config(text=text, fg=theme.DANGER if alert else theme.TEXT)
        reasons = disks.protection_reasons(disk, disks.system_drive_letter(), disks.app_drive_letter())
        if reasons:
            self.protection_label.config(text=self._("Protégé contre l'effacement : {reasons}.").format(reasons=", ".join(reasons)), fg=theme.MUTED)
        else:
            self.protection_label.config(text=self._("Ce disque peut être préparé (effacé puis formaté)."), fg=theme.MUTED)
        for p in disk.partitions:
            self.partition_tree.insert("", "end", iid=str(p.number), values=(
                p.number, f"{p.letter}:" if p.letter else "", p.label or "", p.file_system or "", p.type or "",
                disks.format_size(p.size), disks.format_size(p.free) if p.free is not None else "",
                f"{p.used_percent} %" if p.used_percent is not None else ""))
        self._update_overview_buttons()

    def _selected_partition(self):
        disk, sel = self.overview_disk(), self.partition_tree.selection()
        if disk is None or not sel:
            return None
        return next((p for p in disk.partitions if str(p.number) == sel[0]), None)

    def _update_overview_buttons(self):
        part = self._selected_partition()
        self.open_drive_button.state(["!disabled"] if part is not None and part.letter else ["disabled"])
        disk = self.overview_disk()
        allowed = disk is not None and not disks.protection_reasons(disk, disks.system_drive_letter(), disks.app_drive_letter())
        self.prepare_this_button.state(["!disabled"] if allowed and not self.format_running else ["disabled"])

    def open_selected_drive(self):
        part = self._selected_partition()
        if part is not None and part.letter:
            os.startfile(f"{part.letter}:\\")

    def prepare_selected_disk(self):
        disk = self.overview_disk()
        if disk is None or not self.disk_tree.exists(str(disk.number)):
            return
        self.open_page(PAGE_FORMAT)
        self.disk_tree.selection_set(str(disk.number))
        self.disk_tree.see(str(disk.number))
        self.on_disk_selected()

    def make_copy_page(self):
        frame = CardFrame(self.page_container, bg=theme.CARD)
        theme.page_header(frame, self._("Transfert des données"),
                          self._("Copie les dossiers des profils utilisateurs d'un disque (par exemple l'ancien PC branché en USB) vers un dossier. Rien n'est supprimé ; un transfert interrompu peut être relancé."))

        # Source
        src_row = tk.Frame(frame, bg=theme.CARD)
        src_row.pack(fill="x", padx=24, pady=2)
        tk.Label(src_row, text=self._("Disque source :"), font=theme.F_BODY, fg=theme.TEXT, bg=theme.CARD, width=16, anchor="w").pack(side="left")
        self.transfer_src_combo = ttk.Combobox(src_row, values=list_drives_with_labels(), state="readonly", width=40)
        self.transfer_src_combo.pack(side="left")
        self.transfer_src_combo.bind("<<ComboboxSelected>>", lambda e: self.load_profiles())

        # Profils (à gauche) et dossiers (à droite)
        middle = tk.Frame(frame, bg=theme.CARD)
        middle.pack(fill="x", padx=24, pady=(10, 4))
        left = tk.Frame(middle, bg=theme.CARD)
        left.pack(side="left", fill="both", expand=True)
        tk.Label(left, text=self._("Profils (cliquez pour cocher ou décocher)"), font=theme.F_BODY_BOLD,
                 fg=theme.TEXT, bg=theme.CARD).pack(anchor="w")
        self.profile_tree = ttk.Treeview(left, columns=("check", "name"), show="", height=3, selectmode="none")
        self.profile_tree.column("check", width=30, anchor="center", stretch=False)
        self.profile_tree.column("name", width=260, anchor="w")
        self.profile_tree.pack(fill="both", expand=True, pady=(2, 0))
        self.profile_tree.bind("<Button-1>", self._toggle_profile)

        right = tk.Frame(middle, bg=theme.CARD)
        right.pack(side="left", fill="y", padx=(24, 0))
        tk.Label(right, text=self._("Dossiers à copier"), font=theme.F_BODY_BOLD, fg=theme.TEXT, bg=theme.CARD).grid(row=0, column=0, columnspan=2, sticky="w")
        self.folder_vars = {}
        for i, (key, label) in enumerate(transfer.STANDARD_FOLDERS):
            var = tk.BooleanVar(value=True)
            self.folder_vars[key] = var
            ttk.Checkbutton(right, text=self._(label), variable=var, command=self._invalidate_analysis).grid(row=1 + i // 2, column=i % 2, sticky="w", padx=(0, 16))
        self.onedrive_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(right, text=self._("Dossier OneDrive (fichiers présents sur le disque uniquement)"),
                        variable=self.onedrive_var,
                        command=self._invalidate_analysis).grid(row=5, column=0, columnspan=2, sticky="w", pady=(6, 0))
        for child in right.grid_slaves():
            child.grid_configure(pady=(child.grid_info().get("pady") or 1))

        # Destination
        dst_row = tk.Frame(frame, bg=theme.CARD)
        dst_row.pack(fill="x", padx=24, pady=4)
        tk.Label(dst_row, text=self._("Destination :"), font=theme.F_BODY, fg=theme.TEXT, bg=theme.CARD, width=16, anchor="w").pack(side="left")
        self.copy_dst_var = tk.StringVar()
        ttk.Entry(dst_row, textvariable=self.copy_dst_var, state="readonly").pack(side="left", fill="x", expand=True)
        ttk.Button(dst_row, text=self._("Parcourir…"), command=self.browse_copy_dst).pack(side="left", padx=(8, 0))

        # Analyse et actions
        self.transfer_summary = tk.Label(frame, text=self._("Choisissez le disque source, les profils et la destination, puis cliquez sur Analyser."),
                                         font=theme.F_BODY, fg=theme.TEXT, bg=theme.CARD, wraplength=820, justify="left", anchor="w")
        self.transfer_summary.pack(fill="x", padx=24, pady=(10, 4))
        actions = tk.Frame(frame, bg=theme.CARD)
        actions.pack(fill="x", padx=24, pady=4)
        self.analyse_button = ttk.Button(actions, text=self._("Analyser"), command=self.analyse_transfer)
        self.analyse_button.pack(side="left")
        self.start_transfer_button = ttk.Button(actions, text=self._("Démarrer le transfert"), style="Accent.TButton",
                                                command=self.start_transfer)
        self.start_transfer_button.pack(side="left", padx=8)
        self.stop_transfer_button = ttk.Button(actions, text=self._("Arrêter"), command=self.stop_transfer)
        self.stop_transfer_button.pack(side="left")
        self.open_report_button = ttk.Button(actions, text=self._("Ouvrir le rapport"), command=self.open_transfer_report)
        self.open_report_button.pack(side="right")
        for b in (self.start_transfer_button, self.stop_transfer_button, self.open_report_button):
            b.state(["disabled"])
        # État du transfert, dans la rangée des boutons pour rester visible
        self.copy_progress_label = tk.Label(actions, text="", fg=theme.TEXT, bg=theme.CARD, font=theme.F_BODY, anchor="w")
        self.copy_progress_label.pack(side="left", fill="x", expand=True, padx=12)

        self.copy_progress = ttk.Progressbar(frame, mode="determinate")
        self.copy_progress.pack(fill="x", padx=24, pady=(8, 16))

        self.transfer_profiles = []
        self.transfer_checked = set()
        self.transfer_plan = []
        self.transfer_running = False
        self.transfer_cancel = threading.Event()
        self.transfer_report = None
        return frame

    # --- Transfert des données ---
    def _invalidate_analysis(self):
        self.transfer_plan = []
        if not self.transfer_running:
            self.start_transfer_button.state(["disabled"])

    def load_profiles(self):
        letter = extract_drive_letter(self.transfer_src_combo.get())
        self.profile_tree.delete(*self.profile_tree.get_children())
        self._invalidate_analysis()
        if not letter:
            return
        self.transfer_summary.config(text=self._("Recherche des profils…"), fg=theme.TEXT)

        def task():
            found = transfer.find_profiles(f"{letter}:\\")
            run_on_ui(self._show_profiles, letter, found)

        threading.Thread(target=task, daemon=True).start()

    def _show_profiles(self, letter, found):
        self.transfer_profiles = found
        self.transfer_checked = {p.name for p in found}
        for p in found:
            self.profile_tree.insert("", "end", iid=p.name, values=("☑", p.name))
        if not found:
            self.transfer_summary.config(text=self._("Aucun profil utilisateur trouvé dans {drive}:\\Users.").format(drive=letter), fg=theme.DANGER)
        else:
            self.transfer_summary.config(text=self._("{count} profil(s) trouvé(s). Choisissez la destination puis cliquez sur Analyser.").format(count=len(found)), fg=theme.TEXT)

    def _toggle_profile(self, event):
        iid = self.profile_tree.identify_row(event.y)
        if not iid or self.transfer_running:
            return "break"
        if iid in self.transfer_checked:
            self.transfer_checked.discard(iid)
            self.profile_tree.set(iid, "check", "☐")
        else:
            self.transfer_checked.add(iid)
            self.profile_tree.set(iid, "check", "☑")
        self._invalidate_analysis()
        return "break"

    def browse_copy_dst(self):
        folder = filedialog.askdirectory()
        if folder:
            self.copy_dst_var.set(os.path.normpath(folder))
            self._invalidate_analysis()

    def _build_plan(self):
        """Liste (profil, libellé, source, destination) selon les cases cochées."""
        labels = dict(transfer.STANDARD_FOLDERS)
        dst_root = Path(self.copy_dst_var.get())
        plan = []
        for p in self.transfer_profiles:
            if p.name not in self.transfer_checked:
                continue
            for key, path in p.folders.items():
                if self.folder_vars[key].get():
                    plan.append((p.name, labels[key], path, dst_root / p.name / labels[key]))
            if self.onedrive_var.get():
                for od in p.onedrive:
                    plan.append((p.name, od.name, od, dst_root / p.name / od.name))
        return plan

    def analyse_transfer(self):
        if self.transfer_running:
            return
        if not self.copy_dst_var.get():
            messagebox.showerror(self._("Erreur"), self._("Choisissez d'abord le dossier de destination."))
            return
        plan = self._build_plan()
        if not plan:
            messagebox.showerror(self._("Erreur"), self._("Aucun dossier à copier : cochez au moins un profil et un dossier."))
            return
        problem = transfer.destination_problem([item[2] for item in plan], Path(self.copy_dst_var.get()))
        if problem:
            messagebox.showerror(self._("Destination refusée"), problem)
            return
        self.analyse_button.state(["disabled"])
        self.start_transfer_button.state(["disabled"])
        self.transfer_summary.config(text=self._("Analyse en cours (calcul de la taille)…"), fg=theme.TEXT)

        def task():
            scanned = [(item, transfer.scan(item[2])) for item in plan]
            free = transfer.free_space(Path(self.copy_dst_var.get()))
            run_on_ui(self._show_analysis, scanned, free)

        threading.Thread(target=task, daemon=True).start()

    def _show_analysis(self, scanned, free):
        self.analyse_button.state(["!disabled"])
        files = sum(r.files for _, r in scanned)
        size = sum(r.bytes for _, r in scanned)
        cloud = sum(r.cloud_only for _, r in scanned)
        text = self._("{files} fichiers, {size} à copier ({folders} dossiers). Espace libre sur la destination : {free}.").format(
            files=f"{files:,}".replace(",", " "), size=disks.format_size(size), folders=len(scanned), free=disks.format_size(free))
        if cloud:
            text += " " + self._("{count} fichier(s) OneDrive « en ligne uniquement » ne seront pas copiés.").format(count=cloud)
        enough = size < free
        if not enough:
            text += " " + self._("Espace insuffisant sur la destination.")
        self.transfer_summary.config(text=text, fg=theme.TEXT if enough else theme.DANGER)
        self.transfer_plan = scanned if enough else []
        self.start_transfer_button.state(["!disabled"] if enough and files + cloud > 0 else ["disabled"])
        log_message(self.log_text, text)

    def start_transfer(self):
        if not self.transfer_plan or self.transfer_running:
            return
        plan = self.transfer_plan
        dst_root = Path(self.copy_dst_var.get())
        source = self.transfer_src_combo.get()
        started = datetime.datetime.now()
        report_dir = dst_root / f"EdenDisk-transfert-{started:%Y%m%d-%H%M}"
        total = max(1, sum(r.files for _, r in plan))
        self.transfer_running = True
        self.transfer_cancel.clear()
        for b in (self.analyse_button, self.start_transfer_button, self.open_report_button):
            b.state(["disabled"])
        self.stop_transfer_button.state(["!disabled"])
        self.copy_progress.config(maximum=total, value=0)
        log_message(self.log_text, self._("Transfert démarré vers {dst}.").format(dst=dst_root))

        def task():
            results, done = [], [0]
            for index, ((profile, label, src, dst), planned) in enumerate(plan, start=1):
                result = transfer.FolderResult(profile, label, src, dst, planned)
                results.append(result)
                if self.transfer_cancel.is_set():
                    continue
                run_on_ui(self.copy_progress_label.config,
                          {"text": self._("{profile} / {folder} ({index}/{count})").format(profile=profile, folder=label, index=index, count=len(plan))})

                def on_file():
                    done[0] += 1
                    if done[0] % 25 == 0:
                        run_on_ui(self.copy_progress.config, {"value": min(done[0], total)})

                log_file = report_dir / f"{index:02d} {profile} - {label}.log"
                result.exit_code = transfer.run_robocopy(src, dst, log_file, on_file, self.transfer_cancel)
                try:
                    result.errors = transfer.parse_errors(log_file.read_text(encoding="utf-16"))
                except OSError:
                    pass
                ok, text = (False, self._("arrêté")) if result.exit_code < 0 else transfer.interpret_exit_code(result.exit_code)
                log_message(self.log_text, f"{profile} / {label} : {text}" + (f" ({len(result.errors)} erreur(s))" if result.errors else ""))
            report = transfer.write_report(report_dir / "Rapport de transfert.txt", source, dst_root, results, started,
                                           datetime.datetime.now(), self.transfer_cancel.is_set(), disks.format_size)
            run_on_ui(self._transfer_done, results, report)

        threading.Thread(target=task, daemon=True).start()

    def stop_transfer(self):
        if self.transfer_running:
            self.transfer_cancel.set()
            self.stop_transfer_button.state(["disabled"])
            log_message(self.log_text, self._("Arrêt demandé…"))

    def _transfer_done(self, results, report):
        self.transfer_running = False
        self.transfer_report = report
        self.copy_progress.config(value=self.copy_progress["maximum"] if not self.transfer_cancel.is_set() else self.copy_progress["value"])
        self.stop_transfer_button.state(["disabled"])
        self.analyse_button.state(["!disabled"])
        self.open_report_button.state(["!disabled"])
        errors = sum(len(r.errors) for r in results)
        if self.transfer_cancel.is_set():
            text = self._("Transfert interrompu. Relancez-le pour reprendre : les fichiers déjà copiés seront ignorés.")
        elif errors or not all(r.ok for r in results):
            text = self._("Transfert terminé avec {count} fichier(s) non copié(s) : voir le rapport.").format(count=errors)
        else:
            text = self._("Transfert terminé sans erreur.")
        self.copy_progress_label.config(text=text)
        self.transfer_summary.config(text=self._("Rapport : {path}").format(path=report), fg=theme.TEXT)
        log_message(self.log_text, text)
        messagebox.showinfo(self._("Transfert des données"), text)

    def open_transfer_report(self):
        if self.transfer_report and Path(self.transfer_report).exists():
            os.startfile(self.transfer_report)

    def make_clone_page(self):
        frame = CardFrame(self.page_container)
        theme.page_header(frame, self._("Copie complète d'un lecteur"),
                          self._("Copie tous les fichiers d'un lecteur dans un dossier (sauvegarde avant intervention, par exemple). Les fichiers système de Windows sont ignorés. Le résultat n'est pas un disque démarrable : ce n'est pas un clonage."))
        body = tk.Frame(frame, bg=theme.CARD)
        body.pack(fill="x", padx=24)
        theme.label(body, self._("Lecteur à copier")).grid(row=0, column=0, sticky="w", pady=6)
        self.clone_src_combo = ttk.Combobox(body, values=list_drives_with_labels(), state="readonly", width=40)
        self.clone_src_combo.grid(row=0, column=1, sticky="w", pady=6)
        self.clone_src_combo.bind("<<ComboboxSelected>>", lambda e: self._invalidate_clone())
        theme.label(body, self._("Dossier de destination")).grid(row=1, column=0, sticky="w", pady=6, padx=(0, 16))
        self.clone_dst_var = tk.StringVar()
        dst_row = tk.Frame(body, bg=theme.CARD)
        dst_row.grid(row=1, column=1, sticky="we", pady=6)
        ttk.Entry(dst_row, textvariable=self.clone_dst_var, state="readonly").pack(side="left", fill="x", expand=True)
        ttk.Button(dst_row, text=self._("Parcourir…"), command=self.browse_clone_dst).pack(side="left", padx=(8, 0))
        body.grid_columnconfigure(1, weight=1)

        self.clone_summary = theme.label(frame, self._("Choisissez le lecteur et le dossier de destination, puis cliquez sur Analyser."),
                                         wraplength=840, justify="left")
        self.clone_summary.pack(fill="x", padx=24, pady=(14, 6))
        actions = tk.Frame(frame, bg=theme.CARD)
        actions.pack(fill="x", padx=24, pady=4)
        self.clone_analyse_button = ttk.Button(actions, text=self._("Analyser"), command=self.analyse_clone)
        self.clone_analyse_button.pack(side="left")
        self.clone_start_button = ttk.Button(actions, text=self._("Démarrer la copie"), style="Accent.TButton", command=self.start_clone)
        self.clone_start_button.pack(side="left", padx=8)
        self.clone_stop_button = ttk.Button(actions, text=self._("Arrêter"), command=self.stop_clone)
        self.clone_stop_button.pack(side="left")
        self.clone_report_button = ttk.Button(actions, text=self._("Ouvrir le rapport"), command=self.open_clone_report)
        self.clone_report_button.pack(side="right")
        self.clone_status = theme.label(actions, "")
        self.clone_status.pack(side="left", fill="x", expand=True, padx=12)
        for b in (self.clone_start_button, self.clone_stop_button, self.clone_report_button):
            b.state(["disabled"])
        self.clone_progress = ttk.Progressbar(frame, mode="determinate")
        self.clone_progress.pack(fill="x", padx=24, pady=(8, 16))

        self.clone_plan = None
        self.clone_running = False
        self.clone_cancel = threading.Event()
        self.clone_report = None
        return frame

    # --- Copie complète d'un lecteur ---
    def _invalidate_clone(self):
        self.clone_plan = None
        if not self.clone_running:
            self.clone_start_button.state(["disabled"])

    def browse_clone_dst(self):
        folder = filedialog.askdirectory()
        if folder:
            self.clone_dst_var.set(os.path.normpath(folder))
            self._invalidate_clone()

    def analyse_clone(self):
        letter = extract_drive_letter(self.clone_src_combo.get())
        dst = self.clone_dst_var.get()
        if not letter or not dst:
            messagebox.showerror(self._("Erreur"), self._("Choisissez le lecteur à copier et le dossier de destination."))
            return
        src = Path(f"{letter}:\\")
        problem = transfer.destination_problem([src], Path(dst))
        if problem:
            messagebox.showerror(self._("Destination refusée"), problem)
            return
        self.clone_analyse_button.state(["disabled"])
        self.clone_summary.config(text=self._("Analyse en cours (calcul de la taille)…"), fg=theme.TEXT)

        def task():
            result = transfer.scan(src, whole_drive=True)
            run_on_ui(self._show_clone_analysis, src, Path(dst), result, transfer.free_space(Path(dst)))

        threading.Thread(target=task, daemon=True).start()

    def _show_clone_analysis(self, src, dst, result, free):
        self.clone_analyse_button.state(["!disabled"])
        text = self._("{files} fichiers, {size} à copier. Espace libre sur la destination : {free}.").format(
            files=f"{result.files:,}".replace(",", " "), size=disks.format_size(result.bytes), free=disks.format_size(free))
        if result.unreadable:
            text += " " + self._("{count} dossier(s) illisible(s) seront ignorés (droits d'accès).").format(count=result.unreadable)
        enough = result.bytes < free
        if not enough:
            text += " " + self._("Espace insuffisant sur la destination.")
        self.clone_summary.config(text=text, fg=theme.TEXT if enough else theme.DANGER)
        self.clone_plan = (src, dst, result) if enough else None
        self.clone_start_button.state(["!disabled"] if enough and result.files else ["disabled"])
        log_message(self.log_text, text)

    def start_clone(self):
        if not self.clone_plan or self.clone_running:
            return
        src, dst_root, planned = self.clone_plan
        started = datetime.datetime.now()
        label = f"{src.drive}"
        target = dst_root / f"Copie {src.drive.rstrip(':')} {started:%Y-%m-%d %H%M}"
        report_dir = target / "_EdenDisk"
        total = max(1, planned.files)
        self.clone_running = True
        self.clone_cancel.clear()
        for b in (self.clone_analyse_button, self.clone_start_button, self.clone_report_button):
            b.state(["disabled"])
        self.clone_stop_button.state(["!disabled"])
        self.clone_progress.config(maximum=total, value=0)
        self.clone_status.config(text=self._("Copie en cours…"))
        log_message(self.log_text, self._("Copie de {src} vers {dst}.").format(src=src, dst=target))

        def task():
            done = [0]

            def on_file():
                done[0] += 1
                if done[0] % 25 == 0:
                    run_on_ui(self.clone_progress.config, {"value": min(done[0], total)})

            log_file = report_dir / "robocopy.log"
            result = transfer.FolderResult(self._("Lecteur"), label, src, target, planned)
            # Le dossier _EdenDisk (rapport) est exclu pour ne pas se copier lui-même si la source est relue
            result.exit_code = transfer.run_robocopy(src, target, log_file, on_file, self.clone_cancel,
                                                     extra=transfer.drive_exclusions(src))
            try:
                result.errors = transfer.parse_errors(log_file.read_text(encoding="utf-16"))
            except OSError:
                pass
            report = transfer.write_report(report_dir / "Rapport de copie.txt", str(src), target, [result], started,
                                           datetime.datetime.now(), self.clone_cancel.is_set(), disks.format_size)
            run_on_ui(self._clone_done, result, report)

        threading.Thread(target=task, daemon=True).start()

    def stop_clone(self):
        if self.clone_running:
            self.clone_cancel.set()
            self.clone_stop_button.state(["disabled"])
            log_message(self.log_text, self._("Arrêt demandé…"))

    def _clone_done(self, result, report):
        self.clone_running = False
        self.clone_report = report
        if not self.clone_cancel.is_set():
            self.clone_progress.config(value=self.clone_progress["maximum"])
        self.clone_stop_button.state(["disabled"])
        self.clone_analyse_button.state(["!disabled"])
        self.clone_report_button.state(["!disabled"])
        if self.clone_cancel.is_set():
            text = self._("Copie interrompue. Relancez-la pour reprendre : les fichiers déjà copiés seront ignorés.")
        elif result.errors or not result.ok:
            text = self._("Copie terminée avec {count} fichier(s) non copié(s) : voir le rapport.").format(count=len(result.errors))
        else:
            text = self._("Copie terminée sans erreur.")
        self.clone_status.config(text=text)
        self.clone_summary.config(text=self._("Rapport : {path}").format(path=report), fg=theme.TEXT)
        log_message(self.log_text, text)
        messagebox.showinfo(self._("Copie complète d'un lecteur"), text)

    def open_clone_report(self):
        if self.clone_report and Path(self.clone_report).exists():
            os.startfile(self.clone_report)

    def make_format_page(self):
        frame = CardFrame(self.page_container, bg=theme.CARD)
        theme.page_header(frame, self._("Préparation d'un disque"),
                          self._("Efface entièrement le disque choisi (toutes ses partitions), puis crée une partition unique formatée."),
                          warning=True)

        # Liste des disques physiques
        list_frame = tk.Frame(frame, bg=theme.CARD)
        list_frame.pack(fill="both", expand=True, padx=24)
        columns = ("num", "name", "size", "bus", "style", "letters", "state")
        self.disk_tree = ttk.Treeview(list_frame, columns=columns, show="headings", height=5, selectmode="browse")
        headings = {
            "num": (self._("N°"), 40), "name": (self._("Modèle"), 220), "size": (self._("Taille"), 80),
            "bus": (self._("Connexion"), 96), "style": (self._("Style"), 60), "letters": (self._("Lecteurs"), 80),
            "state": (self._("État"), 260),
        }
        for col, (text, width) in headings.items():
            self.disk_tree.heading(col, text=text)
            self.disk_tree.column(col, width=width, anchor="w", stretch=(col in ("name", "state")))
        self.disk_tree.tag_configure("protected", foreground=theme.SUBTLE)
        self.disk_tree.pack(side="left", fill="both", expand=True)
        self.disk_tree.bind("<<TreeviewSelect>>", lambda e: self.on_disk_selected())

        tools = tk.Frame(frame, bg=theme.CARD)
        tools.pack(fill="x", padx=24, pady=(6, 0))
        ttk.Button(tools, text=self._("Actualiser la liste"), command=self.refresh_disks).pack(side="left")

        # Ce qui sera effacé / pourquoi c'est refusé
        self.disk_detail_label = tk.Label(frame, text="", font=theme.F_BODY, fg=theme.TEXT, bg=theme.CARD,
                                          justify="left", anchor="w", wraplength=760)
        self.disk_detail_label.pack(fill="x", padx=24, pady=6)

        # Options
        opts = tk.Frame(frame, bg=theme.CARD)
        opts.pack(fill="x", padx=24, pady=4)
        tk.Label(opts, text=self._("Système de fichiers :"), font=theme.F_BODY, fg=theme.TEXT, bg=theme.CARD).grid(row=0, column=0, sticky="w")
        self.fs_combo = ttk.Combobox(opts, values=list(disks.FILE_SYSTEMS), state="readonly", width=10)
        self.fs_combo.current(0)
        self.fs_combo.grid(row=0, column=1, padx=(6, 24), sticky="w")
        tk.Label(opts, text=self._("Style de partition :"), font=theme.F_BODY, fg=theme.TEXT, bg=theme.CARD).grid(row=0, column=2, sticky="w")
        self.convert_combo = ttk.Combobox(opts, values=list(disks.PARTITION_STYLES), state="readonly", width=8)
        self.convert_combo.current(0)
        self.convert_combo.grid(row=0, column=3, padx=(6, 24), sticky="w")
        tk.Label(opts, text=self._("Nom du volume :"), font=theme.F_BODY, fg=theme.TEXT, bg=theme.CARD).grid(row=0, column=4, sticky="w")
        self.label_entry = ttk.Entry(opts, width=20)
        self.label_entry.insert(0, "EdenDisk")
        self.label_entry.grid(row=0, column=5, padx=6, sticky="w")

        # Progression (durée inconnue : barre animée)
        self.format_progress = ttk.Progressbar(frame, mode="determinate", value=0)
        self.format_progress.pack(fill="x", padx=24, pady=(10, 4))

        self.format_button = ttk.Button(frame, text=self._("Effacer et préparer le disque…"), style="Danger.TButton", command=self.start_format_convert)
        self.format_button.pack(pady=10)
        self.format_button.state(["disabled"])

        return frame

    # --- Préparation de disque ---
    def refresh_disks(self):
        if self.format_running:
            return
        self.disk_detail_label.config(text=self._("Lecture des disques…"), fg=theme.TEXT)
        self.format_button.state(["disabled"])
        self.overview_status.config(text=self._("Lecture des disques…"), fg=theme.TEXT)

        def task():
            try:
                found, error = disks.list_disks(), None
            except Exception as e:  # PowerShell indisponible, délai dépassé…
                found, error = [], str(e)
            run_on_ui(self._show_disks, found, error)

        threading.Thread(target=task, daemon=True).start()

    def _show_disks(self, found, error):
        self.disks = found
        self._fill_overview(found, error)
        self.disk_tree.delete(*self.disk_tree.get_children())
        if error:
            self.disk_detail_label.config(text=self._("Impossible de lire la liste des disques : {error}").format(error=error), fg=theme.DANGER)
            return
        sys_letter, app_letter = disks.system_drive_letter(), disks.app_drive_letter()
        for d in found:
            reasons = disks.protection_reasons(d, sys_letter, app_letter)
            state = self._("Protégé : {reasons}").format(reasons=", ".join(reasons)) if reasons else self._("Peut être préparé")
            self.disk_tree.insert("", "end", iid=str(d.number), tags=("protected",) if reasons else (),
                                  values=(d.number, d.name, disks.format_size(d.size), d.bus, d.style,
                                          " ".join(f"{l}:" for l in d.letters), state))
        self.disk_detail_label.config(text=self._("Sélectionnez le disque à préparer."), fg=theme.TEXT)
        log_message(self.log_text, self._("{count} disque(s) détecté(s).").format(count=len(found)))

    def selected_disk(self):
        sel = self.disk_tree.selection()
        if not sel:
            return None
        return next((d for d in self.disks if str(d.number) == sel[0]), None)

    def on_disk_selected(self):
        disk = self.selected_disk()
        if disk is None or self.format_running:
            return
        reasons = disks.protection_reasons(disk, disks.system_drive_letter(), disks.app_drive_letter())
        if reasons:
            self.format_button.state(["disabled"])
            self.disk_detail_label.config(
                text=self._("Ce disque ne peut pas être préparé : {reasons}.").format(reasons=", ".join(reasons)), fg=theme.DANGER)
            return
        content = "\n".join("  • " + p.describe() for p in disk.partitions) or "  • " + self._("aucune partition")
        self.disk_detail_label.config(
            text=self._("Sera entièrement effacé : disque {num} — {name} ({size})").format(
                num=disk.number, name=disk.name, size=disks.format_size(disk.size)) + "\n" + content,
            fg=theme.TEXT)
        self.format_button.state(["!disabled"])

    def confirm_erase(self, disk):
        """Fenêtre de confirmation : il faut taper le numéro du disque pour valider."""
        win = tk.Toplevel(self)
        win.title(self._("Confirmer l'effacement"))
        win.transient(self)
        win.resizable(False, False)
        win.configure(bg=theme.CARD)
        body = tk.Frame(win, padx=24, pady=20, bg=theme.CARD)
        body.pack()
        tk.Label(body, text=self._("Toutes les données du disque suivant seront définitivement effacées :"),
                 font=(theme.FONT, 11, "bold"), fg=theme.DANGER, bg=theme.CARD, justify="left").pack(anchor="w")
        lines = [self._("Disque {num} — {name} ({size}, {bus})").format(
            num=disk.number, name=disk.name, size=disks.format_size(disk.size), bus=disk.bus)]
        lines += ["  • " + p.describe() for p in disk.partitions]
        tk.Label(body, text="\n".join(lines), font=theme.F_BODY, fg=theme.TEXT, bg=theme.CARD,
                 justify="left").pack(anchor="w", pady=10)
        tk.Label(body, text=self._("Pour confirmer, tapez le numéro du disque ({num}) :").format(num=disk.number),
                 font=theme.F_BODY, fg=theme.TEXT, bg=theme.CARD).pack(anchor="w")
        typed = tk.StringVar()
        entry = ttk.Entry(body, textvariable=typed, width=10)
        entry.pack(anchor="w", pady=6)
        result = {"ok": False}
        buttons = tk.Frame(body, bg=theme.CARD)
        buttons.pack(fill="x", pady=(10, 0))
        erase_btn = ttk.Button(buttons, text=self._("Effacer le disque {num}").format(num=disk.number), style="Danger.TButton",
                               command=lambda: (result.update(ok=True), win.destroy()))
        erase_btn.pack(side="right")
        erase_btn.state(["disabled"])
        ttk.Button(buttons, text=self._("Annuler"), command=win.destroy).pack(side="right", padx=8)
        typed.trace_add("write", lambda *a: erase_btn.state(
            ["!disabled"] if typed.get().strip() == str(disk.number) else ["disabled"]))
        entry.focus_set()
        win.bind("<Escape>", lambda e: win.destroy())
        win.grab_set()
        self.wait_window(win)
        return result["ok"]

    def start_format_convert(self):
        disk = self.selected_disk()
        if disk is None:
            messagebox.showerror(self._("Erreur"), self._("Veuillez sélectionner le disque à préparer."))
            return
        fs, style = self.fs_combo.get(), self.convert_combo.get()
        label = self.label_entry.get().strip() or "EdenDisk"
        reasons = disks.protection_reasons(disk, disks.system_drive_letter(), disks.app_drive_letter())
        errors = disks.validate_options(disk, fs, label, style)
        if reasons:
            messagebox.showerror(self._("Opération refusée"), ", ".join(reasons))
            return
        if errors:
            messagebox.showerror(self._("Options invalides"), "\n".join(errors))
            return
        if not self.confirm_erase(disk):
            log_message(self.log_text, self._("Préparation annulée."))
            return

        self.format_running = True
        self.format_button.state(["disabled"])
        self.format_progress.config(mode="indeterminate")
        self.format_progress.start(12)
        log_message(self.log_text, self._("Préparation du disque {num} ({name}) : {style}, {fs}, « {label} »…").format(
            num=disk.number, name=disk.name, style=style, fs=fs, label=label))

        def task():
            result = disks.prepare_disk(disk, fs, label, style)
            run_on_ui(self._format_done, result)

        threading.Thread(target=task, daemon=True).start()

    def _format_done(self, result):
        self.format_running = False
        self.format_progress.stop()
        self.format_progress.config(mode="determinate", value=0)
        if result.ok:
            where = self._(" Nouveau lecteur : {letter}:").format(letter=result.letter) if result.letter else ""
            log_message(self.log_text, self._("Disque préparé avec succès.") + where)
            messagebox.showinfo(self._("Terminé"), self._("Disque préparé avec succès.") + where)
        else:
            log_message(self.log_text, result.message)
            messagebox.showerror(self._("Échec"), result.message)
        self.refresh_disks()

    def make_settings_page(self):
        frame = CardFrame(self.page_container)
        theme.page_header(frame, self._("Paramètres"))

        lang = tk.Frame(frame, bg=theme.CARD)
        lang.pack(fill="x", padx=24, pady=(0, 18))
        theme.label(lang, self._("Langue de l'application"), bold=True).pack(fill="x")
        theme.label(lang, self._("Le changement s'applique au prochain démarrage d'EdenDisk."), muted=True).pack(fill="x", pady=(0, 6))
        row = tk.Frame(lang, bg=theme.CARD)
        row.pack(fill="x")
        current_language = load_preferences().get("language", "fr")
        self.lang_combo = ttk.Combobox(row, values=[f"{v} ({k})" for k, v in LANGUAGES.items()], state="readonly", width=24)
        for idx, val in enumerate(self.lang_combo["values"]):
            if f"{LANGUAGES.get(current_language, 'Français')} ({current_language})" == val:
                self.lang_combo.current(idx)
                break
        self.lang_combo.pack(side="left")
        ttk.Button(row, text=self._("Enregistrer"), style="Accent.TButton", command=self.save_settings).pack(side="left", padx=10)

        tk.Frame(frame, bg=theme.BORDER, height=1).pack(fill="x", padx=24, pady=(0, 18))

        about = tk.Frame(frame, bg=theme.CARD)
        about.pack(fill="x", padx=24)
        theme.label(about, self._("À propos"), bold=True).pack(fill="x")
        theme.label(about, f"EdenDisk {APP_VERSION}").pack(fill="x", pady=(4, 0))
        theme.label(about, self._("Logiciel gratuit, sans inscription ni clé de licence."), muted=True).pack(fill="x")
        theme.label(about, self._("Développé et distribué par AKM12 — Advanced Knowledge & Maintenance."), muted=True).pack(fill="x")
        link = tk.Label(about, text=FICHE_URL, bg=theme.CARD, fg=theme.TEAL, font=(theme.FONT, 10, "underline"),
                        cursor="hand2", anchor="w")
        link.pack(fill="x", pady=(6, 0))
        link.bind("<Button-1>", lambda e: webbrowser.open_new(FICHE_URL))
        return frame

    # ---------------- Paramètres ----------------
    def save_settings(self):
        sel = self.lang_combo.get()
        code = None
        for k, v in LANGUAGES.items():
            if f"{v} ({k})" == sel:
                code = k
                break
        current_language = load_preferences().get("language", "fr")
        if code and code != current_language:
            config = load_preferences()
            config["language"] = code
            try:
                save_preferences(config)
            except OSError as e:
                messagebox.showerror(self._("Erreur"), str(e))
                return
            messagebox.showinfo(
                self._("Info"),
                self._("Langue modifiée avec succès.\nRedémarrez l'application pour appliquer les changements.")
            )
        else:
            messagebox.showinfo(self._("Info"), self._("Aucune modification effectuée."))

    # ---------------- Divers ----------------
    def clear_log(self):
        self.log_text.config(state="normal")
        self.log_text.delete("1.0", tk.END)
        self.log_text.config(state="disabled")

    def on_close(self):
        if messagebox.askyesno(self._("Quitter"), self._("Êtes-vous sûr de vouloir quitter ?")):
            self.destroy()