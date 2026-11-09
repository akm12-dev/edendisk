import os, sys, shutil, re, ctypes, win32api, json, gettext
from tkinter import messagebox

# ---------------- Config & traduction ----------------
CONFIG_NAME = "config.json"
LANGUAGES = {"fr": "Français", "en": "English"}
LANG_DIR = os.path.join(os.path.dirname(__file__), "locale")
DEFAULT_PREFERENCES = {"language": "fr"}


def config_path():
    """Préférences dans %APPDATA%\EdenDisk : inscriptible même quand EdenDisk est installé dans Program Files."""
    base = os.environ.get("APPDATA") or os.path.expanduser("~")
    return os.path.join(base, "EdenDisk", CONFIG_NAME)


def _legacy_paths():
    """Emplacements des versions 2.0.0 et antérieures (dossier courant ou dossier de l'exécutable)."""
    exe_dir = os.path.dirname(sys.executable) if getattr(sys, "frozen", False) else os.path.dirname(os.path.abspath(__file__))
    return [os.path.join(os.getcwd(), CONFIG_NAME), os.path.join(exe_dir, CONFIG_NAME)]


def _read(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else None
    except (OSError, ValueError):
        return None


def load_preferences():
    for path in [config_path(), *_legacy_paths()]:
        data = _read(path)
        if data is not None:
            return {**DEFAULT_PREFERENCES, **data}
    return dict(DEFAULT_PREFERENCES)


def save_preferences(config):
    path = config_path()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(config, f, indent=2)

def get_translator():
    lang_code = load_preferences().get("language", "fr")
    try:
        lang = gettext.translation("base", localedir=LANG_DIR, languages=[lang_code], fallback=True)
        return lang.gettext
    except:
        return lambda x: x

# ---------------- Permissions ----------------
def is_admin():
    try:
        return ctypes.windll.shell32.IsUserAnAdmin()
    except:
        return False

def relaunch_as_admin():
    params = " ".join([f'"{arg}"' for arg in sys.argv])
    try:
        ctypes.windll.shell32.ShellExecuteW(None, "runas", sys.executable, params, None, 1)
    except Exception as e:
        messagebox.showerror("Erreur", f"Échec de l'exécution en tant qu'administrateur : {e}")

# ---------------- Utilitaires ----------------
def list_drives_with_labels():
    drives = win32api.GetLogicalDriveStrings().split("\u0000")
    drives = [d for d in drives if d]
    result = []
    for d in drives:
        try:
            vol_name = win32api.GetVolumeInformation(d)[0]
        except:
            vol_name = ""
        result.append(f"{d} - {vol_name}" if vol_name else d)
    return result

def extract_drive_letter(drive_string):
    match = re.match(r"([A-Z]):", drive_string, re.I)
    if match:
        return match.group(1).upper()
    elif len(drive_string) == 1 and drive_string.isalpha():
        return drive_string.upper()
    return None
