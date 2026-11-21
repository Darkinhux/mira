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


# ---------------------------------------------------------------- Ctrl+C
import copiados  # noqa: E402


def test_clipboard_history_dedupe_and_limits(tmp_path):
    h = copiados.ClipboardHistory(max_items=3)
    for t in ("um", "dois", "três", "dois", "   ", ""):
        h.add_text(t)
    assert [e.text for e in h.entries] == ["dois", "três", "um"]
    h.add_text("quatro")
    assert len(h.entries) == 3 and h.entries[0].text == "quatro"
    h.add_image(Image.new("RGB", (10, 10), "red"))
    assert h.entries[0].kind == "image" and h.entries[0].label() == "Imagem 10×10"
    assert copiados.Entry("text", text="https://youtube.com").icon() == "🔗"
    assert copiados.Entry("text", text="(11) 99999-0000").icon() == "🔢"


def test_clipboard_history_save_only_when_enabled(tmp_path):
    path = tmp_path / "copiados.json"
    h = copiados.ClipboardHistory(save_path=path)
    h.add_text("guardado")
    h.add_image(Image.new("RGB", (4, 4)))
    again = copiados.ClipboardHistory(save_path=path)
    assert [e.text for e in again.entries] == ["guardado"]  # imagens não vão pro disco
    copiados.ClipboardHistory().add_text("só memória")
    assert path.read_text(encoding="utf-8").count("só memória") == 0


# ---------------------------------------------------------------- migração e atualização
import atualizar  # noqa: E402
import migracao  # noqa: E402

V1_CONFIG = {  # config.json da primeira versão do Mira
    "trigger": "mouse5", "radius": 170, "accent": "#00ff00",
    "items": [
        {"name": "Steam", "icon": "🎮", "type": "open", "target": "steam://open/main"},
        {"name": "Discord", "icon": "💬", "type": "open", "target": "discord://"},
        {"name": "Recortar", "icon": "✂️", "type": "snip"},
        {"name": "Tela inteira", "icon": "🖥️", "type": "screenshot"},
        {"name": "Navegador", "icon": "🌐", "type": "open", "target": "https://www.google.com"},
        {"name": "Arquivos", "icon": "📁", "type": "open", "target": "explorer.exe"},
        {"name": "Meu jogo", "icon": "🕹️", "type": "open", "target": "C:\\\\jogo.exe"},
    ],
}


def test_migration_keeps_custom_and_adds_news():
    defaults = load_cfg()
    new, added, notes = migracao.migrate(V1_CONFIG, defaults)
    names = [i["name"] for i in new["items"]]
    assert new["trigger"] == "mouse5" and new["accent"] == "#00ff00"   # personalizado fica
    assert "Meu jogo" in names                                         # item próprio fica
    assert next(i for i in new["items"] if i["name"] == "Navegador")["type"] == "open"
    for news in ("Jogos", "Copiados", "Mídia", "Sistema"):
        assert news in names and news in added
    assert names.index("Copiados") == names.index("Recortar") + 1      # no lugar certo
    assert names[0] == "Jogos"
    assert {p["name"] for p in new["profiles"]} == {"Navegador", "Valorant"}
    assert "clipboard_history" in new and "update_check" in new
    assert len(names) <= 12 and not notes

    again, added2, _ = migracao.migrate(new, defaults)
    assert again == new and not added2                                 # nada de novo

    new["items"] = [i for i in new["items"] if i["name"] != "Jogos"]   # apagou de propósito
    new["profiles"] = []
    third, added3, _ = migracao.migrate(new, defaults)
    assert "Jogos" not in [i["name"] for i in third["items"]] and not added3
    assert third["profiles"] == []


def test_migration_full_wheel_warns():
    defaults = load_cfg()
    full = {"items": [{"name": f"Item {n}", "type": "snip"} for n in range(12)]}
    new, added, notes = migracao.migrate(full, defaults)
    assert len(new["items"]) == 12 and notes


def _fake_release(tmp_path, payload: bytes):
    import hashlib
    exe = tmp_path / "release.exe"
    exe.write_bytes(payload)
    api = tmp_path / "latest.json"
    api.write_text(json.dumps({
        "tag_name": "mira-v42", "html_url": "https://example/r",
        "assets": [{"name": "Mira.exe", "size": len(payload),
                    "browser_download_url": exe.as_uri(),
                    "digest": "sha256:" + hashlib.sha256(payload).hexdigest()}]}))
    return atualizar.latest_release(api.as_uri())


def test_update_check_and_download(tmp_path):
    info = _fake_release(tmp_path, b"MZ" + b"x" * 5000)
    assert info["build"] == 42 and info["size"] == 5002
    assert atualizar.is_newer(info, current=7) and not atualizar.is_newer(info, current=42)
    assert not atualizar.is_newer(info, current=0)  # versão de desenvolvimento não atualiza

    dest = tmp_path / "Mira.new.exe"
    import pytest
    with pytest.raises(ValueError):  # só aceita download das Releases do próprio repo
        atualizar.download(info, dest)
    atualizar.download(info, dest, allow_any_url=True)
    assert dest.read_bytes().startswith(b"MZ")

    bad = dict(info, sha256="0" * 64)
    with pytest.raises(ValueError, match="SHA-256"):
        atualizar.download(bad, tmp_path / "x.exe", allow_any_url=True)
    assert not (tmp_path / "x.exe").exists()

    not_exe = _fake_release(tmp_path, b"<html>erro</html>")
    with pytest.raises(ValueError, match="não é um .exe"):
        atualizar.download(not_exe, tmp_path / "y.exe", allow_any_url=True)


def test_swap_exe(tmp_path):
    cur, new = tmp_path / "Mira.exe", tmp_path / "Mira.new.exe"
    cur.write_bytes(b"MZ velho")
    new.write_bytes(b"MZ novo")
    atualizar.swap_exe(cur, new)
    assert cur.read_bytes() == b"MZ novo" and (tmp_path / "Mira.old.exe").exists()
    atualizar.cleanup_old(cur)
    assert not (tmp_path / "Mira.old.exe").exists() and cur.exists()


# ---------------------------------------------------------------- OCR
import ocr  # noqa: E402


def test_ocr_prepare_scales():
    small = ocr.prepare(Image.new("RGB", (200, 40)))
    assert small.width > 200 and small.height > 40          # texto pequeno é ampliado
    big = ocr.prepare(Image.new("RGB", (12000, 300)))
    assert max(big.size) <= ocr.MAX_SIDE                      # limite do motor do Windows
    normal = ocr.prepare(Image.new("RGB", (1200, 800)))
    assert normal.size == (1200, 800)
