"""Disques physiques : inventaire et préparation (effacement + formatage) sécurisée.

Toutes les informations viennent des cmdlets PowerShell du module Storage (Get-Disk,
Get-Partition, Get-Volume) en JSON : le résultat ne dépend pas de la langue de Windows,
contrairement à la sortie texte de diskpart.

Sécurité de la préparation de disque :
  * un disque système, de démarrage, hors ligne, en lecture seule, contenant le lecteur
    Windows ou contenant EdenDisk ne peut pas être préparé (protection_reasons) ;
  * le script PowerShell revérifie l'identité du disque (UniqueId, taille, modèle) et ses
    protections juste avant d'effacer : si les numéros de disques ont changé entre la
    sélection et l'exécution (clé USB débranchée…), l'opération est annulée ;
  * les options (système de fichiers, style, nom de volume) sont contrôlées par liste
    blanche avant d'être insérées dans le script.
"""
from __future__ import annotations

import base64
import json
import os
import re
import subprocess
import sys
from dataclasses import dataclass, field

CREATE_NO_WINDOW = 0x08000000

FILE_SYSTEMS = ("NTFS", "exFAT", "FAT32")
PARTITION_STYLES = ("GPT", "MBR")
FAT32_MAX_BYTES = 32 * 1024**3          # Windows ne formate pas en FAT32 au-delà de 32 Go
MBR_MAX_BYTES = 2 * 1024**4             # MBR ne gère pas plus de 2 To
LABEL_MAX = {"NTFS": 32, "exFAT": 15, "FAT32": 11}
LABEL_RE = re.compile(r"^[A-Za-z0-9 _-]*$")


@dataclass
class Partition:
    number: int
    size: int
    type: str = ""
    letter: str | None = None
    label: str | None = None
    file_system: str | None = None
    free: int | None = None          # espace libre du volume, si la partition en porte un

    @property
    def used_percent(self) -> int | None:
        if self.free is None or self.size <= 0:
            return None
        return round(100 * (self.size - self.free) / self.size)

    def describe(self) -> str:
        parts = [f"partition {self.number}"]
        if self.letter:
            parts.append(f"{self.letter}:")
        if self.label:
            parts.append(f"« {self.label} »")
        if self.file_system:
            parts.append(self.file_system)
        elif self.type:
            parts.append(self.type)
        parts.append(format_size(self.size))
        return " ".join(parts)


@dataclass
class Disk:
    number: int
    name: str
    size: int
    bus: str = ""
    style: str = ""
    unique_id: str = ""
    serial: str = ""
    is_system: bool = False
    is_boot: bool = False
    is_offline: bool = False
    is_readonly: bool = False
    partitions: list[Partition] = field(default_factory=list)
    # Santé et support (Get-PhysicalDisk / Get-StorageReliabilityCounter) : None = non communiqué
    media_type: str | None = None    # SSD, HDD…
    health: str | None = None        # Healthy, Warning, Unhealthy, Unknown
    temperature: int | None = None   # °C
    wear: int | None = None          # usure en % (SSD)
    power_on_hours: int | None = None
    read_errors: int | None = None

    @property
    def letters(self) -> list[str]:
        return [p.letter for p in self.partitions if p.letter]

    @property
    def is_virtual(self) -> bool:
        return self.bus == "File Backed Virtual"


HEALTH_LABELS = {"Healthy": "Bon", "Warning": "Avertissement", "Unhealthy": "Défaillant", "Unknown": "Inconnu"}
MEDIA_LABELS = {"SSD": "SSD", "HDD": "Disque dur", "SCM": "Mémoire persistante"}
BUS_LABELS = {"File Backed Virtual": "Virtuel (VHD)", "RAID": "RAID", "SATA": "SATA", "NVMe": "NVMe", "USB": "USB",
              "SAS": "SAS", "SCSI": "SCSI", "ATA": "ATA", "SD": "Carte SD", "MMC": "Carte MMC"}


def health_label(disk: "Disk") -> str:
    return HEALTH_LABELS.get(disk.health or "", "Non communiqué")


def health_needs_attention(disk: "Disk") -> bool:
    """Vrai si Windows signale un problème (le seuil est celui de Windows, pas d'EdenDisk)."""
    return disk.health in ("Warning", "Unhealthy") or bool(disk.read_errors)


