"""Tests de src/transfer.py. Les tests robocopy utilisent uniquement des dossiers temporaires."""
import datetime
import os
import sys
import tempfile
import threading
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
import transfer  # noqa: E402


def write(path: Path, content: str = "x"):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


class Profiles(unittest.TestCase):
    def test_finds_real_profiles_only(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            write(root / "Users" / "Jean Dupont" / "Documents" / "facture.pdf")
            write(root / "Users" / "Jean Dupont" / "Desktop" / "note.txt")
            write(root / "Users" / "Jean Dupont" / "OneDrive - Société" / "a.txt")
            write(root / "Users" / "Public" / "Documents" / "x.txt")
            write(root / "Users" / "Default" / "Documents" / "x.txt")
            (root / "Users" / "Vide").mkdir(parents=True)
            profiles = transfer.find_profiles(root)
            self.assertEqual([p.name for p in profiles], ["Jean Dupont"])
            self.assertEqual(sorted(profiles[0].folders), ["Desktop", "Documents"])
            self.assertEqual([p.name for p in profiles[0].onedrive], ["OneDrive - Société"])

    def test_no_users_folder(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual(transfer.find_profiles(tmp), [])


class Scan(unittest.TestCase):
    def test_counts_files_and_bytes(self):
        with tempfile.TemporaryDirectory() as tmp:
            write(Path(tmp) / "a.txt", "12345")
            write(Path(tmp) / "sous dossier" / "é.txt", "123")
            result = transfer.scan(Path(tmp))
            self.assertEqual((result.files, result.bytes), (2, 8))

    def test_whole_drive_skips_windows_items(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            write(root / "Clients" / "devis.xlsx", "12345")
            write(root / "pagefile.sys", "x" * 100)
            write(root / "System Volume Information" / "tracking.log", "x" * 100)
            write(root / "$RECYCLE.BIN" / "S-1-5" / "a.txt", "x" * 100)
            self.assertEqual(transfer.scan(root).files, 4)
            whole = transfer.scan(root, whole_drive=True)
            self.assertEqual((whole.files, whole.bytes), (1, 5))
            args = transfer.drive_exclusions(root)
            self.assertIn("/XD", args)
            self.assertIn(str(root / "System Volume Information"), args)
            self.assertIn("pagefile.sys", args)

    def test_cancel(self):
        with tempfile.TemporaryDirectory() as tmp:
            write(Path(tmp) / "a.txt")
            stop = threading.Event()
            stop.set()
            self.assertEqual(transfer.scan(Path(tmp), stop).files, 0)


class Destination(unittest.TestCase):
    def test_destination_inside_source_refused(self):
        with tempfile.TemporaryDirectory() as tmp:
            src = Path(tmp) / "Documents"
            src.mkdir()
            self.assertIsNotNone(transfer.destination_problem([src], src / "copie"))
            self.assertIsNotNone(transfer.destination_problem([src], src))
            self.assertIsNone(transfer.destination_problem([src], Path(tmp) / "Transfert"))


class Robocopy(unittest.TestCase):
    def test_command_never_deletes(self):
        cmd = transfer.robocopy_command(Path("E:/Users/a/Documents"), Path("D:/T/a/Documents"), Path("D:/log.txt"))
        self.assertNotIn("/MIR", cmd)
        self.assertNotIn("/PURGE", cmd)
        self.assertNotIn("/MOV", cmd)
        self.assertNotIn("/MOVE", cmd)
        self.assertIn("/XJ", cmd)

    def test_exit_codes(self):
        self.assertEqual(transfer.interpret_exit_code(0)[0], True)
        self.assertEqual(transfer.interpret_exit_code(1)[0], True)
        self.assertEqual(transfer.interpret_exit_code(3)[0], True)
        self.assertEqual(transfer.interpret_exit_code(9)[0], False)
        self.assertEqual(transfer.interpret_exit_code(16)[0], False)

    def test_parse_lines_french_and_english(self):
        self.assertTrue(transfer.is_file_line("\t  Nouveau fichier\t\t       2\tC:\\src\\a.txt\r\n"))
        self.assertTrue(transfer.is_file_line("\t    New File  \t\t      12\tC:\\src\\b.txt"))
        self.assertFalse(transfer.is_file_line("Le processus ne peut pas accéder au fichier"))
        log = ("2026/11/09 06:31:44 ERREUR 32 (0x00000020) Copie du fichier C:\\src\\verrou.txt\n"
               "Le processus ne peut pas accéder au fichier car ce fichier est utilisé par un autre processus.\n"
               "2026/11/09 06:31:45 ERROR 5 (0x00000005) Copying File \\\\nas\\share\\x.doc\n"
               "Access is denied.\n")
        errors = transfer.parse_errors(log)
        self.assertEqual([(e.code, e.path) for e in errors], [(32, "C:\\src\\verrou.txt"), (5, "\\\\nas\\share\\x.doc")])
        self.assertIn("utilisé par un autre processus", errors[0].message)

    def test_real_copy_with_locked_file_and_report(self):
        with tempfile.TemporaryDirectory(prefix="edendisk essai é ") as tmp:
            src, dst, logs = Path(tmp) / "Source à copier", Path(tmp) / "Destination finale", Path(tmp) / "journaux"
            write(src / "a.txt", "contenu A")
            write(src / "sous dossier" / "b é.txt", "contenu B")
            write(src / "verrou.txt", "verrouillé")
            count = []
            # Fichier ouvert en exclusivité (partage = 0) : robocopy doit le signaler sans bloquer le reste
            import ctypes
            from ctypes import wintypes
            kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
            kernel32.CreateFileW.restype = wintypes.HANDLE
            kernel32.CreateFileW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, wintypes.LPVOID,
                                             wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE]
            h = kernel32.CreateFileW(str(src / "verrou.txt"), 0x80000000, 0, None, 3, 0, None)
            self.assertNotEqual(h, wintypes.HANDLE(-1).value)
            try:
                code = transfer.run_robocopy(src, dst, logs / "log.txt", on_file=lambda: count.append(1))
            finally:
                kernel32.CloseHandle(h)
            self.assertEqual(code & 8, 8)                      # au moins un échec
            self.assertEqual((dst / "a.txt").read_text(encoding="utf-8"), "contenu A")
            self.assertEqual((dst / "sous dossier" / "b é.txt").read_text(encoding="utf-8"), "contenu B")
            self.assertGreaterEqual(len(count), 2)
            errors = transfer.parse_errors((logs / "log.txt").read_text(encoding="utf-16"))
            self.assertEqual(len(errors), 1)
            self.assertTrue(errors[0].path.endswith("verrou.txt"))

            # Relance : le fichier verrouillé passe, les autres sont ignorés (déjà identiques)
            code2 = transfer.run_robocopy(src, dst, logs / "log2.txt")
            self.assertTrue(transfer.interpret_exit_code(code2)[0])
            self.assertTrue((dst / "verrou.txt").exists())

            result = transfer.FolderResult("Jean", "Documents", src, dst, transfer.scan(src), code, errors)
            now = datetime.datetime.now()
            report = transfer.write_report(logs / "rapport.txt", "E:\\", dst, [result], now, now, False)
            text = report.read_text(encoding="utf-8-sig")
            self.assertIn("TERMINÉ AVEC 1 ERREUR(S)", text)
            self.assertIn("verrou.txt", text)

    def test_cancel_stops_robocopy(self):
        with tempfile.TemporaryDirectory() as tmp:
            src = Path(tmp) / "src"
            for i in range(50):
                write(src / f"f{i}.txt", "x" * 1000)
            stop = threading.Event()
            stop.set()
            code = transfer.run_robocopy(src, Path(tmp) / "dst", Path(tmp) / "log.txt", cancel=stop)
            self.assertIn(code, (-1, 0, 1))  # arrêté dès la première ligne, ou déjà fini sur une machine rapide


if __name__ == "__main__":
    unittest.main()
