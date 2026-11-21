"""
Mira — roda de atalhos acionada por um botão do mouse (padrão: Mouse 4).

Como usar:
  * Segure o Mouse 4, mova o cursor na direção do atalho e solte.
  * Ou dê um clique rápido no Mouse 4: a roda fica aberta e você clica no atalho.
  * Esc, clique direito ou clique no centro fecham a roda.

Os atalhos ficam em config.json (ao lado deste arquivo).
"""
from __future__ import annotations

import ctypes
import io
import json
import logging
import math
import os
import queue
import subprocess
import sys
import time
import tkinter as tk
from datetime import datetime
from pathlib import Path
from tkinter import messagebox

IS_WIN = sys.platform == "win32"

# Precisa vir antes de qualquer janela/captura para que as coordenadas do
# cursor, das janelas e dos prints batam em telas com escala (125%, 150%...).
if IS_WIN:
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(2)
    except Exception:
        try:
            ctypes.windll.user32.SetProcessDPIAware()
        except Exception:
            pass

import threading  # noqa: E402

from PIL import Image, ImageChops, ImageEnhance, ImageGrab, ImageTk  # noqa: E402
from pynput import keyboard, mouse  # noqa: E402

import neon  # noqa: E402

APP_NAME = "Mira"
BASE_DIR = Path(__file__).resolve().parent
CONFIG_PATH = BASE_DIR / "config.json"
LOG_PATH = BASE_DIR / "mira.log"

logging.basicConfig(
    filename=LOG_PATH,
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
)
log = logging.getLogger(APP_NAME)

DEFAULT_CONFIG: dict = {
    "trigger": "mouse4",
    "radius": 170,
    "inner_radius": 55,
    "icon_size": 34,
    "neon": "#00f0ff",
    "accent": "#ff2a6d",
    "background": "#0b0b16",
    "text_color": "#e9fbff",
    "animations": True,
    "screenshot_folder": "~/Pictures/Mira",
    "items": [
        {"name": "Steam", "icon": "🎮", "type": "open", "target": "steam://open/main"},
        {"name": "Discord", "icon": "💬", "type": "open", "target": "discord://"},
        {"name": "Recortar", "icon": "✂️", "type": "snip"},
        {"name": "Tela inteira", "icon": "🖥️", "type": "screenshot"},
        {"name": "Navegador", "icon": "🌐", "type": "open", "target": "https://www.google.com"},
        {"name": "Arquivos", "icon": "📁", "type": "open", "target": "explorer.exe"},
        {"name": "Play/Pause", "icon": "⏯️", "type": "keys", "keys": "media_play_pause"},
        {"name": "Gerenciador", "icon": "📊", "type": "keys", "keys": "ctrl+shift+esc"},
    ],
}

# trigger -> (tipo, número do XBUTTON)
TRIGGERS = {
    "mouse4": ("x", 1),
    "mouse5": ("x", 2),
    "middle": ("m", 0),
}

# Mensagens do hook de mouse do Windows
WM_LBUTTONDOWN, WM_LBUTTONUP = 0x0201, 0x0202
WM_RBUTTONDOWN, WM_RBUTTONUP = 0x0204, 0x0205
WM_MBUTTONDOWN, WM_MBUTTONUP = 0x0207, 0x0208
WM_XBUTTONDOWN, WM_XBUTTONUP = 0x020B, 0x020C


# --------------------------------------------------------------------------
# Configuração
# --------------------------------------------------------------------------
def load_config() -> dict:
    if not CONFIG_PATH.exists():
        CONFIG_PATH.write_text(
            json.dumps(DEFAULT_CONFIG, ensure_ascii=False, indent=2), encoding="utf-8"
        )
    with CONFIG_PATH.open(encoding="utf-8") as f:
        user = json.load(f)
    cfg = {**DEFAULT_CONFIG, **user}
    items = [i for i in cfg.get("items", []) if isinstance(i, dict) and i.get("name")]
    if len(items) < 2:
        raise ValueError("config.json precisa ter pelo menos 2 itens em \"items\".")
    if len(items) > 12:
        raise ValueError("config.json aceita no máximo 12 itens em \"items\".")
    if cfg["trigger"] not in TRIGGERS:
        raise ValueError(f"\"trigger\" deve ser um de: {', '.join(TRIGGERS)}")
    cfg["items"] = items
    return cfg


