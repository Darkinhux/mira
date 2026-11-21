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
    app_done = s.on_done
    # guarda o resultado e avisa o app que o recorte terminou (como no uso normal)
    s.on_done = lambda img, action: (got.append((img, action)), app_done(None, None))
    s.finish("copy")
    img, action = got[0]
    assert action == "copy" and img.size == (300, 200)
    assert not app.wheel.visible
    assert not app.snipping


# ---------------------------------------------------------------- Ctrl+C e perfis
def _focus_tk_entry(app):
    """Abre uma caixa de texto nossa e traz para a frente (truque do Alt do Windows)."""
    import ctypes
    win = tk.Toplevel(app.root)
    win.geometry("400x80+200+200")
    entry = tk.Entry(win, width=40)
    entry.pack()
    pump(app, 0.3)
    u = ctypes.windll.user32
    hwnd = int(win.wm_frame(), 16)
    u.keybd_event(0x12, 0, 0, 0)          # Alt
    u.SetForegroundWindow(hwnd)
    u.keybd_event(0x12, 0, 2, 0)
    entry.focus_force()
    pump(app, 0.4)
    return win, entry


def test_clipboard_capture_and_private(app, mira):
    import copiados
    import ctypes
    pump(app, 0.7)
    assert copiados.write_text("olá do teste do Mira")
    pump(app, 0.8)
    assert app.clips.entries and app.clips.entries[0].text == "olá do teste do Mira"

    # gerenciador de senhas: marca como privado -> não pode entrar no histórico
    u, k = ctypes.windll.user32, ctypes.windll.kernel32
    k.GlobalAlloc.restype = ctypes.c_void_p
    k.GlobalLock.restype = ctypes.c_void_p
    u.SetClipboardData.argtypes = [ctypes.c_uint, ctypes.c_void_p]
    fmt = u.RegisterClipboardFormatW("ExcludeClipboardContentFromMonitorProcessing")
    data = "senha-super-secreta\0".encode("utf-16-le")
    h = k.GlobalAlloc(2, len(data))
    ctypes.memmove(k.GlobalLock(ctypes.c_void_p(h)), data, len(data))
    k.GlobalUnlock(ctypes.c_void_p(h))
    marker = k.GlobalAlloc(2, 4)
    assert u.OpenClipboard(None)
    u.EmptyClipboard()
    u.SetClipboardData(13, h)
    u.SetClipboardData(fmt, marker)
    u.CloseClipboard()
    pump(app, 0.8)
    assert all("senha" not in (e.text or "") for e in app.clips.entries)


def test_paste_from_history_and_profile(app, mira):
    win, entry = _focus_tk_entry(app)
    try:
        exe, _ = mira.foreground_app()
        assert exe.startswith("python"), f"janela da frente: {exe!r}"

        # perfil para o próprio python.exe: a roda tem que abrir com ele
        app.cfg["profiles"].insert(0, {"name": "Teste", "match": ["python*.exe"], "title": [],
                                       "items": [{"name": "A", "type": "keys", "keys": "a"},
                                                 {"name": "Geral", "type": "default"}]})
        app.wheel.rebuild()
        app._open_wheel(500, 370)
        pump(app, 0.2)
        assert app.wheel.layer.title == "Teste"
        app.activate(app.wheel.layer.items[1])  # Geral -> roda normal
        assert app.wheel.layer.items == app.cfg["items"]
        app._close_wheel()

        # colar do histórico
        app.clips.add_text("colado pelo Mira")
        entry.focus_force()
        pump(app, 0.2)
        app.paste_clip(app.clips.entries[0])
        pump(app, 0.6)
        assert entry.get() == "colado pelo Mira"
    finally:
        app.cfg["profiles"].pop(0)
        app.wheel.rebuild()
        win.destroy()


# ---------------------------------------------------------------- OCR
def test_ocr_engine_reads_text():
    import ocr
    from PIL import ImageDraw, ImageFont
    img = Image.new("RGB", (900, 140), "white")
    ImageDraw.Draw(img).text((20, 30), "MIRA OCR 2026", fill="black",
                             font=ImageFont.truetype(r"C:\Windows\Fonts\arialbd.ttf", 64))
    text = ocr.extract_text(img)
    assert "MIRA" in text.upper() and "2026" in text, text


def test_shift_printscreen_copies_text(app, monkeypatch):
    import copiados
    import recorte
    from pynput import keyboard

    made, toasts = [], []
    orig = recorte.Snipper

    class Spy(orig):
        def __init__(self, *a, **kw):
            super().__init__(*a, **kw)
            made.append(self)

    monkeypatch.setattr(recorte, "Snipper", Spy)
    real_toast = app.toast
    monkeypatch.setattr(app, "toast", lambda text, *a, **kw: (toasts.append(text),
                                                               real_toast(text, *a, **kw)))

    win = tk.Toplevel(app.root)
    win.overrideredirect(True)
    win.attributes("-topmost", True)
    win.configure(bg="white")
    win.geometry("760x170+100+100")
    tk.Label(win, text="MIRA OCR 2026", font=("Arial", 54, "bold"), bg="white",
             fg="black").pack(expand=True)
    pump(app, 0.6)
    try:
        assert copiados.write_text("(vazio)")  # nada de testes anteriores na área de transferência
        k = keyboard.Controller()
        with k.pressed(keyboard.Key.shift):
            k.press(keyboard.Key.print_screen)
            k.release(keyboard.Key.print_screen)
        pump(app, 0.8)
        assert made and made[-1].ocr_mode, "Shift+PrtSc não abriu o recorte de texto"

        class E:
            def __init__(self, x, y):
                self.x, self.y = x, y

        s = made[-1]
        s._on_press(E(105, 105))
        s._on_drag(E(855, 265))
        s._on_release(E(855, 265))
        end = time.monotonic() + 45
        while time.monotonic() < end and "2026" not in (copiados.read_text() or ""):
            pump(app, 0.3)
        text = copiados.read_text() or ""
        assert "MIRA" in text.upper() and "2026" in text, f"copiado: {text!r} / avisos: {toasts}"
    finally:
        win.destroy()
