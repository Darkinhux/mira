"""
Atualização automática do Mira.exe pelas Releases do GitHub.

* Só fala com api.github.com (e o download vem das Releases do próprio repo).
* O .exe sabe o próprio número de build (gravado no _versao.py pelo CI).
* Baixa para "Mira.new.exe", confere tamanho, cabeçalho de .exe e SHA-256,
  e só então troca: o Windows deixa RENOMEAR um .exe em uso, então o atual
  vira "Mira.old.exe", o novo vira "Mira.exe" e é aberto. O .old é apagado
  na próxima vez que o Mira abrir.
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import urllib.request
from pathlib import Path

log = logging.getLogger("Mira")

REPO = "Darkinhux/mira"
API_LATEST = f"https://api.github.com/repos/{REPO}/releases/latest"
ASSET_NAME = "Mira.exe"
ALLOWED_DOWNLOAD_PREFIX = f"https://github.com/{REPO}/releases/download/"
USER_AGENT = "Mira-updater"

try:
    from _versao import BUILD, COMMIT  # gerado pelo CI no build do .exe
except ImportError:
    BUILD, COMMIT = 0, ""


def parse_build(tag: str) -> int:
    m = re.search(r"(\d+)$", tag or "")
    return int(m.group(1)) if m else 0


def latest_release(url: str = API_LATEST, timeout: float = 10) -> dict | None:
    """{"build", "tag", "url", "size", "sha256", "page"} da última Release, ou None."""
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT,
                                               "Accept": "application/vnd.github+json"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        data = json.load(resp)
    asset = next((a for a in data.get("assets", []) if a.get("name") == ASSET_NAME), None)
    if not asset:
        return None
    digest = str(asset.get("digest") or "")
    return {
        "build": parse_build(data.get("tag_name", "")),
        "tag": data.get("tag_name", ""),
        "url": asset.get("browser_download_url", ""),
        "size": int(asset.get("size") or 0),
        "sha256": digest.split(":", 1)[1].lower() if digest.startswith("sha256:") else "",
        "page": data.get("html_url", ""),
    }


def is_newer(info: dict | None, current: int = BUILD) -> bool:
    return bool(info) and current > 0 and info["build"] > current


def download(info: dict, dest: Path, progress=None, allow_any_url: bool = False) -> Path:
    """Baixa e confere o .exe novo. Levanta erro se algo não bater."""
    url = info["url"]
    if not allow_any_url and not url.startswith(ALLOWED_DOWNLOAD_PREFIX):
        raise ValueError(f"endereço de download inesperado: {url}")
    tmp = dest.with_suffix(dest.suffix + ".part")
    h = hashlib.sha256()
    got = 0
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=60) as resp, open(tmp, "wb") as f:
        while chunk := resp.read(256 * 1024):
            f.write(chunk)
            h.update(chunk)
            got += len(chunk)
            if progress and info.get("size"):
                progress(got / info["size"])
    try:
        if info.get("size") and got != info["size"]:
            raise ValueError(f"download incompleto ({got} de {info['size']} bytes)")
        with open(tmp, "rb") as f:
            if f.read(2) != b"MZ":
                raise ValueError("o arquivo baixado não é um .exe")
        if info.get("sha256") and h.hexdigest() != info["sha256"]:
            raise ValueError("o SHA-256 do arquivo baixado não confere")
        os.replace(tmp, dest)
    finally:
        if tmp.exists():
            tmp.unlink()
    return dest


def swap_exe(current: Path, new: Path) -> Path:
    """Mira.exe -> Mira.old.exe e Mira.new.exe -> Mira.exe. Devolve o caminho novo."""
    old = current.with_name(current.stem + ".old" + current.suffix)
    if old.exists():
        old.unlink()
    os.replace(current, old)
    try:
        os.replace(new, current)
    except OSError:
        os.replace(old, current)  # desfaz
        raise
    return current


def cleanup_old(current: Path) -> None:
    old = current.with_name(current.stem + ".old" + current.suffix)
    for p in (old, current.with_name(current.stem + ".new" + current.suffix)):
        try:
            if p.exists():
                p.unlink()
        except OSError:
            pass
