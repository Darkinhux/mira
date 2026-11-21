"""
Descobre os jogos instalados para a camada "Jogos ▸".

Lê só arquivos locais (sem login, sem internet):
  * Steam: libraryfolders.vdf + appmanifest_*.acf de cada biblioteca
  * Epic Games: manifestos .item em ProgramData
  * Riot: RiotClientInstalls.json + pasta Metadata (Valorant, LoL, LoR)

Cada jogo vira um item da roda ({"name", "icon", "type": "open", "target", ...}).
Os jogados mais recentemente vêm primeiro (quando a Steam informa).
"""
from __future__ import annotations

import json
import logging
import os
import re
import sys
from pathlib import Path

IS_WIN = sys.platform == "win32"
log = logging.getLogger("Mira")

# coisas da Steam que não são jogos
STEAM_SKIP_IDS = {"228980", "1070560", "1391110", "1628350", "1493710", "1826330", "2180100"}
STEAM_SKIP_WORDS = ("redistributable", "steamworks common", "proton", "steam linux runtime",
                    "steamvr", "dedicated server", "sdk")


# --------------------------------------------------------------------------
# VDF (formato de configuração da Steam)
# --------------------------------------------------------------------------
_VDF_TOKEN = re.compile(r'"((?:[^"\\]|\\.)*)"|([{}])')


def parse_vdf(text: str) -> dict:
    """Lê VDF em texto. As chaves ficam em minúsculas."""
    tokens = _VDF_TOKEN.findall(text)
    pos = 0

    def block() -> dict:
        nonlocal pos
        out: dict = {}
        key = None
        while pos < len(tokens):
            string, brace = tokens[pos]
            pos += 1
            if brace == "}":
                return out
            if brace == "{":
                if key is not None:
                    out[key] = block()
                    key = None
                continue
            value = string.replace("\\\\", "\\").replace('\\"', '"')
            if key is None:
                key = value.lower()
            else:
                out[key] = value
                key = None
        return out

    return block()


def _read_vdf(path: Path) -> dict:
    try:
        return parse_vdf(path.read_text(encoding="utf-8", errors="replace"))
    except OSError:
        return {}


