"""
Histórico do Ctrl+C: guarda os últimos textos e imagens copiados.

* No Windows, olha o "número de sequência" da área de transferência a cada
  meio segundo (barato) e só lê o conteúdo quando ele muda.
* Respeita os formatos que gerenciadores de senha usam para pedir que o
  conteúdo NÃO seja guardado (ExcludeClipboardContentFromMonitorProcessing,
  CanIncludeInClipboardHistory = 0, Clipboard Viewer Ignore).
* Por padrão fica só na memória; com "clipboard_save": true os textos são
  salvos em copiados.json para sobreviver a reinícios.
"""
from __future__ import annotations

import ctypes
import hashlib
import json
import logging
import re
import sys
import time
from pathlib import Path

from PIL import Image

IS_WIN = sys.platform == "win32"
log = logging.getLogger("Mira")

MAX_TEXT = 100_000          # caracteres
MAX_IMAGE_PIXELS = 40_000_000
MAX_IMAGES = 8
URL_RE = re.compile(r"^(https?://|www\.)\S+$", re.I)

CF_UNICODETEXT, CF_DIB, GMEM_MOVEABLE = 13, 8, 0x0002

if IS_WIN:
    from ctypes import wintypes

    _u = ctypes.WinDLL("user32", use_last_error=True)
    _k = ctypes.WinDLL("kernel32", use_last_error=True)
    _u.GetClipboardSequenceNumber.restype = wintypes.DWORD
    _u.IsClipboardFormatAvailable.argtypes = [wintypes.UINT]
    _u.RegisterClipboardFormatW.argtypes = [wintypes.LPCWSTR]
    _u.RegisterClipboardFormatW.restype = wintypes.UINT
    _u.OpenClipboard.argtypes = [wintypes.HWND]
    _u.GetClipboardData.argtypes = [wintypes.UINT]
    _u.GetClipboardData.restype = wintypes.HANDLE
    _u.SetClipboardData.argtypes = [wintypes.UINT, wintypes.HANDLE]
    _u.SetClipboardData.restype = wintypes.HANDLE
    _k.GlobalAlloc.argtypes = [wintypes.UINT, ctypes.c_size_t]
    _k.GlobalAlloc.restype = wintypes.HGLOBAL
    _k.GlobalLock.argtypes = [wintypes.HGLOBAL]
    _k.GlobalLock.restype = ctypes.c_void_p
    _k.GlobalUnlock.argtypes = [wintypes.HGLOBAL]
    _k.GlobalFree.argtypes = [wintypes.HGLOBAL]

    _PRIVATE = [_u.RegisterClipboardFormatW(n) for n in
                ("ExcludeClipboardContentFromMonitorProcessing", "Clipboard Viewer Ignore")]
    _CAN_INCLUDE = _u.RegisterClipboardFormatW("CanIncludeInClipboardHistory")


def _open_clipboard() -> bool:
    for _ in range(20):
        if _u.OpenClipboard(None):
            return True
        time.sleep(0.02)
    return False


def sequence() -> int | None:
    return int(_u.GetClipboardSequenceNumber()) if IS_WIN else None


def is_private() -> bool:
    """O app que copiou pediu para não guardar (ex.: gerenciador de senhas)."""
    if not IS_WIN:
        return False
    if any(f and _u.IsClipboardFormatAvailable(f) for f in _PRIVATE):
        return True
    if _CAN_INCLUDE and _u.IsClipboardFormatAvailable(_CAN_INCLUDE) and _open_clipboard():
        try:
            h = _u.GetClipboardData(_CAN_INCLUDE)
            p = _k.GlobalLock(h) if h else None
            if p:
                value = ctypes.c_uint32.from_address(p).value
                _k.GlobalUnlock(h)
                return value == 0
        finally:
            _u.CloseClipboard()
    return False


def read_text() -> str | None:
    if not IS_WIN or not _u.IsClipboardFormatAvailable(CF_UNICODETEXT):
        return None
    if not _open_clipboard():
        return None
    try:
        h = _u.GetClipboardData(CF_UNICODETEXT)
        p = _k.GlobalLock(h) if h else None
        if not p:
            return None
        try:
            return ctypes.wstring_at(p)
        finally:
            _k.GlobalUnlock(h)
    finally:
        _u.CloseClipboard()


def has_image() -> bool:
    return IS_WIN and bool(_u.IsClipboardFormatAvailable(CF_DIB))


