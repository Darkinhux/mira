"""
Recorte de tela no estilo Lightshot.

1. Arraste para selecionar uma área.
2. Ajuste a seleção pelas alças (ou arraste por dentro para mover).
3. Desenhe com as ferramentas da barra lateral (lápis, linha, seta,
   retângulo, marca-texto, texto). A roda do mouse muda a espessura.
4. Ctrl+C copia · Ctrl+S salva como · Enter/duplo clique copia e salva
   na pasta de prints · Ctrl+Z desfaz · Esc fecha.
"""
from __future__ import annotations

import math
import tkinter as tk

from PIL import Image, ImageColor, ImageDraw, ImageEnhance, ImageTk

import neon

PALETTE = ["#ff2a6d", "#00f0ff", "#f9f002", "#39ff14", "#ff3b30", "#2d7dff", "#ffffff", "#000000"]
TOOLS = [  # id, símbolo, nome, tecla de atalho
    ("pen", "✎", "Lápis", "P"),
    ("line", "╱", "Linha", "L"),
    ("arrow", "➚", "Seta", "A"),
    ("rect", "▢", "Retângulo", "R"),
    ("marker", "▌", "Marca-texto", "M"),
    ("blur", "▦", "Pixelar / esconder", "B"),
    ("text", "T", "Texto", "T"),
]
WIDTHS = [2, 4, 6, 10, 16]
BTN = 34
HANDLE = 5
UI_FONT = ("Segoe UI Symbol", 14)
MONO = ("Consolas", 9, "bold")
CURSORS = {
    "nw": "top_left_corner", "ne": "top_right_corner", "sw": "bottom_left_corner",
    "se": "bottom_right_corner", "n": "sb_v_double_arrow", "s": "sb_v_double_arrow",
    "e": "sb_h_double_arrow", "w": "sb_h_double_arrow",
}


# --------------------------------------------------------------------------
# desenho das anotações (o mesmo código na prévia e na imagem final)
# --------------------------------------------------------------------------
def _rgb(color: str):
    return ImageColor.getrgb(color)[:3]


def _contrast(rgb):
    return (0, 0, 0) if sum(rgb) > 380 else (255, 255, 255)


def text_size(width: int) -> int:
    return 12 + width * 3


