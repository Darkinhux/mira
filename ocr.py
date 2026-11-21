"""
OCR (copiar texto de uma imagem) com o motor que já vem no Windows 10/11
(Windows.Media.Ocr). Funciona sem internet e sem instalar nada: o Mira chama o
PowerShell do próprio Windows, que acessa a API do sistema.

O idioma vem das configurações do Windows (Configurações → Hora e idioma).
Se não houver pacote de OCR para o idioma, o Windows oferece instalar em
Configurações → Hora e idioma → Idioma → (seu idioma) → Opções.
"""
from __future__ import annotations

import os
import subprocess
import sys
import tempfile
from pathlib import Path

from PIL import Image

IS_WIN = sys.platform == "win32"

PS_SCRIPT = r"""
param([string]$Path)
$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
Add-Type -AssemblyName System.Runtime.WindowsRuntime
$null = [Windows.Storage.StorageFile, Windows.Storage, ContentType = WindowsRuntime]
$null = [Windows.Media.Ocr.OcrEngine, Windows.Foundation, ContentType = WindowsRuntime]
$null = [Windows.Graphics.Imaging.BitmapDecoder, Windows.Graphics, ContentType = WindowsRuntime]
$asTask = ([System.WindowsRuntimeSystemExtensions].GetMethods() | Where-Object {
    $_.Name -eq 'AsTask' -and $_.GetParameters().Count -eq 1 -and
    $_.GetParameters()[0].ParameterType.Name -eq 'IAsyncOperation`1' })[0]
function Await($op, [Type]$type) {
    $task = $asTask.MakeGenericMethod($type).Invoke($null, @($op))
    $task.Wait(-1) | Out-Null
    $task.Result
}
$engine = [Windows.Media.Ocr.OcrEngine]::TryCreateFromUserProfileLanguages()
if ($engine -eq $null) {
    $en = New-Object Windows.Globalization.Language 'en-US'
    $engine = [Windows.Media.Ocr.OcrEngine]::TryCreateFromLanguage($en)
}
if ($engine -eq $null) { [Console]::Error.WriteLine('SEM_IDIOMA'); exit 3 }
$file = Await ([Windows.Storage.StorageFile]::GetFileFromPathAsync($Path)) ([Windows.Storage.StorageFile])
$stream = Await ($file.OpenAsync([Windows.Storage.FileAccessMode]::Read)) ([Windows.Storage.Streams.IRandomAccessStream])
$decoder = Await ([Windows.Graphics.Imaging.BitmapDecoder]::CreateAsync($stream)) ([Windows.Graphics.Imaging.BitmapDecoder])
$bitmap = Await ($decoder.GetSoftwareBitmapAsync()) ([Windows.Graphics.Imaging.SoftwareBitmap])
$result = Await ($engine.RecognizeAsync($bitmap)) ([Windows.Media.Ocr.OcrResult])
foreach ($line in $result.Lines) { [Console]::Out.WriteLine($line.Text) }
$stream.Dispose()
"""

MAX_SIDE = 9000  # limite do motor do Windows é ~10000 px


class OcrError(Exception):
    pass


def prepare(img: Image.Image) -> Image.Image:
    """Texto pequeno é lido melhor ampliado; imagens enormes são reduzidas."""
    img = img.convert("RGB")
    w, h = img.size
    if max(w, h) > MAX_SIDE:
        img.thumbnail((MAX_SIDE, MAX_SIDE), Image.LANCZOS)
    elif w * h < 400_000:  # recortes pequenos: amplia até ~3x
        f = min(3.0, (400_000 / max(1, w * h)) ** 0.5, MAX_SIDE / max(w, h))
        if f > 1.2:
            img = img.resize((round(w * f), round(h * f)), Image.LANCZOS)
    return img


def extract_text(img: Image.Image, timeout: float = 40) -> str:
    if not IS_WIN:
        raise OcrError("o OCR usa o motor do Windows e só funciona no Windows")
    tmp = Path(tempfile.mkdtemp(prefix="mira-ocr-"))
    try:
        png = tmp / "recorte.png"
        script = tmp / "ocr.ps1"
        prepare(img).save(png)
        script.write_text(PS_SCRIPT, encoding="utf-8-sig")
        proc = subprocess.run(
            ["powershell.exe", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass",
             "-File", str(script), "-Path", str(png)],
            capture_output=True, timeout=timeout,
            creationflags=0x08000000,  # CREATE_NO_WINDOW: sem piscar janela preta
        )
        out = proc.stdout.decode("utf-8", "replace").strip()
        err = proc.stderr.decode("utf-8", "replace").strip()
        if proc.returncode == 3 or "SEM_IDIOMA" in err:
            raise OcrError("o Windows não tem pacote de OCR para o seu idioma. Instale em "
                           "Configurações → Hora e idioma → Idioma → Opções")
        if proc.returncode != 0:
            raise OcrError(err.splitlines()[-1] if err else f"PowerShell saiu com {proc.returncode}")
        return "\n".join(line.rstrip() for line in out.splitlines()).strip()
    except subprocess.TimeoutExpired:
        raise OcrError("o OCR demorou demais") from None
    except FileNotFoundError:
        raise OcrError("PowerShell não encontrado") from None
    finally:
        for f in tmp.glob("*"):
            try:
                f.unlink()
            except OSError:
                pass
        try:
            os.rmdir(tmp)
        except OSError:
            pass
