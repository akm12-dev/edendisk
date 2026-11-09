# EdenDisk

Utilitaire **AKM12** pour techniciens : transfert des données utilisateur, copie de lecteur et préparation
(effacement + formatage) de disques sous Windows. Gratuit, sans clé de licence.

Fiche : https://akm12.com/logiciels/edendisk

## Lancer depuis le code source

Prérequis : Windows, Python 3.9+, `pip install pywin32 pillow`.

```powershell
cd src
py main.py        # demande les droits administrateur (nécessaires pour préparer un disque)
```

## Structure

```
src/
  main.py        point d'entrée (relance en administrateur)
  ui.py          interface tkinter
  backend.py     préférences, traductions, copie des dossiers utilisateur, copie de lecteur
  disks.py       inventaire des disques et préparation sécurisée (PowerShell Storage)
  locale/        traductions FR / EN (base.po -> base.mo avec msgfmt)
tests/
  test_disks.py              tests automatiques, aucun disque touché
  essai_disque_virtuel.py    essai réel sur un disque virtuel temporaire (administrateur)
```

## Sécurité de la préparation de disque

- Un disque système, de démarrage, hors ligne, en lecture seule, contenant le lecteur Windows ou contenant
  EdenDisk ne peut pas être sélectionné.
- Avant d'effacer, la liste de toutes les partitions concernées est affichée et il faut **taper le numéro du disque**.
- Juste avant l'effacement, le script PowerShell revérifie l'identité du disque (identifiant, taille, modèle)
  et ses protections : si un disque a été branché ou débranché entre-temps, l'opération est annulée.

## Tests

```powershell
py -m unittest discover -s tests              # tests automatiques
py tests\essai_disque_virtuel.py              # dans un terminal administrateur : essai réel sur un VHDX de 1 Go
```

## Licence

Code consultable, tous droits réservés — voir [LICENSE](LICENSE). Vous pouvez lire, cloner et compiler ce code
pour votre propre usage ; sa redistribution, sa modification publiée et sa réutilisation demandent l'accord
d'AKM12. Les versions officielles gratuites sont publiées sur https://akm12.com et
https://github.com/akm12-dev/releases.

## Construire la version Windows

```powershell
cd src
py -m PyInstaller --noconfirm --clean EdenDisk.spec      # → src\dist\EdenDisk.exe
cd ..
& "C:\Program Files (x86)\Inno Setup 6\ISCC.exe" edendisk.iss   # → installer\output\EdenDisk-<version>-setup.exe
```

Changer de version : `APP_VERSION` (src/ui.py), `src/version_info.txt` et `#define AppVersion` (edendisk.iss).