def draw_annotations(layer: Image.Image, annos: list[dict], off, scale: float) -> None:
    """Desenha as anotações numa camada RGBA transparente do tamanho da seleção."""
    def P(p):
        return ((p[0] - off[0]) * scale, (p[1] - off[1]) * scale)

    d = ImageDraw.Draw(layer)
    for a in annos:
        kind = a["kind"]
        col = _rgb(a["color"])
        w = max(1, round(a["width"] * scale))
        pts = [P(p) for p in a["points"]]
        if kind == "pen":
            if len(pts) > 1:
                d.line(pts, fill=col + (255,), width=w, joint="curve")
            for x, y in (pts[0], pts[-1]):  # pontas arredondadas
                d.ellipse((x - w / 2, y - w / 2, x + w / 2, y + w / 2), fill=col + (255,))
        elif kind == "marker":
            mw = w * 4
            mask = Image.new("L", layer.size, 0)
            md = ImageDraw.Draw(mask)
            if len(pts) > 1:
                md.line(pts, fill=255, width=mw, joint="curve")
            for x, y in (pts[0], pts[-1]):
                md.ellipse((x - mw / 2, y - mw / 2, x + mw / 2, y + mw / 2), fill=255)
            tint = Image.new("RGBA", layer.size, col + (0,))
            tint.putalpha(mask.point(lambda v: v * 105 // 255))
            layer.alpha_composite(tint)
            d = ImageDraw.Draw(layer)
        elif kind == "line":
            d.line(pts[:2], fill=col + (255,), width=w)
        elif kind == "arrow":
            (x0, y0), (x1, y1) = pts[0], pts[-1]
            ang = math.atan2(y1 - y0, x1 - x0)
            head = max(12 * scale, w * 4)
            bx, by = x1 - head * 0.8 * math.cos(ang), y1 - head * 0.8 * math.sin(ang)
            d.line([(x0, y0), (bx, by)], fill=col + (255,), width=w)
            left = (x1 - head * math.cos(ang - 0.45), y1 - head * math.sin(ang - 0.45))
            right = (x1 - head * math.cos(ang + 0.45), y1 - head * math.sin(ang + 0.45))
            d.polygon([(x1, y1), left, right], fill=col + (255,))
        elif kind == "rect":
            (x0, y0), (x1, y1) = pts[0], pts[-1]
            d.rectangle((min(x0, x1), min(y0, y1), max(x0, x1), max(y0, y1)),
                        outline=col + (255,), width=w)
        elif kind == "text" and a.get("text"):
            size = max(6, round(a["size"] * scale))
            d.text(pts[0], a["text"], font=neon.font("display", size), fill=col + (255,),
                   anchor="la", stroke_width=max(1, size // 12),
                   stroke_fill=_contrast(col) + (255,))


def pixelate(img: Image.Image, box, block: int) -> None:
    """Pixela uma área da imagem (para esconder nomes, e-mails, chats...)."""
    x0, y0, x1, y1 = box
    x0, x1 = sorted((max(0, round(x0)), min(img.width, round(x1))))
    y0, y1 = sorted((max(0, round(y0)), min(img.height, round(y1))))
    w, h = x1 - x0, y1 - y0
    if w < 2 or h < 2:
        return
    region = img.crop((x0, y0, x1, y1))
    small = region.resize((max(1, w // block), max(1, h // block)), Image.BILINEAR)
    img.paste(small.resize((w, h), Image.NEAREST), (x0, y0))


def blur_block(width: int) -> int:
    return 6 + width * 2


def render(base: Image.Image, annos, off, scale: float, ss: int = 1) -> Image.Image:
    """Recorte + anotações. ss=2 suaviza as bordas na imagem final."""
    out = base.convert("RGBA")
    for a in annos:  # as áreas pixeladas vêm primeiro, por baixo dos desenhos
        if a["kind"] == "blur" and len(a["points"]) > 1:
            (px0, py0), (px1, py1) = a["points"][0], a["points"][-1]
            box = ((px0 - off[0]) * scale, (py0 - off[1]) * scale,
                   (px1 - off[0]) * scale, (py1 - off[1]) * scale)
            pixelate(out, box, max(3, round(blur_block(a["width"]) * scale)))
    annos = [a for a in annos if a["kind"] != "blur"]
    if annos:
        layer = Image.new("RGBA", (out.width * ss, out.height * ss), (0, 0, 0, 0))
        draw_annotations(layer, annos, off, scale * ss)
        if ss > 1:
            layer = layer.resize(out.size, Image.LANCZOS)
        out.alpha_composite(layer)
    return out


# --------------------------------------------------------------------------
# a janela de recorte
# --------------------------------------------------------------------------
class Snipper:
    def __init__(self, root: tk.Misc, cfg: dict, shot: Image.Image, vscreen, cursor, on_done):
        """on_done(imagem | None, ação) — ação: "copy", "save", "quick" ou None."""
        self.on_done = on_done
        self.neon, self.accent, self.bgc = cfg["neon"], cfg["accent"], cfg["background"]
        vx, vy, vw, vh = vscreen
        self.vw, self.vh = vw, vh
        self.shot = shot
        self.sx = shot.width / vw
        disp = shot if shot.size == (vw, vh) else shot.resize((vw, vh))
        self.disp = disp.convert("RGB")
        dim = ImageEnhance.Brightness(self.disp).enhance(0.4)
        dim = Image.blend(dim, Image.new("RGB", dim.size, self.bgc), 0.3)
        self.bg = ImageTk.PhotoImage(dim)

        self.sel = None          # (x0, y0, x1, y1) em coordenadas da tela
        self.mode = None         # "new" | "move" | "resize" | "draw"
        self.drag = None
        self.tool = None
        self.color = self.accent
        self.width = 4
        self.annos: list[dict] = []
        self.current = None      # anotação sendo desenhada
        self.entry = None        # caixa de texto aberta
        self.palette_open = False
        self.buttons: list = []  # (x0, y0, x1, y1, ação, dica)
        self.hover_btn = None
        self._cache_key = None
        self._cache = None
        self._pending = False
        self._photo = None

        self.win = tk.Toplevel(root)
        self.win.overrideredirect(True)
        self.win.attributes("-topmost", True)
        self.win.geometry(f"{vw}x{vh}+{vx}+{vy}")
        self.cv = tk.Canvas(self.win, width=vw, height=vh, highlightthickness=0, bd=0,
                            cursor="crosshair")
        self.cv.pack()
        self.cv.create_image(0, 0, anchor="nw", image=self.bg)

        cx, cy = cursor[0] - vx, cursor[1] - vy
        hy = max(40, cy - 70)
        self.cv.create_rectangle(cx - 250, hy - 18, cx + 250, hy + 18, fill="#07070f",
                                 outline=self.neon, tags="hint")
        self.cv.create_text(cx, hy, text="[ ARRASTE PARA SELECIONAR ]   ESC // CANCELA",
                            fill=self.neon, font=("Consolas", 12, "bold"), tags="hint")

        cv = self.cv
        cv.bind("<Motion>", self._on_motion)
        cv.bind("<ButtonPress-1>", self._on_press)
        cv.bind("<B1-Motion>", self._on_drag)
        cv.bind("<ButtonRelease-1>", self._on_release)
        cv.bind("<Double-Button-1>", self._on_double)
        cv.bind("<ButtonPress-3>", self._on_right)
        cv.bind("<MouseWheel>", lambda e: self._change_width(1 if e.delta > 0 else -1))
        cv.bind("<Button-4>", lambda e: self._change_width(1))
        cv.bind("<Button-5>", lambda e: self._change_width(-1))
        w = self.win
        w.bind("<Escape>", self._on_escape)
        w.bind("<Return>", lambda e: self._key(lambda: self.finish("quick")))
        w.bind("<Control-c>", lambda e: self._key(lambda: self.finish("copy")))
        w.bind("<Control-s>", lambda e: self._key(lambda: self.finish("save")))
        w.bind("<Control-z>", lambda e: self._key(self.undo))
        for tid, _, _, key in TOOLS:
            w.bind(f"<KeyPress-{key.lower()}>", lambda e, t=tid: self._key(lambda: self.set_tool(t)))
        self.win.after(30, self._focus)

    # ---------------- utilidades ----------------
    def _focus(self):
        self.win.lift()
        self.win.focus_force()
        self.cv.focus_set()

    def _key(self, fn):
        if self.entry is None:  # não atrapalhar quem está digitando
            fn()
        return "break"

    def _clamp(self, x, y):
        if not self.sel:
            return x, y
        x0, y0, x1, y1 = self.sel
        return min(max(x, x0), x1), min(max(y, y0), y1)

    def _inside(self, x, y):
        if not self.sel:
            return False
        x0, y0, x1, y1 = self.sel
        return x0 <= x <= x1 and y0 <= y <= y1

    def _handle_at(self, x, y):
        if not self.sel:
            return None
        x0, y0, x1, y1 = self.sel
        mx, my = (x0 + x1) / 2, (y0 + y1) / 2
        spots = {"nw": (x0, y0), "n": (mx, y0), "ne": (x1, y0), "e": (x1, my),
                 "se": (x1, y1), "s": (mx, y1), "sw": (x0, y1), "w": (x0, my)}
        for name, (hx, hy) in spots.items():
            if abs(x - hx) <= HANDLE + 3 and abs(y - hy) <= HANDLE + 3:
                return name
        return None

    def _button_at(self, x, y):
        for b in self.buttons:
            if b[0] <= x <= b[2] and b[1] <= y <= b[3]:
                return b
        return None

    # ---------------- ações ----------------
    def set_tool(self, tool):
        self._commit_text()
        self.tool = None if self.tool == tool else tool
        self.palette_open = False
        self.schedule()

    def set_color(self, color):
        self.color = color
        self.palette_open = False
        if self.entry is not None:
            self.entry.configure(fg=color, insertbackground=color)
        self.schedule()

    def _change_width(self, step):
        i = min(range(len(WIDTHS)), key=lambda k: abs(WIDTHS[k] - self.width))
        self.width = WIDTHS[max(0, min(len(WIDTHS) - 1, i + step))]
        if self.entry is not None:
            self.entry.configure(font=("Segoe UI", -text_size(self.width), "bold"))
        self.schedule()

    def undo(self):
        if self.annos:
            self.annos.pop()
            self.schedule()

    def finish(self, action):
        self._commit_text()
        img = None
        if action and self.sel:
            x0, y0, x1, y1 = self.sel
            s = self.sx
            box = (round(x0 * s), round(y0 * s), round(x1 * s), round(y1 * s))
            img = render(self.shot.crop(box), self.annos, (x0, y0), s, ss=2).convert("RGB")
        self.win.destroy()
        self.on_done(img, action)

    # ---------------- texto ----------------
    def _open_text(self, x, y):
        self._commit_text()
        e = tk.Entry(self.cv, font=("Segoe UI", -text_size(self.width), "bold"), fg=self.color,
                     bg="#07070f", insertbackground=self.color, relief="flat",
                     highlightthickness=1, highlightcolor=self.neon,
                     highlightbackground=self.neon, width=18)
        self.entry = e
        self.entry_pos = (x, y)
        self.entry_item = self.cv.create_window(x, y, window=e, anchor="nw")
        e.bind("<Return>", lambda ev: (self._commit_text(), "break")[1])
        e.bind("<Escape>", lambda ev: (self._close_text(), "break")[1])
        e.focus_set()

    def _commit_text(self):
        if self.entry is None:
            return
        text = self.entry.get().strip()
        if text:
            self.annos.append({"kind": "text", "points": [self.entry_pos], "text": text,
                               "color": self.color, "width": self.width,
                               "size": text_size(self.width)})
        self._close_text()

    def _close_text(self):
        if self.entry is not None:
            self.cv.delete(self.entry_item)
            self.entry.destroy()
            self.entry = None
            self.cv.focus_set()
            self.schedule()

    # ---------------- mouse ----------------
    def _on_motion(self, e):
        if not self.sel:
            self._crosshair(e.x, e.y)
            return
        btn = self._button_at(e.x, e.y)
        if btn is not self.hover_btn:
            self.hover_btn = btn
            self.schedule()
        if btn:
            cursor = "hand2"
        elif (h := self._handle_at(e.x, e.y)):
            cursor = CURSORS[h]
        elif self._inside(e.x, e.y):
            if self.tool is None:
                cursor = "fleur"
            elif self.tool == "text":
                cursor = "xterm"
            elif self.tool in ("pen", "marker"):
                cursor = "pencil"
            else:
                cursor = "crosshair"
        else:
            cursor = "crosshair"
        self.cv.configure(cursor=cursor)

    def _on_press(self, e):
        self.cv.delete("hint")
        btn = self._button_at(e.x, e.y)
        if btn:
            self.mode = None
            btn[4]()
            return
        if self.palette_open:
            self.palette_open = False
            self.schedule()
        self._commit_text()
        handle = self._handle_at(e.x, e.y)
        inside = self._inside(e.x, e.y)
        if handle:
            self.mode, self.drag = "resize", handle
        elif self.tool and inside:
            x, y = self._clamp(e.x, e.y)
            if self.tool == "text":
                self.mode = None
                self._open_text(x, y)
                return
            self.mode = "draw"
            self.current = {"kind": self.tool, "points": [(x, y)], "color": self.color,
                            "width": self.width}
        elif inside:
            self.mode, self.drag = "move", (e.x, e.y, self.sel)
        else:
            self.mode, self.drag = "new", (e.x, e.y)
            self.sel = (e.x, e.y, e.x, e.y)
        self.schedule()

    def _on_drag(self, e):
        if self.mode == "new":
            x0, y0 = self.drag
            self.sel = (min(x0, e.x), min(y0, e.y), max(x0, e.x), max(y0, e.y))
        elif self.mode == "move":
            sx, sy, (x0, y0, x1, y1) = self.drag
            dx = max(-x0, min(e.x - sx, self.vw - x1))
            dy = max(-y0, min(e.y - sy, self.vh - y1))
            self.sel = (x0 + dx, y0 + dy, x1 + dx, y1 + dy)
        elif self.mode == "resize":
            x0, y0, x1, y1 = self.sel
            h = self.drag
            if "w" in h:
                x0 = e.x
            if "e" in h:
                x1 = e.x
            if "n" in h:
                y0 = e.y
            if "s" in h:
                y1 = e.y
            # se cruzar a borda oposta, troca a alça (como no Lightshot)
            if x0 > x1:
                x0, x1 = x1, x0
                h = h.replace("w", "?").replace("e", "w").replace("?", "e")
            if y0 > y1:
                y0, y1 = y1, y0
                h = h.replace("n", "?").replace("s", "n").replace("?", "s")
            self.drag = h
            self.sel = (x0, y0, x1, y1)
        elif self.mode == "draw" and self.current:
            p = self._clamp(e.x, e.y)
            if self.current["kind"] in ("pen", "marker"):
                last = self.current["points"][-1]
                if abs(p[0] - last[0]) + abs(p[1] - last[1]) >= 2:
                    self.current["points"].append(p)
            else:
                self.current["points"][1:] = [p]
        else:
            return
        self.schedule()

    def _on_release(self, e):
        if self.mode == "new":
            x0, y0, x1, y1 = self.sel
            if x1 - x0 < 4 or y1 - y0 < 4:
                self.sel = None
                self.cv.delete("ui", "selimg")
                self._crosshair(e.x, e.y)
        elif self.mode == "draw" and self.current:
            pts = self.current["points"]
            if len(pts) > 1 or self.current["kind"] in ("pen", "marker"):
                self.annos.append(self.current)
            self.current = None
        self.mode = None
        self.schedule()

    def _on_double(self, e):
        if self.sel and self.tool is None and self._inside(e.x, e.y):
            self.finish("quick")

    def _on_right(self, e):
        if self.entry is not None:
            self._close_text()
        elif self.palette_open:
            self.palette_open = False
            self.schedule()
        elif self.tool:
            self.set_tool(self.tool)  # solta a ferramenta
        else:
            self.finish(None)

    def _on_escape(self, e):
        if self.entry is not None:
            self._close_text()
        else:
            self.finish(None)
        return "break"

    # ---------------- desenho da interface ----------------
    def _crosshair(self, x, y):
        self.cv.delete("cross")
        for coords in ((0, y, self.vw, y), (x, 0, x, self.vh)):
            self.cv.create_line(*coords, fill=self.neon, dash=(6, 6), tags="cross")
        self.cv.create_text(x + 12, y + 14, anchor="nw", text=f"X{x:04d} Y{y:04d}",
                            fill=self.neon, font=("Consolas", 8), tags="cross")

    def schedule(self):
        if not self._pending:  # no máximo ~1 redesenho por frame
            self._pending = True
            self.win.after(8, self._redraw)

    def _selection_image(self):
        x0, y0, x1, y1 = (round(v) for v in self.sel)
        key = (x0, y0, x1, y1, len(self.annos), id(self.annos[-1]) if self.annos else 0)
        if key != self._cache_key:  # anotações já prontas ficam guardadas
            self._cache_key = key
            self._cache = render(self.disp.crop((x0, y0, x1, y1)), self.annos, (x0, y0), 1.0)
        img = self._cache
        if self.current and self.current["kind"] == "blur":
            img = render(self.disp.crop((x0, y0, x1, y1)), self.annos + [self.current],
                         (x0, y0), 1.0)
        elif self.current:
            img = img.copy()
            layer = Image.new("RGBA", img.size, (0, 0, 0, 0))
            draw_annotations(layer, [self.current], (x0, y0), 1.0)
            img.alpha_composite(layer)
        return img

    def _redraw(self):
        self._pending = False
        if not self.win.winfo_exists():
            return
        cv = self.cv
        cv.delete("ui", "selimg", "cross")
        self.buttons = []
        if not self.sel:
            return
        x0, y0, x1, y1 = self.sel
        if x1 - x0 < 1 or y1 - y0 < 1:
            return
        self._photo = ImageTk.PhotoImage(self._selection_image())
        cv.create_image(x0, y0, anchor="nw", image=self._photo, tags="selimg")
        if self.entry is not None:
            cv.tag_raise(self.entry_item)

        # moldura, cantoneiras e alças
        cv.create_rectangle(x0, y0, x1, y1, outline=self.neon, width=1, tags="ui")
        L = max(4, min(22, (x1 - x0) // 3, (y1 - y0) // 3))
        for x, y, sx, sy in ((x0, y0, 1, 1), (x1, y0, -1, 1), (x0, y1, 1, -1), (x1, y1, -1, -1)):
            cv.create_line(x, y + sy * L, x, y, x + sx * L, y, fill=self.accent, width=3,
                           tags="ui")
        if self.mode != "draw":
            mx, my = (x0 + x1) / 2, (y0 + y1) / 2
            for hx, hy in ((mx, y0), (x1, my), (mx, y1), (x0, my)):
                cv.create_rectangle(hx - HANDLE, hy - HANDLE, hx + HANDLE, hy + HANDLE,
                                    fill="#07070f", outline=self.accent, tags="ui")

        # tamanho
        w, h = round((x1 - x0) * self.sx), round((y1 - y0) * self.sx)
        ly = y0 - 24 if y0 > 30 else y0 + 6
        tid = cv.create_text(x0 + (0 if y0 > 30 else 6), ly, anchor="nw", text=f" {w} × {h} ",
                             fill="#07070f", font=("Consolas", 10, "bold"), tags="ui")
        bx0, by0, bx1, by1 = cv.bbox(tid)
        cv.tag_lower(cv.create_rectangle(bx0 - 2, by0 - 2, bx1 + 2, by1 + 2, fill=self.accent,
                                         outline="", tags="ui"), tid)
        if self.mode in ("new", "move", "resize"):
            return  # barras só aparecem quando a seleção para
        self._toolbars()

    def _button(self, x, y, glyph, action, tip, active=False, fill=None, font=UI_FONT):
        hover = self.hover_btn is not None and self.hover_btn[:2] == (x, y)
        bg = self.accent if active else ("#1a1a2e" if hover else "#07070f")
        self.cv.create_rectangle(x, y, x + BTN, y + BTN, fill=bg,
                                 outline=self.neon if (hover or active) else "#2a2a44",
                                 tags="ui")
        if fill:  # quadradinho de cor
            self.cv.create_rectangle(x + 9, y + 9, x + BTN - 9, y + BTN - 9, fill=fill,
                                     outline="#ffffff", tags="ui")
        else:
            self.cv.create_text(x + BTN / 2, y + BTN / 2, text=glyph, font=font,
                                fill="#ffffff" if active else self.neon, tags="ui")
        self.buttons.append((x, y, x + BTN, y + BTN, action, tip))

    def _toolbars(self):
        cv = self.cv
        x0, y0, x1, y1 = self.sel
        gap = 8

        # ----- barra vertical: ferramentas -----
        n_tools = len(TOOLS) + 2
        bar_h = n_tools * (BTN + 2)
        if x1 + gap + BTN <= self.vw:
            tx = x1 + gap
        elif x0 - gap - BTN >= 0:
            tx = x0 - gap - BTN
        else:
            tx = x1 - BTN - 4
        ty = max(0, min(y0, self.vh - bar_h))
        side_right = tx > x0
        self._tool_x, self._tool_right = tx, side_right
        y = ty
        for tid, glyph, name, key in TOOLS:
            self._button(tx, y, glyph, lambda t=tid: self.set_tool(t), f"{name} ({key})",
                         active=self.tool == tid)
            y += BTN + 2
        color_y = y
        self._button(tx, y, "", self._toggle_palette, "Cor", fill=self.color)
        y += BTN + 2
        self._button(tx, y, "↶", self.undo, "Desfazer (Ctrl+Z)")

        if self.palette_open:
            px = tx + BTN + 4 if side_right else tx - 4 - len(PALETTE) * (BTN - 6)
            if px + len(PALETTE) * (BTN - 6) > self.vw:
                px = tx - 4 - len(PALETTE) * (BTN - 6)
            cv.create_rectangle(px - 3, color_y - 3, px + len(PALETTE) * (BTN - 6) + 1,
                                color_y + BTN - 3, fill="#07070f", outline=self.neon, tags="ui")
            for i, col in enumerate(PALETTE):
                sx = px + i * (BTN - 6)
                cv.create_rectangle(sx + 3, color_y + 3, sx + BTN - 9, color_y + BTN - 9,
                                    fill=col, outline="#ffffff" if col == self.color else "",
                                    width=2, tags="ui")
                self.buttons.append((sx, color_y, sx + BTN - 6, color_y + BTN - 6,
                                     lambda c=col: self.set_color(c), col))

        # ----- barra horizontal: ações -----
        actions = [
            (f"{self.width}", lambda: self._change_width(1 if self.width < WIDTHS[-1] else -99),
             "Espessura (roda do mouse)", MONO),
            ("⎘", lambda: self.finish("copy"), "Copiar (Ctrl+C)", UI_FONT),
            ("💾", lambda: self.finish("save"), "Salvar como… (Ctrl+S)", ("Segoe UI Emoji", 13)),
            ("⚡", lambda: self.finish("quick"), "Copiar + salvar na pasta (Enter)", UI_FONT),
            ("✕", lambda: self.finish(None), "Fechar (Esc)", UI_FONT),
        ]
        bar_w = len(actions) * (BTN + 2)
        if y1 + gap + BTN <= self.vh:
            ay = y1 + gap
        elif y0 - gap - BTN >= 0:
            ay = y0 - gap - BTN
        else:
            ay = y1 - BTN - 4
        ax = max(0, min(x1 - bar_w, self.vw - bar_w))
        for glyph, fn, tip, font in actions:
            self._button(ax, ay, glyph, fn, tip, font=font)
            ax += BTN + 2

        # dica do botão sob o mouse
        if self.hover_btn is not None and not self.hover_btn[5].startswith("#"):
            bx0, by0, bx1, by1 = self.hover_btn[:4]
            if bx0 == self._tool_x:  # barra vertical: dica ao lado do botão
                if self._tool_right and bx1 + 160 < self.vw or bx0 < 160:
                    tx_, ty_, anchor = bx1 + 8, (by0 + by1) / 2, "w"
                else:
                    tx_, ty_, anchor = bx0 - 8, (by0 + by1) / 2, "e"
            else:
                tx_, ty_, anchor = bx0, by0 - 6, "sw"
                if ty_ < 20:
                    ty_, anchor = by1 + 6, "nw"
            tid = cv.create_text(tx_, ty_, text=self.hover_btn[5].upper(), anchor=anchor,
                                 fill=self.neon, font=MONO, tags="ui")
            b = cv.bbox(tid)
            if b[2] > self.vw:
                cv.move(tid, self.vw - b[2] - 4, 0)
                b = cv.bbox(tid)
            cv.tag_lower(cv.create_rectangle(b[0] - 4, b[1] - 2, b[2] + 4, b[3] + 2,
                                             fill="#07070f", outline=self.neon, tags="ui"), tid)

    def _toggle_palette(self):
        self.palette_open = not self.palette_open
        self.schedule()