# --------------------------------------------------------------------------
# Funções do Windows (via ctypes, sem dependências extras)
# --------------------------------------------------------------------------
if IS_WIN:
    from ctypes import wintypes

    _user32 = ctypes.WinDLL("user32", use_last_error=True)
    _kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

    _user32.GetCursorPos.argtypes = [ctypes.POINTER(wintypes.POINT)]
    _user32.GetSystemMetrics.argtypes = [ctypes.c_int]
    _user32.GetSystemMetrics.restype = ctypes.c_int
    _user32.GetParent.argtypes = [wintypes.HWND]
    _user32.GetParent.restype = wintypes.HWND
    _user32.GetWindowLongW.argtypes = [wintypes.HWND, ctypes.c_int]
    _user32.GetWindowLongW.restype = ctypes.c_long
    _user32.SetWindowLongW.argtypes = [wintypes.HWND, ctypes.c_int, ctypes.c_long]
    _user32.SetWindowLongW.restype = ctypes.c_long
    _user32.OpenClipboard.argtypes = [wintypes.HWND]
    _user32.SetClipboardData.argtypes = [wintypes.UINT, wintypes.HANDLE]
    _user32.SetClipboardData.restype = wintypes.HANDLE
    _kernel32.GlobalAlloc.argtypes = [wintypes.UINT, ctypes.c_size_t]
    _kernel32.GlobalAlloc.restype = wintypes.HGLOBAL
    _kernel32.GlobalLock.argtypes = [wintypes.HGLOBAL]
    _kernel32.GlobalLock.restype = ctypes.c_void_p
    _kernel32.GlobalUnlock.argtypes = [wintypes.HGLOBAL]
    _kernel32.GlobalFree.argtypes = [wintypes.HGLOBAL]
    _kernel32.CreateMutexW.argtypes = [ctypes.c_void_p, wintypes.BOOL, wintypes.LPCWSTR]
    _kernel32.CreateMutexW.restype = wintypes.HANDLE

    # --- janela com transparência por pixel (UpdateLayeredWindow) ---
    _gdi32 = ctypes.WinDLL("gdi32", use_last_error=True)

    class BLENDFUNCTION(ctypes.Structure):
        _fields_ = [("BlendOp", ctypes.c_ubyte), ("BlendFlags", ctypes.c_ubyte),
                    ("SourceConstantAlpha", ctypes.c_ubyte), ("AlphaFormat", ctypes.c_ubyte)]

    class BITMAPINFOHEADER(ctypes.Structure):
        _fields_ = [("biSize", wintypes.DWORD), ("biWidth", wintypes.LONG),
                    ("biHeight", wintypes.LONG), ("biPlanes", wintypes.WORD),
                    ("biBitCount", wintypes.WORD), ("biCompression", wintypes.DWORD),
                    ("biSizeImage", wintypes.DWORD), ("biXPelsPerMeter", wintypes.LONG),
                    ("biYPelsPerMeter", wintypes.LONG), ("biClrUsed", wintypes.DWORD),
                    ("biClrImportant", wintypes.DWORD)]

    _user32.GetDC.argtypes = [wintypes.HWND]
    _user32.GetDC.restype = wintypes.HDC
    _user32.ReleaseDC.argtypes = [wintypes.HWND, wintypes.HDC]
    _user32.UpdateLayeredWindow.argtypes = [
        wintypes.HWND, wintypes.HDC, ctypes.POINTER(wintypes.POINT),
        ctypes.POINTER(wintypes.SIZE), wintypes.HDC, ctypes.POINTER(wintypes.POINT),
        wintypes.COLORREF, ctypes.POINTER(BLENDFUNCTION), wintypes.DWORD]
    _user32.ShowWindow.argtypes = [wintypes.HWND, ctypes.c_int]
    _user32.SetWindowPos.argtypes = [wintypes.HWND, wintypes.HWND, ctypes.c_int, ctypes.c_int,
                                     ctypes.c_int, ctypes.c_int, wintypes.UINT]
    _gdi32.CreateCompatibleDC.argtypes = [wintypes.HDC]
    _gdi32.CreateCompatibleDC.restype = wintypes.HDC
    _gdi32.CreateDIBSection.argtypes = [wintypes.HDC, ctypes.POINTER(BITMAPINFOHEADER),
                                        wintypes.UINT, ctypes.POINTER(ctypes.c_void_p),
                                        wintypes.HANDLE, wintypes.DWORD]
    _gdi32.CreateDIBSection.restype = wintypes.HBITMAP
    _gdi32.SelectObject.argtypes = [wintypes.HDC, wintypes.HGDIOBJ]
    _gdi32.SelectObject.restype = wintypes.HGDIOBJ
    _gdi32.DeleteObject.argtypes = [wintypes.HGDIOBJ]
    _gdi32.DeleteDC.argtypes = [wintypes.HDC]

GWL_EXSTYLE = -20
WS_EX_LAYERED, WS_EX_TRANSPARENT = 0x00080000, 0x00000020
WS_EX_NOACTIVATE, WS_EX_TOOLWINDOW = 0x08000000, 0x00000080