def format_size(num_bytes: int) -> str:
    """Taille lisible en unités décimales (comme l'étiquette des disques)."""
    value = float(num_bytes)
    for unit in ("octets", "Ko", "Mo", "Go", "To"):
        if value < 1000 or unit == "To":
            return f"{value:.0f} {unit}" if unit == "octets" else f"{value:.1f} {unit}".replace(".", ",")
        value /= 1000
    return f"{num_bytes} octets"


# --------------------------------------------------------------------------- PowerShell

def _run_powershell(script: str, timeout: int = 120) -> subprocess.CompletedProcess:
    """Exécute un script PowerShell passé en -EncodedCommand (aucun problème de guillemets)."""
    prefix = "[Console]::OutputEncoding = [System.Text.Encoding]::UTF8\n$ProgressPreference = 'SilentlyContinue'\n"
    encoded = base64.b64encode((prefix + script).encode("utf-16-le")).decode("ascii")
    return subprocess.run(
        ["powershell.exe", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-EncodedCommand", encoded],
        capture_output=True,
        timeout=timeout,
        creationflags=CREATE_NO_WINDOW if sys.platform == "win32" else 0,
    )


def _decode(data: bytes) -> str:
    for enc in ("utf-8", "cp850", "cp1252"):
        try:
            return data.decode(enc)
        except UnicodeDecodeError:
            continue
    return data.decode("utf-8", errors="replace")


_CLIXML_ERROR = re.compile(r'<S S="Error">(.*?)</S>', re.S)
_CLIXML_ESCAPE = re.compile(r"_x([0-9A-Fa-f]{4})_")


def error_text(stderr: str) -> str:
    """Texte lisible d'une erreur PowerShell.

    Avec -EncodedCommand, PowerShell écrit ses erreurs au format CLIXML (« #< CLIXML <Objs>… »)
    où les retours à la ligne sont codés _x000D__x000A_ : on en extrait le texte brut.
    """
    if "#< CLIXML" in stderr:
        import html
        parts = [html.unescape(_CLIXML_ESCAPE.sub(lambda m: chr(int(m.group(1), 16)), p))
                 for p in _CLIXML_ERROR.findall(stderr)]
        stderr = "".join(parts)
    return stderr.strip()


INVENTORY_SCRIPT = r"""
$ErrorActionPreference = 'Stop'
$physical = @{}
foreach ($pd in @(Get-PhysicalDisk -ErrorAction SilentlyContinue)) { $physical[[string]$pd.DeviceId] = $pd }
function Num($value) { if ($null -eq $value) { $null } else { [int64]$value } }
$disks = @(Get-Disk | Sort-Object Number | ForEach-Object {
  $d = $_
  $pd = $physical[[string]$d.Number]
  $rc = $null
  if ($pd) { try { $rc = $pd | Get-StorageReliabilityCounter -ErrorAction Stop } catch {} }
  $parts = @(Get-Partition -DiskNumber $d.Number -ErrorAction SilentlyContinue | Sort-Object PartitionNumber | ForEach-Object {
    $v = $null
    try { $v = $_ | Get-Volume -ErrorAction Stop } catch {}
    $letter = $null
    if ($_.DriveLetter -and [int][char]$_.DriveLetter -ne 0) { $letter = [string]$_.DriveLetter }
    [pscustomobject]@{
      Number = [int]$_.PartitionNumber; Size = [int64]$_.Size; Type = [string]$_.Type; DriveLetter = $letter
      Label = $(if ($v) { [string]$v.FileSystemLabel } else { $null })
      FileSystem = $(if ($v) { [string]$v.FileSystem } else { $null })
      Free = $(if ($v) { Num $v.SizeRemaining } else { $null })
    }
  })
  [pscustomobject]@{
    Number = [int]$d.Number; Name = [string]$d.FriendlyName; Size = [int64]$d.Size
    Bus = [string]$d.BusType; Style = [string]$d.PartitionStyle
    UniqueId = [string]$d.UniqueId; Serial = [string]$d.SerialNumber
    IsSystem = [bool]$d.IsSystem; IsBoot = [bool]$d.IsBoot
    IsOffline = [bool]$d.IsOffline; IsReadOnly = [bool]$d.IsReadOnly
    MediaType = $(if ($pd) { [string]$pd.MediaType } else { $null })
    Health = $(if ($pd) { [string]$pd.HealthStatus } else { [string]$d.HealthStatus })
    Temperature = $(if ($rc) { Num $rc.Temperature } else { $null })
    Wear = $(if ($rc) { Num $rc.Wear } else { $null })
    PowerOnHours = $(if ($rc) { Num $rc.PowerOnHours } else { $null })
    ReadErrors = $(if ($rc) { Num $rc.ReadErrorsUncorrected } else { $null })
    Partitions = $parts
  }
})
ConvertTo-Json -InputObject $disks -Depth 4 -Compress
"""


def _int_or_none(value, positive: bool = False) -> int | None:
    """Entier, ou None si absent. positive=True : 0 est traité comme « non communiqué »
    (beaucoup de contrôleurs USB renvoient 0 °C faute de capteur)."""
    if value is None or value == "":
        return None
    try:
        number = int(value)
    except (TypeError, ValueError):
        return None
    if positive and number <= 0:
        return None
    return number


def parse_inventory(raw: str) -> list[Disk]:
    """Transforme le JSON de INVENTORY_SCRIPT en objets Disk (accepte un objet seul ou une liste)."""
    raw = raw.strip()
    if not raw:
        return []
    data = json.loads(raw)
    if isinstance(data, dict):
        data = [data]
    disks = []
    for d in data:
        parts = d.get("Partitions") or []
        if isinstance(parts, dict):
            parts = [parts]
        disks.append(
            Disk(
                number=int(d["Number"]),
                name=(d.get("Name") or "").strip(),
                size=int(d.get("Size") or 0),
                bus=d.get("Bus") or "",
                style=d.get("Style") or "",
                unique_id=(d.get("UniqueId") or "").strip(),
                serial=(d.get("Serial") or "").strip(),
                is_system=bool(d.get("IsSystem")),
                is_boot=bool(d.get("IsBoot")),
                is_offline=bool(d.get("IsOffline")),
                is_readonly=bool(d.get("IsReadOnly")),
                media_type=d.get("MediaType") or None,
                health=d.get("Health") or None,
                temperature=_int_or_none(d.get("Temperature"), positive=True),
                wear=_int_or_none(d.get("Wear")),
                power_on_hours=_int_or_none(d.get("PowerOnHours")),
                read_errors=_int_or_none(d.get("ReadErrors")),
                partitions=[
                    Partition(
                        number=int(p["Number"]),
                        size=int(p.get("Size") or 0),
                        type=p.get("Type") or "",
                        letter=(p.get("DriveLetter") or None),
                        label=(p.get("Label") or None),
                        file_system=(p.get("FileSystem") or None),
                        free=_int_or_none(p.get("Free")),
                    )
                    for p in parts
                ],
            )
        )
    return disks


def list_disks() -> list[Disk]:
    """Inventaire des disques physiques. Lève RuntimeError si PowerShell échoue."""
    result = _run_powershell(INVENTORY_SCRIPT, timeout=60)
    if result.returncode != 0:
        message = error_text(_decode(result.stderr))
        raise RuntimeError(message.splitlines()[0] if message else "Get-Disk a échoué")
    return parse_inventory(_decode(result.stdout))


# --------------------------------------------------------------------------- Protections

def app_drive_letter() -> str | None:
    """Lettre du lecteur d'où EdenDisk est lancé (exécutable ou script)."""
    path = sys.executable if getattr(sys, "frozen", False) else os.path.abspath(__file__)
    drive = os.path.splitdrive(path)[0]
    return drive[0].upper() if drive and drive[0].isalpha() else None


def system_drive_letter() -> str | None:
    drive = os.environ.get("SystemDrive", "C:")
    return drive[0].upper() if drive and drive[0].isalpha() else None


def protection_reasons(disk: Disk, system_letter: str | None = None, app_letter: str | None = None) -> list[str]:
    """Raisons pour lesquelles ce disque ne doit pas être effacé. Liste vide = disque autorisé."""
    reasons = []
    letters = {letter.upper() for letter in disk.letters}
    if disk.is_system:
        reasons.append("disque système de Windows")
    if disk.is_boot:
        reasons.append("disque de démarrage")
    if system_letter and system_letter.upper() in letters:
        reasons.append(f"contient le lecteur Windows {system_letter.upper()}:")
    if app_letter and app_letter.upper() in letters:
        reasons.append(f"contient EdenDisk (lecteur {app_letter.upper()}:)")
    if disk.is_offline:
        reasons.append("disque hors ligne")
    if disk.is_readonly:
        reasons.append("disque en lecture seule")
    if disk.size <= 0:
        reasons.append("aucun support détecté")
    return reasons


def validate_options(disk: Disk, file_system: str, label: str, style: str) -> list[str]:
    """Contrôle les options de préparation. Liste vide = options valides."""
    errors = []
    if file_system not in FILE_SYSTEMS:
        errors.append(f"Système de fichiers inconnu : {file_system}")
    if style not in PARTITION_STYLES:
        errors.append(f"Style de partition inconnu : {style}")
    if file_system == "FAT32" and disk.size > FAT32_MAX_BYTES:
        errors.append("Windows ne formate pas en FAT32 un disque de plus de 32 Go : choisissez exFAT ou NTFS.")
    if style == "MBR" and disk.size > MBR_MAX_BYTES:
        errors.append("Le style MBR ne gère pas les disques de plus de 2 To : choisissez GPT.")
    if not LABEL_RE.match(label):
        errors.append("Nom de volume : lettres sans accent, chiffres, espaces, tirets et soulignés uniquement.")
    limit = LABEL_MAX.get(file_system)
    if limit and len(label) > limit:
        errors.append(f"Nom de volume trop long pour {file_system} ({limit} caractères maximum).")
    return errors


# --------------------------------------------------------------------------- Préparation

def _ps_quote(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def build_prepare_script(disk: Disk, file_system: str, label: str, style: str) -> str:
    """Script PowerShell d'effacement + initialisation + formatage, avec revérifications."""
    if file_system not in FILE_SYSTEMS or style not in PARTITION_STYLES or not LABEL_RE.match(label):
        raise ValueError("Options de préparation invalides")
    n = int(disk.number)
    return f"""
$ErrorActionPreference = 'Stop'
$d = Get-Disk -Number {n}
if ([string]$d.UniqueId -ne {_ps_quote(disk.unique_id)} -or [int64]$d.Size -ne {int(disk.size)} -or ([string]$d.FriendlyName).Trim() -ne {_ps_quote(disk.name)}) {{
  throw 'Le disque {n} ne correspond plus au disque sélectionné (branchement modifié ?). Opération annulée.'
}}
if ($d.IsSystem -or $d.IsBoot) {{ throw 'Disque système ou de démarrage : opération refusée.' }}
if ($d.IsOffline -or $d.IsReadOnly) {{ throw 'Disque hors ligne ou en lecture seule : opération refusée.' }}
$sysLetter = ([string]$env:SystemDrive).Substring(0, 1)
$sysDisk = (Get-Partition -DriveLetter $sysLetter).DiskNumber
if ($sysDisk -eq {n}) {{ throw 'Ce disque contient Windows : opération refusée.' }}
if ($d.PartitionStyle -ne 'RAW') {{ Clear-Disk -Number {n} -RemoveData -RemoveOEM -Confirm:$false }}
Initialize-Disk -Number {n} -PartitionStyle {style}
$p = New-Partition -DiskNumber {n} -UseMaximumSize -AssignDriveLetter
Format-Volume -Partition $p -FileSystem {file_system} -NewFileSystemLabel {_ps_quote(label)} -Confirm:$false -Force | Out-Null
$p = Get-Partition -DiskNumber {n} -PartitionNumber $p.PartitionNumber
Write-Output ('LETTRE=' + [string]$p.DriveLetter)
"""


@dataclass
class PrepareResult:
    ok: bool
    message: str
    letter: str | None = None


def prepare_disk(disk: Disk, file_system: str, label: str, style: str) -> PrepareResult:
    """Efface entièrement `disk`, le partitionne et le formate. Refuse tout disque protégé."""
    reasons = protection_reasons(disk, system_drive_letter(), app_drive_letter())
    if reasons:
        return PrepareResult(False, "Opération refusée : " + ", ".join(reasons) + ".")
    errors = validate_options(disk, file_system, label, style)
    if errors:
        return PrepareResult(False, " ".join(errors))
    try:
        result = _run_powershell(build_prepare_script(disk, file_system, label, style), timeout=900)
    except subprocess.TimeoutExpired:
        return PrepareResult(False, "L'opération a dépassé 15 minutes et a été interrompue.")
    out, err = _decode(result.stdout), error_text(_decode(result.stderr))
    if result.returncode != 0:
        first = next((line.strip() for line in err.splitlines() if line.strip()), "erreur inconnue")
        return PrepareResult(False, f"Échec de la préparation : {first}")
    match = re.search(r"LETTRE=([A-Za-z])", out)
    letter = match.group(1).upper() if match else None
    return PrepareResult(True, "Disque préparé.", letter)
