import os
import subprocess

def compile_mo_files(locale_dir):
    msgfmt_path = r"C:\msys64\usr\bin\msgfmt.exe"

    for lang in os.listdir(locale_dir):
        lang_path = os.path.join(locale_dir, lang, "LC_MESSAGES")
        po_file = os.path.join(lang_path, "base.po")
        mo_file = os.path.join(lang_path, "base.mo")

        print(f"\nTraitement de la langue : {lang}")
        print(f"Fichier PO : {po_file}")
        print(f"Fichier MO : {mo_file}")

        if os.path.exists(po_file):
            try:
                # Compile toujours pour debug
                print(f"📦 Compilation de {po_file}...")
                result = subprocess.run(
                    [msgfmt_path, po_file, "-o", mo_file],
                    capture_output=True,
                    text=True
                )
                if result.returncode == 0:
                    print(f"✅ Compilation réussie pour la langue : {lang}")
                else:
                    print(f"❌ Erreur lors de la compilation pour {lang} :")
                    print(result.stderr)
            except Exception as e:
                print(f"Exception lors de la compilation de {lang}: {e}")
        else:
            print(f"⚠️ Fichier .po non trouvé pour la langue : {lang}")

if __name__ == "__main__":
    current_dir = os.path.dirname(__file__)
    locale_path = os.path.join(current_dir, "locale")
    compile_mo_files(locale_path)