def toplevel_hwnd(win: tk.Toplevel):
    return _user32.GetParent(win.winfo_id()) or win.winfo_id()


def make_layered(hwnd) -> None:
    style = _user32.GetWindowLongW(hwnd, GWL_EXSTYLE)
    _user32.SetWindowLongW(hwnd, GWL_EXSTYLE, style | WS_EX_LAYERED | WS_EX_TRANSPARENT
                           | WS_EX_NOACTIVATE | WS_EX_TOOLWINDOW)


def update_layered(hwnd, img: Image.Image, x: int, y: int) -> None:
    """Mostra uma imagem RGBA na janela, com transparência por pixel."""
    w, h = img.size
    r, g, b, a = img.split()
    data = Image.merge("RGBA", (ImageChops.multiply(b, a), ImageChops.multiply(g, a),
                                ImageChops.multiply(r, a), a)).tobytes()  # BGRA pré-multiplicado
    screen = _user32.GetDC(None)
    mem = _gdi32.CreateCompatibleDC(screen)
    bmi = BITMAPINFOHEADER(ctypes.sizeof(BITMAPINFOHEADER), w, -h, 1, 32, 0, 0, 0, 0, 0, 0)
    bits = ctypes.c_void_p()
    hbmp = _gdi32.CreateDIBSection(mem, ctypes.byref(bmi), 0, ctypes.byref(bits), None, 0)
    try:
        ctypes.memmove(bits, data, len(data))
        old = _gdi32.SelectObject(mem, hbmp)
        blend = BLENDFUNCTION(0, 0, 255, 1)  # AC_SRC_OVER, AC_SRC_ALPHA
        ok = _user32.UpdateLayeredWindow(
            hwnd, screen, ctypes.byref(wintypes.POINT(x, y)), ctypes.byref(wintypes.SIZE(w, h)),
            mem, ctypes.byref(wintypes.POINT(0, 0)), 0, ctypes.byref(blend), 2)  # ULW_ALPHA
        _gdi32.SelectObject(mem, old)
        if not ok:
            raise ctypes.WinError(ctypes.get_last_error())
    finally:
        _gdi32.DeleteObject(hbmp)
        _gdi32.DeleteDC(mem)
        _user32.ReleaseDC(None, screen)


def cursor_pos(root: tk.Misc) -> tuple[int, int]:
    if IS_WIN:
        pt = wintypes.POINT()
        if _user32.GetCursorPos(ctypes.byref(pt)):
            return pt.x, pt.y
    return root.winfo_pointerxy()


def virtual_screen(root: tk.Misc) -> tuple[int, int, int, int]:
    """(x, y, largura, altura) da área que cobre todos os monitores."""
    if IS_WIN:
        g = _user32.GetSystemMetrics
        return g(76), g(77), g(78), g(79)
    return 0, 0, root.winfo_screenwidth(), root.winfo_screenheight()


def make_noactivate(win: tk.Toplevel) -> None:
    """Faz a janela não roubar o foco (o jogo/app atual continua ativo)."""
    if not IS_WIN:
        return
    try:
        hwnd = _user32.GetParent(win.winfo_id()) or win.winfo_id()
        GWL_EXSTYLE, WS_EX_NOACTIVATE, WS_EX_TOOLWINDOW = -20, 0x08000000, 0x00000080
        style = _user32.GetWindowLongW(hwnd, GWL_EXSTYLE)
        _user32.SetWindowLongW(hwnd, GWL_EXSTYLE, style | WS_EX_NOACTIVATE | WS_EX_TOOLWINDOW)
    except Exception:
        log.exception("make_noactivate falhou")


def copy_image_to_clipboard(img: Image.Image) -> bool:
    if not IS_WIN:
        return False
    buf = io.BytesIO()
    img.convert("RGB").save(buf, "BMP")
    data = buf.getvalue()[14:]  # CF_DIB = BMP sem o cabeçalho de arquivo
    GMEM_MOVEABLE, CF_DIB = 0x0002, 8
    h = _kernel32.GlobalAlloc(GMEM_MOVEABLE, len(data))
    if not h:
        return False
    p = _kernel32.GlobalLock(h)
    ctypes.memmove(p, data, len(data))
    _kernel32.GlobalUnlock(h)
    for _ in range(20):
        if _user32.OpenClipboard(None):
            break
        time.sleep(0.05)
    else:
        _kernel32.GlobalFree(h)
        return False
    try:
        _user32.EmptyClipboard()
        if not _user32.SetClipboardData(CF_DIB, h):
            _kernel32.GlobalFree(h)
            return False
        return True  # a partir daqui o Windows é dono da memória
    finally:
        _user32.CloseClipboard()


# --------------------------------------------------------------------------
# Inicializar com o Windows
# --------------------------------------------------------------------------
RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"


