"""Transfert des données utilisateur d'un disque vers un dossier, avec robocopy.

Cas d'usage : le disque de l'ancien PC est branché (adaptateur USB) ; on copie les dossiers
Bureau, Documents, Images… de chaque profil choisi vers une destination, puis on produit
un rapport lisible par le technicien et par le client.

Principes :
  * aucune suppression : robocopy est lancé sans /MIR ni /PURGE ;
  * relançable : un transfert interrompu reprend, les fichiers identiques sont ignorés ;
  * la sortie de robocopy est analysée sans dépendre de la langue de Windows
    (structure des lignes et codes d'erreur, pas les libellés traduits).
"""
from __future__ import annotations

import datetime
import os
import re
import shutil
import stat
import subprocess
import sys
import threading
from dataclasses import dataclass, field
from pathlib import Path

CREATE_NO_WINDOW = 0x08000000

# Dossiers standard : le nom physique est en anglais sur toutes les versions de Windows
# (le nom affiché « Bureau », « Images »… vient de desktop.ini).
STANDARD_FOLDERS = [
    ("Desktop", "Bureau"),
    ("Documents", "Documents"),
    ("Pictures", "Images"),
    ("Music", "Musique"),
    ("Videos", "Vidéos"),
    ("Downloads", "Téléchargements"),
    ("Favorites", "Favoris"),
]
# Profils techniques de Windows, jamais proposés (« Administrateur » reste proposé : il peut être utilisé)
SYSTEM_PROFILES = {"default", "default user", "public", "all users", "defaultuser0", "defaultuser100000",
                   "wdagutilityaccount"}

ATTR_OFFLINE = 0x1000
ATTR_RECALL_ON_OPEN = 0x40000
ATTR_RECALL_ON_DATA_ACCESS = 0x400000
CLOUD_ONLY = ATTR_OFFLINE | ATTR_RECALL_ON_OPEN | ATTR_RECALL_ON_DATA_ACCESS


@dataclass
class Profile:
    name: str
    path: Path
    folders: dict[str, Path]                       # clé STANDARD_FOLDERS -> dossier existant
    onedrive: list[Path] = field(default_factory=list)


def _is_reparse(entry_path: Path) -> bool:
    try:
        attrs = os.lstat(entry_path).st_file_attributes  # type: ignore[attr-defined]
    except (OSError, AttributeError):
        return os.path.islink(entry_path)
    return bool(attrs & stat.FILE_ATTRIBUTE_REPARSE_POINT)


def find_profiles(drive_root: str | Path) -> list[Profile]:
    """Profils utilisateurs de <lecteur>:\\Users (hors profils système et liens)."""
    users = Path(drive_root) / "Users"
    if not users.is_dir():
        return []
    profiles = []
    for entry in sorted(users.iterdir(), key=lambda p: p.name.lower()):
        try:
            if not entry.is_dir() or _is_reparse(entry) or entry.name.lower() in SYSTEM_PROFILES:
                continue
        except OSError:
            continue
        folders = {}
        for key, _label in STANDARD_FOLDERS:
            candidate = entry / key
            try:
                if candidate.is_dir() and not _is_reparse(candidate):
                    folders[key] = candidate
            except OSError:
                pass
        onedrive = []
        try:
            onedrive = sorted(p for p in entry.iterdir() if p.name.lower().startswith("onedrive") and p.is_dir()
                              and not _is_reparse(p))
        except OSError:
            pass
        if folders or onedrive:
            profiles.append(Profile(entry.name, entry, folders, onedrive))
    return profiles


@dataclass
class ScanResult:
    files: int = 0
    bytes: int = 0
    cloud_only: int = 0      # fichiers « en ligne uniquement » (OneDrive…), non copiables hors connexion
    unreadable: int = 0      # dossiers illisibles (droits)


