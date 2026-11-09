"""Essai réel de la préparation de disque sur un DISQUE VIRTUEL temporaire (aucun vrai disque touché).

À lancer dans un terminal ADMINISTRATEUR :
    py tests\\essai_disque_virtuel.py

Étapes :
  1. crée un disque virtuel de 1 Go (fichier .vhdx dans le dossier temporaire) et l'attache ;
  2. le repère comme le SEUL nouveau disque de type « File Backed Virtual » d'environ 1 Go
     (sinon : arrêt immédiat, rien n'est effacé) ;
  3. vérifie que le disque système est refusé ;
  4. prépare le disque virtuel en GPT/NTFS (disque vierge), puis en MBR/exFAT (disque déjà formaté) ;
  5. détache et supprime le disque virtuel, même en cas d'erreur.
"""
import ctypes
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
import disks  # noqa: E402

GIB = 1024**3


def diskpart(script: str) -> str:
    with tempfile.NamedTemporaryFile("w", suffix=".txt", delete=False, encoding="ascii") as f:
        f.write(script)
        path = f.name
    try:
        res = subprocess.run(["diskpart", "/s", path], capture_output=True, text=True)
        if res.returncode != 0:
            raise RuntimeError(res.stdout + res.stderr)
        return res.stdout
    finally:
        os.remove(path)


def volume_of(letter: str) -> dict:
    out = subprocess.run(
        ["powershell", "-NoProfile", "-Command",
         f"Get-Volume -DriveLetter {letter} | Select-Object FileSystem,FileSystemLabel | ConvertTo-Json -Compress"],
        capture_output=True, text=True,
    ).stdout
    return json.loads(out)


def check(condition: bool, message: str):
    print(("  OK    " if condition else "  ÉCHEC ") + message)
    if not condition:
        raise SystemExit(1)


def main():
    if not ctypes.windll.shell32.IsUserAnAdmin():
        sys.exit("Ce test doit être lancé dans un terminal administrateur.")

    vhd = Path(tempfile.gettempdir()) / "edendisk-essai.vhdx"
    if vhd.exists():
        sys.exit(f"{vhd} existe déjà : supprimez-le (ou détachez-le) puis relancez.")

    before = {d.number for d in disks.list_disks()}
    print("1. Création et attachement du disque virtuel de 1 Go…")
    diskpart(f'create vdisk file="{vhd}" maximum=1024 type=expandable\nselect vdisk file="{vhd}"\nattach vdisk\n')
    try:
        new = [d for d in disks.list_disks() if d.number not in before]
        check(len(new) == 1, f"un seul nouveau disque détecté ({len(new)})")
        target = new[0]
        check(target.bus == "File Backed Virtual", f"le nouveau disque est virtuel (BusType = {target.bus})")
        check(0.9 * GIB < target.size <= 1.1 * GIB, f"taille d'environ 1 Go ({disks.format_size(target.size)})")
        check(disks.protection_reasons(target, disks.system_drive_letter(), disks.app_drive_letter()) == [],
              f"disque virtuel {target.number} autorisé")

        print("2. Le disque système doit être refusé…")
        system = next(d for d in disks.list_disks() if d.is_system or d.is_boot)
        refused = disks.prepare_disk(system, "NTFS", "X", "GPT")
        check(not refused.ok, f"disque {system.number} refusé : {refused.message}")

        print("3. Préparation GPT / NTFS (disque vierge)…")
        res = disks.prepare_disk(target, "NTFS", "ESSAI-NTFS", "GPT")
        check(res.ok and bool(res.letter), f"préparé, lecteur {res.letter}: ({res.message})")
        vol = volume_of(res.letter)
        check(vol["FileSystem"] == "NTFS" and vol["FileSystemLabel"] == "ESSAI-NTFS", f"volume {vol}")

        print("4. Préparation MBR / exFAT (disque déjà formaté)…")
        target = next(d for d in disks.list_disks() if d.number == target.number)
        check(target.style == "GPT" and target.letters, f"état relu : {target.style}, {target.letters}")
        res = disks.prepare_disk(target, "exFAT", "ESSAI-EXFAT", "MBR")
        check(res.ok and bool(res.letter), f"préparé, lecteur {res.letter}: ({res.message})")
        vol = volume_of(res.letter)
        check(vol["FileSystem"] == "exFAT" and vol["FileSystemLabel"] == "ESSAI-EXFAT", f"volume {vol}")
        target = next(d for d in disks.list_disks() if d.number == target.number)
        check(target.style == "MBR", f"style relu : {target.style}")

        print("5. Identité modifiée : l'opération doit être annulée…")
        fake = disks.Disk(**{**target.__dict__, "unique_id": "AUTRE-DISQUE"})
        res = disks.prepare_disk(fake, "NTFS", "X", "GPT")
        check(not res.ok and "ne correspond plus" in res.message, res.message)
        print("\nTous les essais sont réussis.")
    finally:
        print("Nettoyage : détachement et suppression du disque virtuel…")
        try:
            diskpart(f'select vdisk file="{vhd}"\ndetach vdisk\n')
        finally:
            if vhd.exists():
                vhd.unlink()


if __name__ == "__main__":
    main()
