"""Testes que rodam em qualquer sistema (não precisam de tela)."""
import json

from PIL import Image, ImageDraw

import jogos
import neon
import recorte
from conftest import ARTIFACTS, ROOT


def load_cfg():
    return json.loads((ROOT / "config.json").read_text(encoding="utf-8"))


def test_wheel_frame_has_transparency():
    w = neon.NeonWheel(load_cfg())
    img = w.frame(None, 1.0)
    assert img.mode == "RGBA" and img.size == (w.size, w.size)
    assert img.getpixel((1, w.size // 2))[3] == 0  # borda transparente
    c = w.size // 2
    assert img.getpixel((c, c + 30))[3] > 200  # núcleo opaco
    img.save(ARTIFACTS / "roda_render.png")


def test_layers_and_branches():
    cfg = load_cfg()
    kinds = {i["type"] for i in cfg["items"]}
    assert {"games", "menu"} <= kinds
    for item in cfg["items"]:
        if item["type"] == "menu":
            w = neon.NeonWheel(cfg, item["items"], item["name"], "MIRA.SYS / X", 1)
            w.frame(0, 1.0, 1.0, True, 0.5)


def _base():
    img = Image.new("RGB", (200, 120), "white")
    d = ImageDraw.Draw(img)
    for x in range(0, 200, 4):
        d.line([(x, 0), (x, 120)], fill=(x, 0, 255 - x))
    return img


def test_blur_pixelates_only_inside():
    base = _base()
    annos = [{"kind": "blur", "points": [(10, 10), (110, 70)], "color": "#000000", "width": 4}]
    out = recorte.render(base, annos, (0, 0), 1.0).convert("RGB")
    block = recorte.blur_block(4)
    inside = out.crop((10, 10, 10 + block, 10 + block))
    assert len(inside.getcolors(256)) <= 2  # virou blocos
    assert out.getpixel((150, 100)) == base.getpixel((150, 100))  # fora não mudou


def test_all_tools_render():
    annos = [
        {"kind": k, "points": [(20, 20), (80, 60), (120, 90)], "color": "#ff2a6d", "width": 4}
        for k in ("pen", "marker", "line", "arrow", "rect", "blur")
    ] + [{"kind": "text", "points": [(30, 30)], "text": "oi", "color": "#00f0ff",
          "width": 4, "size": 24}]
    out = recorte.render(_base(), annos, (0, 0), 1.0, ss=2)
    assert out.size == (200, 120)


VDF = '''
"libraryfolders"
{
    "0" { "path" "%s" "apps" { "730" "1" } }
}
'''


def test_vdf_parser():
    d = jogos.parse_vdf('"AppState" { "appid" "730" "name" "Counter-Strike 2" "x" { } }')
    assert d["appstate"]["appid"] == "730"
    assert d["appstate"]["name"] == "Counter-Strike 2"


def test_steam_scan(tmp_path):
    root = tmp_path / "Steam"
    apps = root / "steamapps"
    apps.mkdir(parents=True)
    (apps / "libraryfolders.vdf").write_text(VDF % str(root).replace("\\", "\\\\"))
    for appid, name, last in (("730", "Counter-Strike 2", 200), ("228980", "Steamworks Common Redistributables", 0),
                              ("570", "Dota 2", 100), ("1245620", "ELDEN RING", 0)):
        (apps / f"appmanifest_{appid}.acf").write_text(
            f'"AppState" {{ "appid" "{appid}" "name" "{name}" "LastPlayed" "{last}" }}')
    icon_dir = root / "appcache" / "librarycache" / "570"
    icon_dir.mkdir(parents=True)
    Image.new("RGB", (32, 32), "red").save(icon_dir / ("a" * 40 + ".jpg"))
    Image.new("RGB", (460, 215), "blue").save(icon_dir / "header.jpg")

    games = jogos.steam_games(root)
    games.sort(key=lambda g: (-g["_last"], g["name"]))
    assert [g["name"] for g in games] == ["Counter-Strike 2", "Dota 2", "ELDEN RING"]
    assert games[0]["target"] == "steam://rungameid/730"
    assert games[1]["icon"].endswith("a" * 40 + ".jpg")
    assert games[2]["icon"] == "🎮"


def test_epic_and_riot_scan(tmp_path):
    man = tmp_path / "Manifests"
    man.mkdir()
    exe_dir = tmp_path / "Fortnite"
    exe_dir.mkdir()
    (exe_dir / "game.exe").write_text("x")
    (man / "a.item").write_text(json.dumps({
        "DisplayName": "Fortnite", "AppName": "Fortnite", "CatalogNamespace": "fn",
        "CatalogItemId": "abc", "AppCategories": ["public", "games"],
        "InstallLocation": str(exe_dir), "LaunchExecutable": "game.exe"}))
    (man / "b.item").write_text(json.dumps({
        "DisplayName": "Unreal Engine", "AppName": "UE", "AppCategories": ["engines"]}))
    games = jogos.epic_games(man)
    assert [g["name"] for g in games] == ["Fortnite"]
    assert games[0]["target"].startswith("com.epicgames.launcher://apps/fn%3Aabc%3AFortnite")

    riot = tmp_path / "Riot Games"
    (riot / "Metadata" / "valorant.live").mkdir(parents=True)
    client = tmp_path / "RiotClientServices.exe"
    client.write_text("x")
    (riot / "RiotClientInstalls.json").write_text(json.dumps({"rc_default": str(client)}))
    r = jogos.riot_games(riot)
    assert [g["name"] for g in r] == ["VALORANT"]
    assert "--launch-product=valorant" in r[0]["args"]