def write_text(text: str) -> bool:
    if not IS_WIN:
        return False
    data = (text + "\0").encode("utf-16-le")
    h = _k.GlobalAlloc(GMEM_MOVEABLE, len(data))
    if not h:
        return False
    p = _k.GlobalLock(h)
    ctypes.memmove(p, data, len(data))
    _k.GlobalUnlock(h)
    if not _open_clipboard():
        _k.GlobalFree(h)
        return False
    try:
        _u.EmptyClipboard()
        if not _u.SetClipboardData(CF_UNICODETEXT, h):
            _k.GlobalFree(h)
            return False
        return True
    finally:
        _u.CloseClipboard()


# --------------------------------------------------------------------------
class Entry:
    def __init__(self, kind: str, text: str | None = None, image: Image.Image | None = None,
                 when: float | None = None):
        self.kind = kind
        self.text = text
        self.image = image
        self.when = when or time.time()
        if kind == "text":
            self.key = "t:" + hashlib.sha1(text.encode("utf-8", "replace")).hexdigest()
        else:
            self.key = "i:" + hashlib.sha1(image.tobytes()).hexdigest()

    def label(self) -> str:
        if self.kind == "image":
            return f"Imagem {self.image.width}×{self.image.height}"
        one_line = " ".join(self.text.split())
        return one_line[:60] or "(espaços)"

    def icon(self) -> str:
        if self.kind == "image":
            return "🖼️"
        t = self.text.strip()
        if URL_RE.match(t):
            return "🔗"
        if re.fullmatch(r"[\d\s.,+\-()/]+", t):
            return "🔢"
        return "📝"


class ClipboardHistory:
    def __init__(self, max_items: int = 25, save_path: Path | None = None):
        self.max_items = max(1, int(max_items))
        self.save_path = save_path
        self.entries: list[Entry] = []
        self._seq = None
        self._last_text = None
        self.load()

    # ---------- captura ----------
    def poll(self, tk_root=None) -> bool:
        """Confere se algo novo foi copiado. Devolve True se o histórico mudou."""
        try:
            if IS_WIN:
                seq = sequence()
                if seq == self._seq:
                    return False
                first = self._seq is None
                self._seq = seq
                if first or is_private():  # não guarda o que já estava copiado ao abrir
                    return False
                text = read_text()
                if text is not None:
                    return self.add_text(text)
                if has_image():
                    from PIL import ImageGrab
                    img = ImageGrab.grabclipboard()
                    if isinstance(img, Image.Image):
                        return self.add_image(img)
                return False
            # fora do Windows (testes): só texto, pelo Tk
            if tk_root is None:
                return False
            try:
                text = tk_root.clipboard_get()
            except Exception:
                return False
            if text == self._last_text:
                return False
            first = self._last_text is None
            self._last_text = text
            return False if first else self.add_text(text)
        except Exception:
            log.exception("falha lendo a área de transferência")
            return False

    def _push(self, entry: Entry) -> bool:
        self.entries = [e for e in self.entries if e.key != entry.key]
        self.entries.insert(0, entry)
        images = [e for e in self.entries if e.kind == "image"]
        for old in images[MAX_IMAGES:]:
            self.entries.remove(old)
        del self.entries[self.max_items:]
        self.save()
        return True

    def add_text(self, text: str) -> bool:
        if not text or not text.strip() or len(text) > MAX_TEXT:
            return False
        return self._push(Entry("text", text=text))

    def add_image(self, img: Image.Image) -> bool:
        if img.width * img.height > MAX_IMAGE_PIXELS:
            return False
        return self._push(Entry("image", image=img.convert("RGB")))

    # ---------- uso ----------
    def use(self, entry: Entry) -> None:
        """Coloca no topo (o próprio Ctrl+V vai copiar de novo)."""
        self._push(entry)

    def clear(self) -> None:
        self.entries.clear()
        self.save()

    # ---------- disco (só textos e só se ligado) ----------
    def save(self) -> None:
        if not self.save_path:
            return
        data = [{"text": e.text, "when": e.when} for e in self.entries if e.kind == "text"]
        try:
            self.save_path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        except OSError:
            log.exception("não deu para salvar %s", self.save_path)

    def load(self) -> None:
        if not self.save_path or not self.save_path.exists():
            return
        try:
            data = json.loads(self.save_path.read_text(encoding="utf-8"))
            self.entries = [Entry("text", text=d["text"], when=d.get("when"))
                            for d in data if d.get("text")][: self.max_items]
        except (OSError, ValueError, KeyError, TypeError):
            log.exception("copiados.json inválido; começando vazio")