# --------------------------------------------------------------------------
# Steam
# --------------------------------------------------------------------------
def steam_root() -> Path | None:
    if IS_WIN:
        import winreg

        for hive, sub, name in (
            (winreg.HKEY_CURRENT_USER, r"Software\Valve\Steam", "SteamPath"),
            (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\WOW6432Node\Valve\Steam", "InstallPath"),
            (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Valve\Steam", "InstallPath"),
        ):
            try:
                with winreg.OpenKey(hive, sub) as k:
                    p = Path(winreg.QueryValueEx(k, name)[0])
                if p.is_dir():
                    return p
            except OSError:
                pass
        candidates = [r"C:\Program Files (x86)\Steam", r"C:\Program Files\Steam"]
    else:
        candidates = ["~/.steam/steam", "~/.local/share/Steam",
                      "~/Library/Application Support/Steam"]
    for c in candidates:
        p = Path(os.path.expanduser(c))
        if p.is_dir():
            return p
    return None


def steam_libraries(root: Path) -> list[Path]:
    libs = [root]
    data = _read_vdf(root / "steamapps" / "libraryfolders.vdf").get("libraryfolders", {})
    for value in data.values():
        path = value.get("path") if isinstance(value, dict) else value  # formato novo / antigo
        if isinstance(path, str) and path:
            p = Path(path)
            if p.is_dir() and p.resolve() not in {lib.resolve() for lib in libs}:
                libs.append(p)
    return libs


def steam_icon(root: Path, appid: str) -> str | None:
    cache = root / "appcache" / "librarycache"
    old = cache / f"{appid}_icon.jpg"  # Steam antiga
    if old.exists():
        return str(old)
    folder = cache / appid  # Steam nova: o ícone é um arquivo com nome de hash
    if folder.is_dir():
        icons = [f for f in folder.iterdir()
                 if f.suffix.lower() in (".jpg", ".png", ".ico")
                 and re.fullmatch(r"[0-9a-f]{40}", f.stem)]
        if icons:
            return str(min(icons, key=lambda f: f.stat().st_size))
    return None


def steam_games(root: Path | None = None) -> list[dict]:
    root = root or steam_root()
    if not root:
        return []
    games, seen = [], set()
    for lib in steam_libraries(root):
        for acf in sorted((lib / "steamapps").glob("appmanifest_*.acf")):
            st = _read_vdf(acf).get("appstate", {})
            appid, name = st.get("appid"), st.get("name")
            if not appid or not name or appid in seen or appid in STEAM_SKIP_IDS:
                continue
            if any(w in name.lower() for w in STEAM_SKIP_WORDS):
                continue
            seen.add(appid)
            games.append({
                "name": name,
                "icon": steam_icon(root, appid) or "🎮",
                "type": "open",
                "target": f"steam://rungameid/{appid}",
                "_last": int(st.get("lastplayed", "0") or 0),
                "_source": "steam",
            })
    return games


# --------------------------------------------------------------------------
# Epic Games
# --------------------------------------------------------------------------
def _programdata() -> Path:
    return Path(os.environ.get("PROGRAMDATA", r"C:\ProgramData"))


def epic_games(manifests: Path | None = None) -> list[dict]:
    manifests = manifests or _programdata() / "Epic" / "EpicGamesLauncher" / "Data" / "Manifests"
    games = []
    for f in sorted(manifests.glob("*.item")) if manifests.is_dir() else []:
        try:
            j = json.loads(f.read_text(encoding="utf-8", errors="replace"))
        except (OSError, ValueError):
            continue
        cats = [str(c).lower() for c in j.get("AppCategories", [])]
        if cats and "games" not in cats:
            continue
        name, app = j.get("DisplayName"), j.get("AppName")
        ns, cid = j.get("CatalogNamespace", ""), j.get("CatalogItemId", "")
        if not name or not app:
            continue
        exe = Path(j.get("InstallLocation", "")) / j.get("LaunchExecutable", "")
        games.append({
            "name": name,
            "icon": "🎮",
            "icon_file": str(exe) if exe.is_file() else None,
            "type": "open",
            "target": f"com.epicgames.launcher://apps/{ns}%3A{cid}%3A{app}"
                      "?action=launch&silent=true",
            "_last": 0,
            "_source": "epic",
        })
    return games


# --------------------------------------------------------------------------
# Riot
# --------------------------------------------------------------------------
RIOT_PRODUCTS = {
    "valorant": ("VALORANT", "🔫"),
    "league_of_legends": ("League of Legends", "⚔️"),
    "bacon": ("Legends of Runeterra", "🃏"),
}


def riot_games(base: Path | None = None) -> list[dict]:
    base = base or _programdata() / "Riot Games"
    try:
        data = json.loads((base / "RiotClientInstalls.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    client = data.get("rc_default") or data.get("rc_live")
    if not client or not Path(client).is_file():
        return []
    games = []
    for pid, (name, emoji) in RIOT_PRODUCTS.items():
        if (base / "Metadata" / f"{pid}.live").is_dir():
            games.append({
                "name": name, "icon": emoji, "type": "open", "target": client,
                "args": [f"--launch-product={pid}", "--launch-patchline=live"],
                "_last": 0, "_source": "riot",
            })
    return games


# --------------------------------------------------------------------------
SOURCES = {"steam": steam_games, "epic": epic_games, "riot": riot_games}


def find_games(sources=("steam", "epic", "riot")) -> list[dict]:
    games = []
    for src in sources:
        fn = SOURCES.get(str(src).lower())
        if not fn:
            continue
        try:
            games += fn()
        except Exception:
            log.exception("falha ao procurar jogos (%s)", src)
    # jogados recentemente primeiro; depois em ordem alfabética
    games.sort(key=lambda g: (-g.get("_last", 0), g["name"].lower()))
    return games