def _startup_command() -> str:
    exe = Path(sys.executable)
    pythonw = exe.with_name("pythonw.exe")
    return f'"{pythonw if pythonw.exists() else exe}" "{Path(__file__).resolve()}"'


def startup_enabled() -> bool:
    if not IS_WIN:
        return False
    import winreg

    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as k:
            winreg.QueryValueEx(k, APP_NAME)
            return True
    except OSError:
        return False


def set_startup(enable: bool) -> None:
    import winreg

    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_SET_VALUE) as k:
        if enable:
            winreg.SetValueEx(k, APP_NAME, 0, winreg.REG_SZ, _startup_command())
        else:
            try:
                winreg.DeleteValue(k, APP_NAME)
            except FileNotFoundError:
                pass


# --------------------------------------------------------------------------
# Ações
# --------------------------------------------------------------------------
_kb = keyboard.Controller()
KEY_ALIASES = {
    "win": "cmd", "windows": "cmd", "super": "cmd",
    "control": "ctrl", "escape": "esc", "return": "enter", "del": "delete",
    "pgup": "page_up", "pgdn": "page_down", "printscreen": "print_screen",
}


def parse_key(name: str):
    n = name.strip().lower()
    n = KEY_ALIASES.get(n, n)
    if hasattr(keyboard.Key, n):
        return getattr(keyboard.Key, n)
    if len(n) == 1:
        return keyboard.KeyCode.from_char(n)
    raise ValueError(f"tecla desconhecida: {name!r}")


def send_keys(combo: str) -> None:
    keys = [parse_key(p) for p in combo.split("+") if p.strip()]
    for k in keys:
        _kb.press(k)
    for k in reversed(keys):
        _kb.release(k)


def open_target(target: str, args: list[str] | None = None) -> None:
    target = os.path.expandvars(os.path.expanduser(target))
    if args:
        subprocess.Popen([target, *map(str, args)])
    elif IS_WIN:
        os.startfile(target)  # programas, pastas, URLs e protocolos (steam://, discord://)
    elif sys.platform == "darwin":
        subprocess.Popen(["open", target])
    else:
        subprocess.Popen(["xdg-open", target])