def scan(path: Path, cancel: threading.Event | None = None, whole_drive: bool = False) -> ScanResult:
    """Compte fichiers et octets à copier, sans suivre les liens ni les fichiers « en ligne uniquement ».
    whole_drive=True : ignore aussi les éléments système exclus de la copie d'un lecteur."""
    result = ScanResult()
    skip_dirs = {str(Path(path) / d).lower() for d in DRIVE_EXCLUDED_DIRS} if whole_drive else set()
    skip_files = {f.lower() for f in DRIVE_EXCLUDED_FILES} if whole_drive else set()
    stack = [str(path)]
    while stack:
        if cancel is not None and cancel.is_set():
            break
        current = stack.pop()
        try:
            with os.scandir(current) as it:
                for entry in it:
                    try:
                        st = entry.stat(follow_symlinks=False)
                    except OSError:
                        continue
                    attrs = getattr(st, "st_file_attributes", 0)
                    if attrs & stat.FILE_ATTRIBUTE_REPARSE_POINT and not attrs & CLOUD_ONLY:
                        continue                      # jonction / lien : ignoré (robocopy /XJ)
                    if entry.is_dir(follow_symlinks=False):
                        if entry.path.lower() not in skip_dirs:
                            stack.append(entry.path)
                    elif entry.name.lower() in skip_files:
                        continue
                    elif attrs & CLOUD_ONLY:
                        result.cloud_only += 1
                    else:
                        result.files += 1
                        result.bytes += st.st_size
        except OSError:
            result.unreadable += 1
    return result


def destination_problem(sources: list[Path], destination: Path) -> str | None:
    """Message d'erreur si la destination est inutilisable, sinon None."""
    try:
        dst = destination.resolve()
    except OSError:
        return "Destination invalide."
    for src in sources:
        s = src.resolve()
        if dst == s or s in dst.parents:
            return f"La destination se trouve dans un dossier copié ({src}) : la copie ne finirait jamais."
    return None


def free_space(destination: Path) -> int:
    probe = destination
    while not probe.exists() and probe.parent != probe:
        probe = probe.parent
    return shutil.disk_usage(probe).free


# --------------------------------------------------------------------------- robocopy

# Copie d'un lecteur entier : éléments propres à Windows, inutiles et souvent verrouillés
DRIVE_EXCLUDED_DIRS = ["System Volume Information", "$RECYCLE.BIN", "$Recycle.Bin", "Recovery", "Config.Msi",
                       "$WinREAgent", "$SysReset", "$Windows.~BT", "$Windows.~WS"]
DRIVE_EXCLUDED_FILES = ["pagefile.sys", "hiberfil.sys", "swapfile.sys", "DumpStack.log", "DumpStack.log.tmp"]


def drive_exclusions(drive_root: Path) -> list[str]:
    """Arguments robocopy excluant les éléments système de la racine d'un lecteur."""
    dirs = [str(Path(drive_root) / d) for d in DRIVE_EXCLUDED_DIRS]
    return ["/XD", *dirs, "/XF", *DRIVE_EXCLUDED_FILES]


def robocopy_command(source: Path, destination: Path, log_file: Path, extra: list[str] | None = None) -> list[str]:
    """Copie sans suppression, avec reprise, sans suivre les jonctions ni les fichiers en ligne uniquement."""
    return [
        "robocopy", str(source), str(destination),
        "/E",                 # sous-dossiers, y compris vides
        "/COPY:DAT",          # données, attributs, dates (pas les droits NTFS de l'ancien PC)
        "/DCOPY:T",           # dates des dossiers
        "/R:1", "/W:1",       # une seule nouvelle tentative par fichier
        "/XJ",                # ne suit pas les jonctions (« Mes images »… dans Documents)
        "/XA:O",              # ignore les fichiers hors connexion (en ligne uniquement)
        "/FP", "/NDL", "/NJH", "/NJS", "/NP", "/BYTES",
        f"/UNILOG:{log_file}", "/TEE",
        *(extra or []),
    ]


_FILE_LINE = re.compile(r"^\t[^\t]*\t+\s*(\d+)\t(.+)$")
_ERROR_LINE = re.compile(r"^\d{4}/\d{2}/\d{2} \d{2}:\d{2}:\d{2} \S+ (\d+) \(0x[0-9A-Fa-f]{8}\) (.*)$")
_PATH = re.compile(r"([A-Za-z]:\\.*|\\\\.*)$")


def is_file_line(line: str) -> bool:
    """Ligne « fichier copié » de robocopy (/FP /BYTES), quelle que soit la langue."""
    return bool(_FILE_LINE.match(line.rstrip("\r\n")))


@dataclass
class CopyError:
    code: int
    path: str
    message: str


def parse_errors(log_text: str) -> list[CopyError]:
    """Erreurs du journal robocopy : « date heure <ERREUR|ERROR> 32 (0x00000020) … chemin » + message."""
    errors = []
    lines = log_text.splitlines()
    for i, line in enumerate(lines):
        m = _ERROR_LINE.match(line.strip())
        if not m:
            continue
        p = _PATH.search(m.group(2))
        message = lines[i + 1].strip() if i + 1 < len(lines) else ""
        errors.append(CopyError(int(m.group(1)), p.group(1).strip() if p else m.group(2).strip(), message))
    # robocopy réessaie (/R:1) : une même erreur peut apparaître deux fois
    unique = {(e.code, e.path): e for e in errors}
    return list(unique.values())


