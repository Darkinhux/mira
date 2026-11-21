"""Gera dist/Mira.exe (não precisa de Python instalado para rodar).

Uso:  python build_exe.py      (ou dois cliques em criar_exe.bat)
"""
import os
from pathlib import Path

import PyInstaller.__main__

import neon

ROOT = Path(__file__).resolve().parent
BUILD = ROOT / "build"
BUILD.mkdir(exist_ok=True)

# número do build (o CI usa o mesmo número na Release) para a atualização automática
(ROOT / "_versao.py").write_text(
    f"BUILD = {int(os.environ.get('GITHUB_RUN_NUMBER', '0'))}\n"
    f"COMMIT = {os.environ.get('GITHUB_SHA', '')!r}\n", encoding="utf-8")

icon = BUILD / "mira.ico"
neon.tray_image("#00f0ff", "#ff2a6d", 256).save(
    icon, sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])

PyInstaller.__main__.run([
    str(ROOT / "mira.py"),
    "--name", "Mira",
    "--onefile",
    "--noconsole",
    "--noconfirm",
    "--icon", str(icon),
    "--distpath", str(ROOT / "dist"),
    "--workpath", str(BUILD / "pyinstaller"),
    "--specpath", str(BUILD),
    # o pynput e o pystray escolhem o "backend" na hora de rodar
    "--hidden-import", "pynput.keyboard._win32",
    "--hidden-import", "pynput.mouse._win32",
    "--hidden-import", "pystray._win32",
])
print("\nPronto: dist\\Mira.exe")
