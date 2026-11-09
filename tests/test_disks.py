"""Tests de src/disks.py — aucun disque n'est lu ni modifié (PowerShell simulé).

Lancement :  py -m unittest discover -s tests
"""
import json
import subprocess
import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
import disks  # noqa: E402

SYSTEM_DISK = {
    "Number": 0, "Name": "INTEL SSDPEKNU512GZ", "Size": 512110190592, "Bus": "NVMe", "Style": "GPT",
    "UniqueId": "eui.0001", "Serial": "S1", "IsSystem": True, "IsBoot": True, "IsOffline": False, "IsReadOnly": False,
    "Partitions": [
        {"Number": 1, "Size": 104857600, "Type": "System", "DriveLetter": None, "Label": None, "FileSystem": None},
        {"Number": 3, "Size": 510877761536, "Type": "Basic", "DriveLetter": "C", "Label": "", "FileSystem": "NTFS"},
    ],
}
USB_DISK = {
    "Number": 1, "Name": "SanDisk Ultra", "Size": 64023257088, "Bus": "USB", "Style": "MBR",
    "UniqueId": "USBSTOR\\DISK&VEN_SANDISK", "Serial": "4C53", "IsSystem": False, "IsBoot": False,
    "IsOffline": False, "IsReadOnly": False,
    "Partitions": {"Number": 1, "Size": 64021159936, "Type": "IFS", "DriveLetter": "E", "Label": "CLE", "FileSystem": "exFAT"},
}


def make(data):
    return disks.parse_inventory(json.dumps(data))[0]


class ParseInventory(unittest.TestCase):
    def test_list_and_nested_partitions(self):
        found = disks.parse_inventory(json.dumps([SYSTEM_DISK, USB_DISK]))
        self.assertEqual([d.number for d in found], [0, 1])
        self.assertEqual(found[0].letters, ["C"])
        # Une partition unique arrive en objet et non en liste (ConvertTo-Json) : elle doit être gérée
        self.assertEqual(found[1].partitions[0].letter, "E")
        self.assertEqual(found[1].partitions[0].file_system, "exFAT")

    def test_single_disk_object(self):
        self.assertEqual(len(disks.parse_inventory(json.dumps(SYSTEM_DISK))), 1)

    def test_empty(self):
        self.assertEqual(disks.parse_inventory(""), [])

    def test_health_and_counters(self):
        data = dict(SYSTEM_DISK, MediaType="SSD", Health="Healthy", Temperature=38, Wear=2,
                    PowerOnHours=1520, ReadErrors=0)
        d = make(data)
        self.assertEqual((d.media_type, d.health, d.temperature, d.wear, d.power_on_hours, d.read_errors),
                         ("SSD", "Healthy", 38, 2, 1520, 0))
        self.assertEqual(disks.health_label(d), "Bon")
        self.assertFalse(disks.health_needs_attention(d))

    def test_missing_counters_are_not_reported(self):
        # Sans droits administrateur ou derrière un adaptateur USB : compteurs absents, température à 0
        d = make(dict(USB_DISK, Temperature=0, Wear=None))
        self.assertIsNone(d.temperature)
        self.assertIsNone(d.wear)
        self.assertIsNone(d.health)
        self.assertEqual(disks.health_label(d), "Non communiqué")

    def test_warning_needs_attention(self):
        self.assertTrue(disks.health_needs_attention(make(dict(USB_DISK, Health="Warning"))))
        self.assertTrue(disks.health_needs_attention(make(dict(USB_DISK, Health="Healthy", ReadErrors=3))))

    def test_free_space_and_usage(self):
        part = disks.Partition(number=1, size=1000, free=250)
        self.assertEqual(part.used_percent, 75)
        self.assertIsNone(disks.Partition(number=2, size=1000).used_percent)
        d = make(dict(USB_DISK, Partitions=[dict(USB_DISK["Partitions"], Free=32011579968)]))
        self.assertEqual(d.partitions[0].free, 32011579968)


class Protections(unittest.TestCase):
    def test_system_disk_is_protected(self):
        reasons = disks.protection_reasons(make(SYSTEM_DISK), "C", "C")
        self.assertIn("disque système de Windows", reasons)
        self.assertIn("disque de démarrage", reasons)

    def test_windows_letter_protects_even_without_flags(self):
        data = dict(USB_DISK, Partitions=[{"Number": 1, "Size": 1, "DriveLetter": "C"}])
        self.assertTrue(disks.protection_reasons(make(data), "C", None))

    def test_disk_running_edendisk_is_protected(self):
        reasons = disks.protection_reasons(make(USB_DISK), "C", "E")
        self.assertEqual(reasons, ["contient EdenDisk (lecteur E:)"])

    def test_offline_readonly_and_empty_reader(self):
        data = dict(USB_DISK, IsOffline=True, IsReadOnly=True, Size=0)
        self.assertEqual(len(disks.protection_reasons(make(data), "C", "C")), 3)

    def test_plain_usb_disk_is_allowed(self):
        self.assertEqual(disks.protection_reasons(make(USB_DISK), "C", "C"), [])