def interpret_exit_code(code: int) -> tuple[bool, str]:
    """Codes robocopy (masque de bits) : < 8 = réussite, >= 8 = au moins un échec."""
    if code >= 16:
        return False, "erreur grave (source inaccessible, paramètres refusés ou espace insuffisant)"
    if code & 8:
        return False, "certains fichiers n'ont pas pu être copiés"
    if code & 1:
        return True, "fichiers copiés"
    return True, "rien à copier (déjà à jour)"


def run_robocopy(source: Path, destination: Path, log_file: Path, on_file=None,
                 cancel: threading.Event | None = None, extra: list[str] | None = None) -> int:
    """Lance robocopy ; on_file() est appelé à chaque fichier traité. Retourne le code de sortie (-1 si arrêté)."""
    log_file.parent.mkdir(parents=True, exist_ok=True)
    proc = subprocess.Popen(
        robocopy_command(source, destination, log_file, extra),
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        creationflags=CREATE_NO_WINDOW if sys.platform == "win32" else 0,
    )
    assert proc.stdout is not None
    with proc.stdout:
        for raw in proc.stdout:
            if cancel is not None and cancel.is_set():
                proc.terminate()
                proc.wait()
                return -1
            if on_file is not None and is_file_line(raw.decode("cp850", errors="replace")):
                on_file()
    return proc.wait()


# --------------------------------------------------------------------------- Rapport

@dataclass
class FolderResult:
    profile: str
    folder: str
    source: Path
    destination: Path
    planned: ScanResult
    exit_code: int | None = None
    errors: list[CopyError] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return self.exit_code is not None and self.exit_code >= 0 and interpret_exit_code(self.exit_code)[0]


def write_report(path: Path, source_root: str, destination: Path, results: list[FolderResult],
                 started: datetime.datetime, finished: datetime.datetime, stopped: bool,
                 format_size=lambda n: f"{n} octets") -> Path:
    total_files = sum(r.planned.files for r in results)
    total_bytes = sum(r.planned.bytes for r in results)
    total_errors = sum(len(r.errors) for r in results)
    lines = [
        "RAPPORT DE TRANSFERT EDENDISK",
        "=" * 60,
        f"Date            : {started:%d/%m/%Y %H:%M} -> {finished:%H:%M} ({str(finished - started).split('.')[0]})",
        f"Source          : {source_root}",
        f"Destination     : {destination}",
        f"Volume prévu    : {total_files} fichier(s), {format_size(total_bytes)}",
        f"Résultat        : " + ("INTERROMPU par l'utilisateur" if stopped
                                 else "TERMINÉ SANS ERREUR" if total_errors == 0 and all(r.ok for r in results)
                                 else f"TERMINÉ AVEC {total_errors} ERREUR(S)"),
        "",
        "DÉTAIL PAR DOSSIER",
        "-" * 60,
    ]
    for r in results:
        status = "non traité" if r.exit_code is None else "arrêté" if r.exit_code < 0 else interpret_exit_code(r.exit_code)[1]
        lines.append(f"{r.profile} / {r.folder} : {r.planned.files} fichier(s), {format_size(r.planned.bytes)} — {status}")
        lines.append(f"    {r.source}  ->  {r.destination}")
        if r.planned.cloud_only:
            lines.append(f"    {r.planned.cloud_only} fichier(s) « en ligne uniquement » (OneDrive…) non copiés : ils se "
                         "récupèrent en se connectant au compte cloud.")
        if r.planned.unreadable:
            lines.append(f"    {r.planned.unreadable} dossier(s) illisible(s) (droits d'accès).")
    if total_errors:
        lines += ["", "FICHIERS NON COPIÉS", "-" * 60]
        for r in results:
            for e in r.errors:
                lines.append(f"[{e.code}] {e.path}")
                if e.message:
                    lines.append(f"      {e.message}")
    lines += ["", "Les journaux robocopy complets sont dans le même dossier que ce rapport.",
              "Relancer le transfert reprend là où il s'est arrêté (les fichiers identiques sont ignorés).",
              "", "EdenDisk — AKM12 · https://akm12.com/logiciels/edendisk"]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8-sig")
    return path