# --------------------------------------------------------------------------
# Geometria da roda
# --------------------------------------------------------------------------
def slice_at(dx: float, dy: float, n: int, dead_zone: float) -> int | None:
    """Índice da fatia na direção (dx, dy). Item 0 fica no topo, sentido horário."""
    if math.hypot(dx, dy) < dead_zone:
        return None
    ang = math.atan2(dx, -dy) % (2 * math.pi)
    step = 2 * math.pi / n
    return int(((ang + step / 2) % (2 * math.pi)) // step) % n


# --------------------------------------------------------------------------
# A roda
# --------------------------------------------------------------------------
class Wheel:
    FRAME_MS = 16
    OPEN_S = 0.18  # duração da animação de abertura

    def __init__(self, app: "App"):
        self.app = app
        self.win = tk.Toplevel(app.root)
        self.win.overrideredirect(True)
        self.win.attributes("-topmost", True)
        self.visible = False
        self.selected: int | None = None
        self.center = (0, 0)
        self.origin = (0, 0)
        self.t0 = 0.0
        self._job = None
        self._last = None
        self.hwnd = None
        if IS_WIN:
            # janela "layered": a imagem neon é mostrada com transparência por pixel
            self.win.geometry("1x1+-32000+-32000")
            self.win.update()
            self.hwnd = toplevel_hwnd(self.win)
            make_layered(self.hwnd)
            _user32.ShowWindow(self.hwnd, 0)  # SW_HIDE
        else:
            self.win.withdraw()
            self.canvas = tk.Canvas(self.win, highlightthickness=0, bd=0,
                                    bg=app.cfg["background"])
            self.canvas.pack()
            self._photo = None
            self._img_id = None
        self.rebuild()

    def rebuild(self) -> None:
        cfg = self.app.cfg
        self.items = cfg["items"]
        self.renderer = neon.NeonWheel(cfg)
        self.size = self.renderer.size
        self.r = int(cfg["inner_radius"])
        self.dead = float(cfg.get("dead_zone", self.r * 0.7))
        self.animate = bool(cfg.get("animations", True))
        if not IS_WIN:
            self.canvas.configure(width=self.size, height=self.size, bg=cfg["background"])
        # pré-desenha todos os estados em segundo plano para a roda abrir sem atraso
        r = self.renderer
        states = [None, *range(len(self.items))]
        threading.Thread(target=lambda: [r.static(s) for s in states], daemon=True).start()

    # --- exibir / esconder ---
    def show_at(self, x: int, y: int) -> None:
        vx, vy, vw, vh = virtual_screen(self.app.root)
        half = self.size // 2
        x = max(vx + half, min(x, vx + vw - half))
        y = max(vy + half, min(y, vy + vh - half))
        self.center = (x, y)
        self.origin = (x - half, y - half)
        self.selected = None
        self._last = None
        self.t0 = time.monotonic()
        self.visible = True
        self._render()
        if IS_WIN:
            _user32.ShowWindow(self.hwnd, 4)  # SW_SHOWNOACTIVATE
            # HWND_TOPMOST, SWP_NOMOVE | SWP_NOSIZE | SWP_NOACTIVATE
            _user32.SetWindowPos(self.hwnd, wintypes.HWND(-1), 0, 0, 0, 0, 0x13)
        else:
            self.win.geometry(f"{self.size}x{self.size}+{self.origin[0]}+{self.origin[1]}")
            self.win.deiconify()
            self.win.lift()
        self._job = self.win.after(self.FRAME_MS, self._tick)

    def hide(self) -> None:
        self.visible = False
        if self._job:
            self.win.after_cancel(self._job)
            self._job = None
        if IS_WIN:
            _user32.ShowWindow(self.hwnd, 0)
        else:
            self.win.withdraw()

    def update_selection(self) -> int | None:
        px, py = cursor_pos(self.app.root)
        self.selected = slice_at(px - self.center[0], py - self.center[1],
                                 len(self.items), self.dead)
        return self.selected

    def _render(self) -> None:
        t = time.monotonic() - self.t0
        opening = min(1.0, t / self.OPEN_S)
        state = (self.selected, opening >= 1.0)
        if not self.animate and state == self._last:
            return  # nada mudou
        self._last = state
        img = self.renderer.frame(self.selected, t, opening, self.animate)
        if IS_WIN:
            update_layered(self.hwnd, img, *self.origin)
        else:
            bg = Image.new("RGBA", img.size, self.app.cfg["background"])
            bg.alpha_composite(img)
            self._photo = ImageTk.PhotoImage(bg)
            if self._img_id is None:
                self._img_id = self.canvas.create_image(0, 0, anchor="nw", image=self._photo)
            else:
                self.canvas.itemconfigure(self._img_id, image=self._photo)

    def _tick(self) -> None:
        if not self.visible:
            return
        self.update_selection()
        try:
            self._render()
        except Exception:
            log.exception("falha ao desenhar a roda")
        self._job = self.win.after(self.FRAME_MS, self._tick)


# --------------------------------------------------------------------------
# Recorte de tela
# --------------------------------------------------------------------------
class Snipper:
    def __init__(self, app: "App", on_done):
        self.app = app
        self.on_done = on_done
        cfg = app.cfg
        self.neon, self.accent = cfg["neon"], cfg["accent"]
        root = app.root
        vx, vy, vw, vh = virtual_screen(root)
        self.vw, self.vh = vw, vh
        self.shot = ImageGrab.grab(all_screens=True) if IS_WIN else ImageGrab.grab()
        self.sx, self.sy = self.shot.width / vw, self.shot.height / vh
        disp = self.shot if self.shot.size == (vw, vh) else self.shot.resize((vw, vh))
        self.disp = disp.convert("RGB")
        dim = ImageEnhance.Brightness(self.disp).enhance(0.4)
        dim = Image.blend(dim, Image.new("RGB", dim.size, cfg["background"]), 0.3)
        self.bg = ImageTk.PhotoImage(dim)

        self.win = tk.Toplevel(root)
        self.win.overrideredirect(True)
        self.win.attributes("-topmost", True)
        self.win.geometry(f"{vw}x{vh}+{vx}+{vy}")
        self.cv = tk.Canvas(self.win, width=vw, height=vh, highlightthickness=0,
                            bd=0, cursor="crosshair")
        self.cv.pack()
        self.cv.create_image(0, 0, anchor="nw", image=self.bg)

        cx, cy = cursor_pos(root)
        hx, hy = cx - vx, max(40, cy - vy - 70)
        self.cv.create_rectangle(hx - 230, hy - 18, hx + 230, hy + 18, fill="#07070f",
                                 outline=self.neon, tags="hint")
        self.cv.create_text(hx, hy, text="[ ARRASTE PARA RECORTAR ]   ESC // CANCELA",
                            fill=self.neon, font=("Consolas", 12, "bold"), tags="hint")

        self.start = None
        self.cur = None
        self.crop_img = None
        self._pending = False
        self.cv.bind("<Motion>", self._hover)
        self.cv.bind("<ButtonPress-1>", self._press)
        self.cv.bind("<B1-Motion>", self._motion)
        self.cv.bind("<ButtonRelease-1>", self._release)
        self.cv.bind("<ButtonPress-3>", lambda e: self._finish(None))
        self.win.bind("<Escape>", lambda e: self._finish(None))
        self.win.after(30, self._focus)

    def _focus(self):
        self.win.lift()
        self.win.focus_force()
        self.cv.focus_set()

    def _crosshair(self, x, y):
        self.cv.delete("cross")
        for coords in ((0, y, self.vw, y), (x, 0, x, self.vh)):
            self.cv.create_line(*coords, fill=self.neon, dash=(6, 6), tags="cross")
        self.cv.create_text(x + 12, y + 14, anchor="nw", text=f"X{x:04d} Y{y:04d}",
                            fill=self.neon, font=("Consolas", 8), tags="cross")

    def _hover(self, e):
        if not self.start:
            self._crosshair(e.x, e.y)

    def _rect(self):
        (x0, y0), (x1, y1) = self.start, self.cur
        return min(x0, x1), min(y0, y1), max(x0, x1), max(y0, y1)

    def _press(self, e):
        self.start = self.cur = (e.x, e.y)
        self.cv.delete("hint")

    def _motion(self, e):
        if not self.start:
            return
        self.cur = (e.x, e.y)
        if not self._pending:  # limita o redesenho a ~1 por frame
            self._pending = True
            self.win.after(8, self._redraw)

    def _redraw(self):
        self._pending = False
        self.cv.delete("sel")
        self._crosshair(*self.cur)
        x0, y0, x1, y1 = self._rect()
        if x1 - x0 < 1 or y1 - y0 < 1:
            return
        cv = self.cv
        self.crop_img = ImageTk.PhotoImage(self.disp.crop((x0, y0, x1, y1)))
        cv.create_image(x0, y0, anchor="nw", image=self.crop_img, tags="sel")
        cv.create_rectangle(x0, y0, x1, y1, outline=self.neon, width=1, tags="sel")
        L = max(4, min(22, (x1 - x0) // 3, (y1 - y0) // 3))
        for x, y, sx, sy in ((x0, y0, 1, 1), (x1, y0, -1, 1), (x0, y1, 1, -1), (x1, y1, -1, -1)):
            cv.create_line(x, y + sy * L, x, y, x + sx * L, y, fill=self.accent, width=3,
                           tags="sel")
        w, h = round((x1 - x0) * self.sx), round((y1 - y0) * self.sy)
        label = f" {w} × {h} "
        ly = y0 - 24 if y0 > 30 else y1 + 6
        tid = cv.create_text(x0, ly, anchor="nw", text=label, fill="#07070f",
                             font=("Consolas", 10, "bold"), tags="sel")
        bx0, by0, bx1, by1 = cv.bbox(tid)
        cv.tag_lower(cv.create_rectangle(bx0 - 2, by0 - 2, bx1 + 2, by1 + 2, fill=self.accent,
                                         outline="", tags="sel"), tid)

    def _release(self, e):
        if not self.start:
            return
        self.cur = (e.x, e.y)
        x0, y0, x1, y1 = self._rect()
        if x1 - x0 < 4 or y1 - y0 < 4:
            self._finish(None)
            return
        box = (round(x0 * self.sx), round(y0 * self.sy), round(x1 * self.sx), round(y1 * self.sy))
        self._finish(self.shot.crop(box))

    def _finish(self, img):
        self.win.destroy()
        self.on_done(img)


# --------------------------------------------------------------------------
# Aplicativo
# --------------------------------------------------------------------------
class App:
    def __init__(self):
        self.root = tk.Tk()
        self.root.withdraw()
        self.root.title(APP_NAME)
        self.events: queue.Queue = queue.Queue()
        self.cfg = load_config()
        self.trigger = TRIGGERS[self.cfg["trigger"]]
        self.wheel = Wheel(self)
        self.wheel_open = False  # lido pela thread do hook
        self.snipping = False
        self.ignore_up = False
        self._swallow: set[int] = set()
        self.tray = None
        self._start_listeners()
        self._start_tray()
        self.root.after(10, self._poll)

    # --- entrada global ---
    def _start_listeners(self):
        if IS_WIN:
            self.mouse_listener = mouse.Listener(win32_event_filter=self._win32_filter)
        else:
            self.mouse_listener = mouse.Listener(on_click=self._on_click_generic)
        self.mouse_listener.start()
        self.kb_listener = keyboard.Listener(on_press=self._on_key)
        self.kb_listener.start()

    def _win32_filter(self, msg, data):
        kind, num = self.trigger
        is_trigger = False
        if kind == "x" and msg in (WM_XBUTTONDOWN, WM_XBUTTONUP):
            is_trigger = ((data.mouseData >> 16) & 0xFFFF) == num
        elif kind == "m" and msg in (WM_MBUTTONDOWN, WM_MBUTTONUP):
            is_trigger = True
        if is_trigger:
            down = msg in (WM_XBUTTONDOWN, WM_MBUTTONDOWN)
            self.events.put(("trigger_down" if down else "trigger_up", None))
            self.mouse_listener.suppress_event()  # impede o "Voltar" do navegador
        if msg in self._swallow:
            self._swallow.discard(msg)
            self.mouse_listener.suppress_event()
        if self.wheel_open and msg in (WM_LBUTTONDOWN, WM_RBUTTONDOWN):
            self.events.put(("click", "left" if msg == WM_LBUTTONDOWN else "right"))
            self._swallow.add(msg + 1)  # engole também o "soltar" correspondente
            self.mouse_listener.suppress_event()

    def _on_click_generic(self, x, y, button, pressed):
        names = {"mouse4": ("x1", "button8"), "mouse5": ("x2", "button9"), "middle": ("middle",)}
        targets = [getattr(mouse.Button, n) for n in names[self.cfg["trigger"]]
                   if hasattr(mouse.Button, n)]
        if button in targets:
            self.events.put(("trigger_down" if pressed else "trigger_up", None))
        elif self.wheel_open and pressed and button in (mouse.Button.left, mouse.Button.right):
            self.events.put(("click", "left" if button == mouse.Button.left else "right"))

    def _on_key(self, key):
        if key == keyboard.Key.esc and self.wheel_open:
            self.events.put(("esc", None))

    # --- bandeja do sistema ---
    def _start_tray(self):
        try:
            import pystray
        except Exception:
            log.info("pystray indisponível; sem ícone na bandeja", exc_info=True)
            return
        put = lambda ev: (lambda icon, item: self.events.put((ev, None)))  # noqa: E731
        items = [
            pystray.MenuItem("Abrir roda", put("open_center"), default=True),
            pystray.MenuItem("Editar atalhos (config.json)", put("edit_config")),
            pystray.MenuItem("Recarregar atalhos", put("reload")),
        ]
        if IS_WIN:
            items.append(pystray.MenuItem("Iniciar com o Windows", put("toggle_startup"),
                                          checked=lambda item: startup_enabled()))
        items += [pystray.Menu.SEPARATOR, pystray.MenuItem("Sair", put("quit"))]
        self.tray = pystray.Icon(APP_NAME, neon.tray_image(self.cfg["neon"], self.cfg["accent"]),
                                 f"{APP_NAME} — roda de atalhos", pystray.Menu(*items))
        self.tray.run_detached()

    # --- laço de eventos ---
    def _poll(self):
        try:
            while True:
                ev, arg = self.events.get_nowait()
                try:
                    self._handle(ev, arg)
                except Exception as e:
                    log.exception("erro tratando %s", ev)
                    self.toast(f"Erro: {e}", error=True)
        except queue.Empty:
            pass
        self.root.after(10, self._poll)

    def _open_wheel(self, x, y):
        self.wheel.show_at(x, y)
        self.wheel_open = True

    def _close_wheel(self):
        self.wheel_open = False
        self.wheel.hide()

    def _handle(self, ev, arg):
        if ev == "trigger_down":
            if self.snipping:
                return
            if self.wheel.visible:  # apertou de novo com a roda aberta: fecha
                self._close_wheel()
                self.ignore_up = True
                return
            self._open_wheel(*cursor_pos(self.root))
        elif ev == "trigger_up":
            if self.ignore_up:
                self.ignore_up = False
                return
            if self.wheel.visible:
                sel = self.wheel.update_selection()
                if sel is not None:
                    self._choose(sel)
                # sem seleção (clique rápido): a roda fica aberta para clicar
        elif ev == "click":
            if not self.wheel.visible:
                return
            sel = self.wheel.update_selection()
            if arg == "left" and sel is not None:
                self._choose(sel)
            else:
                self._close_wheel()
        elif ev == "esc":
            self._close_wheel()
        elif ev == "open_center":
            self._open_wheel(self.root.winfo_screenwidth() // 2, self.root.winfo_screenheight() // 2)
        elif ev == "edit_config":
            open_target(str(CONFIG_PATH))
        elif ev == "reload":
            self.reload()
        elif ev == "toggle_startup":
            set_startup(not startup_enabled())
            self.toast("Mira vai iniciar com o Windows" if startup_enabled()
                       else "Mira não inicia mais com o Windows")
            if self.tray:
                self.tray.update_menu()
        elif ev == "quit":
            self.quit()

    def reload(self):
        try:
            self.cfg = load_config()
        except Exception as e:
            self.toast(f"config.json inválido: {e}", error=True, ms=5000)
            return
        self.trigger = TRIGGERS[self.cfg["trigger"]]
        self.wheel.rebuild()
        self.toast(f"Atalhos recarregados ({len(self.cfg['items'])} itens)")

    def _choose(self, index: int):
        item = self.cfg["items"][index]
        self._close_wheel()
        # pequena pausa para a roda sumir antes da ação (importante p/ prints)
        self.root.after(120, lambda: self.run_action(item))

    def run_action(self, item: dict):
        kind = item.get("type", "open")
        log.info("ação %s (%s)", item.get("name"), kind)
        try:
            if kind == "open":
                open_target(item["target"], item.get("args"))
            elif kind == "command":
                subprocess.Popen(item["command"], shell=True)
            elif kind == "keys":
                send_keys(item["keys"])
            elif kind == "snip":
                self.snipping = True
                Snipper(self, self._snip_done)
            elif kind == "screenshot":
                img = ImageGrab.grab(all_screens=True) if IS_WIN else ImageGrab.grab()
                self._deliver(img)
            else:
                raise ValueError(f"tipo desconhecido: {kind!r}")
        except KeyError as e:
            self.toast(f"'{item.get('name')}': falta o campo {e} no config.json", error=True)
        except Exception as e:
            log.exception("falha na ação")
            self.toast(f"'{item.get('name')}' falhou: {e}", error=True, ms=4000)

    def _snip_done(self, img):
        self.snipping = False
        if img is not None:
            self._deliver(img)

    def _deliver(self, img: Image.Image):
        folder = Path(os.path.expandvars(os.path.expanduser(self.cfg["screenshot_folder"])))
        folder.mkdir(parents=True, exist_ok=True)
        path = folder / f"Mira_{datetime.now():%Y-%m-%d_%H-%M-%S}.png"
        img.save(path)
        copied = copy_image_to_clipboard(img)
        msg = f"Imagem {'copiada e ' if copied else ''}salva em\n{path}"
        self.toast(msg, on_click=lambda: open_target(str(path)))

    # --- avisos ---
    def toast(self, text: str, error: bool = False, ms: int = 2600, on_click=None):
        line = self.cfg["accent"] if error else self.cfg["neon"]
        bg = "#07070f"
        w = tk.Toplevel(self.root)
        w.overrideredirect(True)
        w.attributes("-topmost", True)
        w.attributes("-alpha", 0.94)
        border = tk.Frame(w, bg=line, padx=1, pady=1)
        border.pack()
        body = tk.Frame(border, bg=bg)
        body.pack()
        tk.Frame(body, bg=line, width=4).pack(side="left", fill="y")
        box = tk.Frame(body, bg=bg, padx=14, pady=8)
        box.pack(side="left")
        tk.Label(box, text=("MIRA.SYS // ERRO" if error else "MIRA.SYS // OK"), bg=bg, fg=line,
                 font=("Consolas", 8, "bold"), anchor="w").pack(fill="x")
        lbl = tk.Label(box, text=text, bg=bg, fg=self.cfg["text_color"], font=("Consolas", 10),
                       justify="left", anchor="w", wraplength=420)
        lbl.pack(fill="x")
        if on_click:
            for wid in (box, lbl):
                wid.configure(cursor="hand2")
                wid.bind("<Button-1>", lambda e: (on_click(), w.destroy()))
        w.update_idletasks()
        sw, sh = self.root.winfo_screenwidth(), self.root.winfo_screenheight()
        w.geometry(f"+{sw - w.winfo_width() - 24}+{sh - w.winfo_height() - 64}")
        make_noactivate(w)
        w.after(ms, w.destroy)

    def quit(self):
        try:
            self.mouse_listener.stop()
            self.kb_listener.stop()
            if self.tray:
                self.tray.stop()
        finally:
            self.root.destroy()

    def run(self):
        log.info("Mira iniciado (gatilho: %s)", self.cfg["trigger"])
        self.toast(f"Mira ativo — segure o {self.cfg['trigger'].replace('mouse', 'Mouse ')} "
                   "para abrir a roda")
        self.root.mainloop()


def main():
    if IS_WIN:
        mutex = _kernel32.CreateMutexW(None, False, "Local\\MiraRodaDeAtalhos")
        if ctypes.get_last_error() == 183:  # ERROR_ALREADY_EXISTS
            r = tk.Tk()
            r.withdraw()
            messagebox.showinfo(APP_NAME, "O Mira já está rodando (veja o ícone perto do relógio).")
            return
        _ = mutex
    try:
        app = App()
    except Exception as e:
        log.exception("falha ao iniciar")
        r = tk.Tk()
        r.withdraw()
        messagebox.showerror(APP_NAME, f"Não foi possível iniciar o Mira:\n\n{e}")
        return
    app.run()


if __name__ == "__main__":
    main()