class Options(unittest.TestCase):
    def setUp(self):
        self.usb = make(USB_DISK)  # 64 Go

    def test_valid(self):
        self.assertEqual(disks.validate_options(self.usb, "NTFS", "Sauvegarde 2026", "GPT"), [])

    def test_fat32_over_32_gb_refused(self):
        self.assertTrue(disks.validate_options(self.usb, "FAT32", "CLE", "MBR"))

    def test_mbr_over_2_tb_refused(self):
        big = make(dict(USB_DISK, Size=4 * 1024**4))
        self.assertTrue(disks.validate_options(big, "NTFS", "X", "MBR"))

    def test_label_injection_refused(self):
        self.assertTrue(disks.validate_options(self.usb, "NTFS", "x'; Clear-Disk 0 #", "GPT"))

    def test_label_length(self):
        self.assertTrue(disks.validate_options(self.usb, "exFAT", "A" * 16, "GPT"))

    def test_unknown_values(self):
        self.assertEqual(len(disks.validate_options(self.usb, "ext4", "X", "APM")), 2)


class Script(unittest.TestCase):
    def test_script_rechecks_identity_and_protections(self):
        script = disks.build_prepare_script(make(USB_DISK), "NTFS", "DATA", "GPT")
        self.assertIn("Get-Disk -Number 1", script)
        self.assertIn("'USBSTOR\\DISK&VEN_SANDISK'", script)       # identité revérifiée
        self.assertIn("-ne 64023257088", script)                    # taille revérifiée
        self.assertIn("IsSystem -or $d.IsBoot", script)
        self.assertIn("$env:SystemDrive", script)
        self.assertIn("Initialize-Disk -Number 1 -PartitionStyle GPT", script)
        self.assertNotIn("diskpart", script.lower())

    def test_quotes_in_disk_name_are_escaped(self):
        script = disks.build_prepare_script(make(dict(USB_DISK, Name="Disk 'X'")), "NTFS", "DATA", "GPT")
        self.assertIn("'Disk ''X'''", script)

    def test_invalid_options_never_reach_script(self):
        with self.assertRaises(ValueError):
            disks.build_prepare_script(make(USB_DISK), "NTFS; Remove-Item", "DATA", "GPT")


class PrepareDisk(unittest.TestCase):
    def test_protected_disk_never_runs_powershell(self):
        with mock.patch.object(disks, "_run_powershell") as run:
            result = disks.prepare_disk(make(SYSTEM_DISK), "NTFS", "X", "GPT")
        self.assertFalse(result.ok)
        run.assert_not_called()

    def test_invalid_options_never_run_powershell(self):
        with mock.patch.object(disks, "_run_powershell") as run, \
             mock.patch.object(disks, "app_drive_letter", return_value="C"), \
             mock.patch.object(disks, "system_drive_letter", return_value="C"):
            result = disks.prepare_disk(make(USB_DISK), "FAT32", "X", "GPT")
        self.assertFalse(result.ok)
        run.assert_not_called()

    def test_success_reads_new_letter(self):
        done = subprocess.CompletedProcess([], 0, b"LETTRE=F\r\n", b"")
        with mock.patch.object(disks, "_run_powershell", return_value=done), \
             mock.patch.object(disks, "app_drive_letter", return_value="C"), \
             mock.patch.object(disks, "system_drive_letter", return_value="C"):
            result = disks.prepare_disk(make(USB_DISK), "NTFS", "DATA", "GPT")
        self.assertTrue(result.ok)
        self.assertEqual(result.letter, "F")

    def test_clixml_error_is_readable(self):
        clixml = ('#< CLIXML\r\n<Objs Version="1.1.0.1" xmlns="http://schemas.microsoft.com/powershell/2004/04">'
                  '<S S="Error">Le disque 1 ne correspond plus au disque s&#233;lectionn&#233;_x000D__x000A_</S>'
                  '<S S="Error">Au caract&#232;re Ligne:4 : 1_x000D__x000A_</S></Objs>')
        failed = subprocess.CompletedProcess([], 1, b"", clixml.encode("utf-8"))
        with mock.patch.object(disks, "_run_powershell", return_value=failed), \
             mock.patch.object(disks, "app_drive_letter", return_value="C"), \
             mock.patch.object(disks, "system_drive_letter", return_value="C"):
            result = disks.prepare_disk(make(USB_DISK), "NTFS", "DATA", "GPT")
        self.assertEqual(result.message, "Échec de la préparation : Le disque 1 ne correspond plus au disque sélectionné")

    def test_powershell_error_is_reported(self):
        failed = subprocess.CompletedProcess([], 1, b"", "Le disque 1 ne correspond plus\r\n".encode("utf-8"))
        with mock.patch.object(disks, "_run_powershell", return_value=failed), \
             mock.patch.object(disks, "app_drive_letter", return_value="C"), \
             mock.patch.object(disks, "system_drive_letter", return_value="C"):
            result = disks.prepare_disk(make(USB_DISK), "NTFS", "DATA", "GPT")
        self.assertFalse(result.ok)
        self.assertIn("ne correspond plus", result.message)


if __name__ == "__main__":
    unittest.main()
