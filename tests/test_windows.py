"""Testes que só fazem sentido num Windows de verdade (rodam no GitHub Actions)."""
import sys
import time
import tkinter as tk

import pytest
from PIL import Image, ImageGrab

from conftest import ARTIFACTS

pytestmark = pytest.mark.skipif(sys.platform != "win32", reason="só no Windows")


@pytest.fixture(scope="module")
def mira():
    import mira as m
    return m


@pytest.fixture(scope="module")
def app(mira):
    a = mira.App()
    yield a
    a.quit()


def pump(app, seconds):
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        app.root.update()
        time.sleep(0.01)


def test_known_folders(mira):
    import os
    for name in ("desktop", "documents", "downloads"):
        assert os.path.isdir(mira.known_folder(name)), name
    assert mira.resolve_path("{desktop}") == mira.known_folder("desktop")


def test_file_icon_is_real(mira):
    img = mira.file_icon(r"C:\Windows\explorer.exe", 34)
    assert img is not None and img.mode == "RGBA" and img.size == (34, 34)
    lo, hi = img.getchannel("A").getextrema()
    assert lo == 0 and hi == 255  # tem transparência de verdade
    img.save(ARTIFACTS / "icone_explorer.png")


def test_folder_listing(mira):
    items = mira.folder_items(r"C:\Windows", 0, 34)
    assert items[0]["name"] == "Abrir pasta"
    assert len(items) == 12 and items[-1]["name"].startswith("Mais")
    nxt = mira.folder_items(r"C:\Windows", items[-1]["offset"], 34)
    assert nxt and nxt[0]["name"] != items[1]["name"]


def test_clipboard_roundtrip(mira):
    img = Image.new("RGB", (64, 40), (255, 42, 109))
    assert mira.copy_image_to_clipboard(img)
    back = ImageGrab.grabclipboard()
    assert isinstance(back, Image.Image) and back.size == (64, 40)


def test_games_scan_does_not_crash():
    import jogos
    assert isinstance(jogos.find_games(), list)


def test_wheel_is_transparent_on_screen(app):
    """Mostra a roda sobre uma janela branca e tira print da tela de verdade."""
    white = tk.Toplevel(app.root)
    white.overrideredirect(True)
    white.configure(bg="white")
    white.geometry("1000x740+0+0")
    pump(app, 0.3)
    app._open_wheel(500, 370)
    pump(app, 0.8)
    w = app.wheel
    ox, oy = w.origin
    shot = ImageGrab.grab(bbox=(ox, oy, ox + w.size, oy + w.size), all_screens=True)
    shot.save(ARTIFACTS / "roda_no_windows.png")
    app._close_wheel()
    white.destroy()
    corner = shot.getpixel((3, 3))
    core = shot.getpixel((w.size // 2, w.size // 2 + 30))
    assert min(corner[:3]) > 225, f"canto deveria ser transparente (branco), veio {corner}"
    assert max(core[:3]) < 80, f"núcleo da roda deveria ser escuro, veio {core}"


def test_mouse4_hook_opens_wheel(app):
    """Aperta o Mouse 4 de verdade (simulado) e confere se a roda abre e o Esc fecha."""
    from pynput import keyboard, mouse
    m, k = mouse.Controller(), keyboard.Controller()
    m.position = (500, 370)
    pump(app, 0.2)
    m.press(mouse.Button.x1)
    pump(app, 0.3)
    assert app.wheel.visible, "o hook do Mouse 4 não abriu a roda"
    m.release(mouse.Button.x1)
    pump(app, 0.3)
    assert app.wheel.visible  # clique rápido no centro: continua aberta
    k.press(keyboard.Key.esc)
    k.release(keyboard.Key.esc)
    pump(app, 0.3)
    assert not app.wheel.visible


def test_submenu_and_folder_layers(app):
    app._open_wheel(500, 370)
    pump(app, 0.2)
    arquivos = next(i for i in app.cfg["items"] if i["name"] == "Arquivos")
    app.activate(arquivos)
    assert app.wheel.depth == 1
    app.activate(arquivos["items"][0])  # Área de Trabalho
    assert app.wheel.depth == 2
    pump(app, 0.3)
    assert app.wheel.pop() and app.wheel.depth == 1
    app._close_wheel()


def test_print_screen_opens_snipper(app, monkeypatch):
    import recorte
    made = []
    orig = recorte.Snipper

    class Spy(orig):
        def __init__(self, *a, **kw):
            super().__init__(*a, **kw)
            made.append(self)

    monkeypatch.setattr(recorte, "Snipper", Spy)
    from pynput import keyboard
    k = keyboard.Controller()
    k.press(keyboard.Key.print_screen)
    k.release(keyboard.Key.print_screen)
    pump(app, 0.8)
    assert made, "PrtSc não abriu o recorte"
    s = made[0]

    class E:
        def __init__(self, x, y):
            self.x, self.y = x, y

    s._on_press(E(100, 100))
    s._on_drag(E(400, 300))
    s._on_release(E(400, 300))
    s.set_tool("arrow")
    s._on_press(E(380, 280))
    s._on_drag(E(150, 140))
    s._on_release(E(150, 140))
    pump(app, 0.3)
    ImageGrab.grab().save(ARTIFACTS / "recorte_no_windows.png")
    got = []
    s.on_done = lambda img, action: got.append((img, action))
    s.finish("copy")
    img, action = got[0]
    assert action == "copy" and img.size == (300, 200)
    assert not app.wheel.visible
