"""
Visual neon / ciberpunk da roda — desenhado inteiro com Pillow.

NeonWheel.frame(selecionado, t, abertura) devolve uma imagem RGBA com
transparência por pixel (brilhos suaves), que o mira.py mostra na tela.
"""
from __future__ import annotations

import math
import os
import sys
from functools import lru_cache
from pathlib import Path

from PIL import Image, ImageChops, ImageColor, ImageDraw, ImageFilter, ImageFont

BASE_DIR = (Path(sys.executable).parent if getattr(sys, "frozen", False)
            else Path(__file__).resolve().parent)

FONTS = {
    "display": [
        "C:/Windows/Fonts/bahnschrift.ttf",
        "C:/Windows/Fonts/segoeuib.ttf",
        "/usr/share/fonts/truetype/jetbrains-mono/JetBrainsMono-Bold.ttf",
        "DejaVuSans-Bold.ttf",
    ],
    "mono": [
        "C:/Windows/Fonts/consolab.ttf",
        "/usr/share/fonts/truetype/jetbrains-mono/JetBrainsMono-Bold.ttf",
        "DejaVuSansMono-Bold.ttf",
    ],
    "emoji": [
        "C:/Windows/Fonts/seguiemj.ttf",
        "/usr/share/fonts/truetype/noto/NotoColorEmoji.ttf",
    ],
}
IMAGE_EXTS = {".png", ".ico", ".jpg", ".jpeg", ".gif", ".bmp", ".webp"}
SS = 2  # supersampling para bordas lisas


# --------------------------------------------------------------------------
# utilidades
# --------------------------------------------------------------------------
@lru_cache(maxsize=None)
def font(kind: str, size: int) -> ImageFont.FreeTypeFont:
    for path in FONTS[kind]:
        try:
            f = ImageFont.truetype(path, size)
        except OSError:
            continue
        if path.endswith("bahnschrift.ttf"):
            try:
                f.set_variation_by_name("SemiBold")
            except Exception:
                pass
        return f
    return ImageFont.load_default(size)


def rgb(color: str) -> tuple[int, int, int]:
    return ImageColor.getrgb(color)[:3]


def mix(a, b, t):
    return tuple(round(x + (y - x) * t) for x, y in zip(a, b))


def circle(c, r):
    return (c - r, c - r, c + r, c + r)


def polar(c, r, a):
    """Ângulo em radianos, 0 = topo, sentido horário."""
    return c + r * math.sin(a), c - r * math.cos(a)


def sector(c, rin, rout, a0, a1, gap):
    """Polígono de uma fatia de anel com vão de largura constante (px)."""
    pts = []
    do, di = gap / 2 / rout, gap / 2 / max(rin, 1)
    steps = max(8, int((a1 - a0) * rout / 5))
    for k in range(steps + 1):
        pts.append(polar(c, rout, a0 + do + (a1 - a0 - 2 * do) * k / steps))
    for k in range(steps + 1):
        pts.append(polar(c, rin, a1 - di - (a1 - a0 - 2 * di) * k / steps))
    return pts


def arc_pts(c, r, a0, a1):
    steps = max(4, int(abs(a1 - a0) * r / 4))
    return [polar(c, r, a0 + (a1 - a0) * k / steps) for k in range(steps + 1)]


def scale_alpha(img: Image.Image, f: float) -> Image.Image:
    if f >= 0.999:
        return img
    out = img.copy()
    out.putalpha(img.getchannel("A").point(lambda v: int(v * f)))
    return out


def glow_text(img, xy, text, fnt, color, glow, anchor="mm", radius=4, strength=2):
    """Texto com halo neon."""
    layer = Image.new("RGBA", img.size, (0, 0, 0, 0))
    ImageDraw.Draw(layer).text(xy, text, font=fnt, fill=glow + (255,), anchor=anchor)
    halo = layer.filter(ImageFilter.GaussianBlur(radius))
    for _ in range(strength):
        img.alpha_composite(halo)
    ImageDraw.Draw(img).text(xy, text, font=fnt, fill=color, anchor=anchor)


def fit_font(kind, text, max_w, start, minimum=9):
    size = start
    while size > minimum and font(kind, size).getlength(text) > max_w:
        size -= 1
    return font(kind, size)


def is_branch(item: dict) -> bool:
    return item.get("type") in ("menu", "folder", "games", "clipboard", "default")


def ellipsize(text: str, fnt, max_w: float) -> str:
    if fnt.getlength(text) <= max_w:
        return text
    while text and fnt.getlength(text + "…") > max_w:
        text = text[:-1]
    return text.rstrip() + "…"


@lru_cache(maxsize=512)
def load_icon(spec: str, size: int) -> Image.Image | None:
    if not spec:
        return None
    p = Path(os.path.expandvars(os.path.expanduser(spec)))
    if not p.is_absolute():
        p = BASE_DIR / p
    if p.suffix.lower() in IMAGE_EXTS and p.exists():
        im = Image.open(p).convert("RGBA")
        im.thumbnail((size, size), Image.LANCZOS)
        return im
    text = spec.replace("\ufe0f", "")
    for path in FONTS["emoji"]:
        if not os.path.exists(path):
            continue
        f = None
        for fs in (size * 2, 109):  # NotoColorEmoji só existe em 109
            try:
                f = ImageFont.truetype(path, fs)
                break
            except OSError:
                pass
        if f is None:
            continue
        fs = int(f.size)
        im = Image.new("RGBA", (fs * 3, fs * 3), (0, 0, 0, 0))
        try:
            ImageDraw.Draw(im).text((fs * 1.5, fs * 1.5), text, font=f, anchor="mm",
                                    embedded_color=True)
        except Exception:
            continue
        bbox = im.getbbox()
        if not bbox:
            continue
        im = im.crop(bbox)
        im.thumbnail((size, size), Image.LANCZOS)
        return im
    return None


def ease_out(p):
    return 1 - (1 - p) ** 3


# --------------------------------------------------------------------------
# a roda
# --------------------------------------------------------------------------
_RING_CACHE: dict = {}


class NeonWheel:
    PAD = 54

    def __init__(self, cfg: dict, items: list | None = None, title: str = "MIRA",
                 crumb: str = "MIRA.SYS", depth: int = 0):
        self.items = cfg["items"] if items is None else items
        self.n = len(self.items)
        self.title = title
        self.crumb = crumb
        self.depth = depth
        # camadas com muitos itens ficam um pouco maiores para caber os nomes
        self.R = int(cfg["radius"]) + max(0, self.n - 8) * 8
        self.r = int(cfg["inner_radius"])
        self.icon_size = int(cfg["icon_size"])
        self.neon = rgb(cfg["neon"])
        self.accent = rgb(cfg["accent"])
        self.bg = rgb(cfg["background"])
        self.text = rgb(cfg["text_color"])
        self.size = 2 * (self.R + self.PAD)
        self.icons = [it.get("_icon_img") or load_icon(it.get("icon", ""), self.icon_size)
                      for it in self.items]
        self._static: dict = {}
        self._sel_glow: dict = {}
        key = (self.size, self.R, self.neon, self.accent)
        if key not in _RING_CACHE:
            _RING_CACHE[key] = self._rings()
        self.ring_a, self.ring_b = _RING_CACHE[key]

    # ---------- camadas estáticas (cacheadas por item selecionado) ----------
    def static(self, sel):
        if sel not in self._static:
            self._static[sel] = self._build(sel)
        return self._static[sel]

    def _build(self, sel):
        k = SS
        S = self.size * k
        c = S / 2
        R, r = self.R * k, self.r * k
        rin = r + 12 * k
        step = 2 * math.pi / self.n
        neon, acc, bg = self.neon, self.accent, self.bg

        fills = Image.new("RGBA", (S, S), (0, 0, 0, 0))
        glow = Image.new("RGBA", (S, S), (0, 0, 0, 0))
        lines = Image.new("RGBA", (S, S), (0, 0, 0, 0))
        df, dg, dl = ImageDraw.Draw(fills), ImageDraw.Draw(glow), ImageDraw.Draw(lines)

        # fundo escuro translúcido
        df.ellipse(circle(c, R + 6 * k), fill=bg + (165,))

        for i in range(self.n):
            a0 = i * step - step / 2
            a1 = a0 + step
            on = i == sel
            rout = R + (12 * k if on else 0)
            pts = sector(c, rin, rout, a0, a1, 6 * k)
            if on:
                df.polygon(pts, fill=mix(bg, acc, 0.45) + (235,))
                dg.polygon(pts, fill=acc + (110,))
                dg.line(pts + [pts[0]], fill=acc + (255,), width=7 * k, joint="curve")
                dl.line(pts + [pts[0]], fill=mix(acc, (255, 255, 255), 0.35) + (255,),
                        width=2 * k, joint="curve")
                edge = arc_pts(c, rout - 7 * k, a0 + step * 0.2, a1 - step * 0.2)
                dl.line(edge, fill=(255, 255, 255, 200), width=2 * k, joint="curve")
            else:
                df.polygon(pts, fill=mix(bg, neon, 0.06) + (225,))
                dg.line(pts + [pts[0]], fill=neon + (85,), width=4 * k, joint="curve")
                dl.line(pts + [pts[0]], fill=neon + (150,), width=1 * k, joint="curve")
                edge = arc_pts(c, rout - 7 * k, a0 + step * 0.3, a1 - step * 0.3)
                dl.line(edge, fill=neon + (70,), width=1 * k)

        # setinha nas fatias que abrem uma subcamada
        for i, item in enumerate(self.items):
            if not is_branch(item):
                continue
            on = i == sel
            rout = R + (12 * k if on else 0)
            am = i * step
            tip = polar(c, rout - 4 * k, am)
            bl = polar(c, rout - 12 * k, am - 7 * k / rout)
            br = polar(c, rout - 12 * k, am + 7 * k / rout)
            col = (255, 255, 255, 255) if on else acc + (230,)
            dg.polygon([tip, bl, br], fill=acc + (255,))
            dl.polygon([tip, bl, br], fill=col)

        # núcleo
        df.ellipse(circle(c, r), fill=(4, 4, 10, 245))
        core_col = acc if sel is not None or self.depth else neon
        dg.ellipse(circle(c, r), outline=core_col + (255,), width=6 * k)
        dl.ellipse(circle(c, r), outline=core_col + (255,), width=2 * k)
        for deg in range(0, 360, 15):
            a = math.radians(deg)
            dl.line(arc_pts(c, r - 8 * k, a, a + math.radians(8)), fill=neon + (120,), width=1 * k)

        # anel HUD com marcações
        hud = R + 22 * k
        dl.ellipse(circle(c, hud), outline=neon + (80,), width=1 * k)
        for deg in range(0, 360, 6):
            a = math.radians(deg)
            big = deg % 30 == 0
            p0 = polar(c, hud - (5 if big else 0) * k, a)
            p1 = polar(c, hud + (7 if big else 3) * k, a)
            dl.line([p0, p1], fill=neon + (200 if big else 90,), width=(2 if big else 1) * k)
            if big:
                dg.line([p0, p1], fill=neon + (150,), width=4 * k)

        # cantoneiras estilo HUD
        h, L = R + 40 * k, 24 * k
        for sx in (-1, 1):
            for sy in (-1, 1):
                x, y = c + sx * h, c + sy * h
                pts = [(x, y - sy * L), (x, y), (x - sx * L, y)]
                dg.line(pts, fill=acc + (220,), width=6 * k)
                dl.line(pts, fill=acc + (255,), width=2 * k)

        # scanlines (só dentro do disco)
        scan = Image.new("L", (S, S), 0)
        ds = ImageDraw.Draw(scan)
        for y in range(0, S, 3 * k):
            ds.line([(0, y), (S, y)], fill=40, width=k)
        disc = Image.new("L", (S, S), 0)
        ImageDraw.Draw(disc).ellipse(circle(c, R + 12 * k), fill=255)
        scan = ImageChops.multiply(scan, disc)
        shade = Image.new("RGBA", (S, S), (0, 0, 0, 255))
        shade.putalpha(scan)
        fills.alpha_composite(shade)

        halo = glow.filter(ImageFilter.GaussianBlur(9 * k))
        out = fills
        out.alpha_composite(halo)
        out.alpha_composite(halo)
        out.alpha_composite(lines)
        out = out.resize((self.size, self.size), Image.LANCZOS)

        self._labels(out, sel)
        return out

    def _labels(self, img, sel):
        c = self.size / 2
        step = 2 * math.pi / self.n
        rm = (self.R + self.r + 12) / 2 + 4
        white = (255, 255, 255)
        d = ImageDraw.Draw(img)
        for i, item in enumerate(self.items):
            on = i == sel
            x, y = polar(c, rm + (6 if on else 0), i * step)
            icon = self.icons[i]
            iy = y - 8
            if icon is not None:
                if on:  # halo da cor de destaque atrás do ícone
                    halo = Image.new("RGBA", img.size, (0, 0, 0, 0))
                    tint = Image.new("RGBA", icon.size, self.accent + (255,))
                    tint.putalpha(icon.getchannel("A"))
                    halo.paste(tint, (round(x - icon.width / 2), round(iy - icon.height / 2)))
                    halo = halo.filter(ImageFilter.GaussianBlur(7))
                    img.alpha_composite(halo)
                    img.alpha_composite(halo)
                img.alpha_composite(icon, (round(x - icon.width / 2), round(iy - icon.height / 2)))
            elif item.get("icon"):
                glow_text(img, (x, iy), item["icon"][:2], font("display", 20),
                          white if on else self.neon, self.accent if on else self.neon)
            name = str(item["name"]).upper()
            max_w = min(2 * math.pi * rm / self.n - 14, 120)
            fnt = fit_font("mono", name, max_w, 10, 8)
            name = ellipsize(name, fnt, max_w)
            ly = y + self.icon_size / 2 + 4
            if on:
                glow_text(img, (x, ly), name, fnt, white, self.accent, radius=3)
            else:
                d.text((x, ly), name, font=fnt, fill=self.neon + (215,), anchor="mm")
                d = ImageDraw.Draw(img)

        # texto central
        if sel is not None:
            item = self.items[sel]
            title = str(item["name"]).upper()
            sub = "▸ ABRIR CAMADA" if is_branch(item) else ">> EXECUTAR"
            sub_col, glow = self.accent, self.accent
        elif self.depth:
            title, sub, sub_col, glow = self.title.upper(), "◂ VOLTAR", self.accent, self.accent
        else:
            title, sub, sub_col, glow = self.title.upper(), "// SELECIONE", self.neon, self.neon
        fnt = fit_font("display", title, self.r * 2 - 22, 18, 9)
        title = ellipsize(title, fnt, self.r * 2 - 18)
        glow_text(img, (c, c - 5), title, fnt, white, glow, radius=5)
        ImageDraw.Draw(img).text((c, c + 15), sub, font=font("mono", 8),
                                 fill=sub_col + (230,), anchor="mm")

        # texto HUD nos cantos
        h = self.R + 40
        d = ImageDraw.Draw(img)
        crumb = self.crumb.upper()
        cf = font("mono", 9)
        while len(crumb) > 4 and cf.getlength(crumb) > 2 * h - 70:
            crumb = "…" + crumb[2:]
        d.text((c - h + 30, c - h), crumb, font=cf, fill=self.neon + (170,), anchor="lm")
        d.text((c + h - 30, c + h), f"{self.n:02d} NODES", font=font("mono", 9),
               fill=self.neon + (170,), anchor="rm")

    def sel_glow(self, sel):
        """Brilho extra da fatia selecionada (pulsa)."""
        if sel not in self._sel_glow:
            k = SS
            S = self.size * k
            c = S / 2
            step = 2 * math.pi / self.n
            a0 = sel * step - step / 2
            pts = sector(c, (self.r + 12) * k, (self.R + 12) * k, a0, a0 + step, 6 * k)
            im = Image.new("RGBA", (S, S), (0, 0, 0, 0))
            ImageDraw.Draw(im).line(pts + [pts[0]], fill=self.accent + (255,),
                                    width=10 * k, joint="curve")
            im = im.filter(ImageFilter.GaussianBlur(14 * k))
            self._sel_glow[sel] = im.resize((self.size, self.size), Image.BILINEAR)
        return self._sel_glow[sel]

    # ---------- anéis que giram ----------
    def _rings(self):
        k = SS
        S = self.size * k
        c = S / 2
        a = Image.new("RGBA", (S, S), (0, 0, 0, 0))
        g = Image.new("RGBA", (S, S), (0, 0, 0, 0))
        da, dg = ImageDraw.Draw(a), ImageDraw.Draw(g)
        ra = (self.R + 32) * k
        for base in (0, 120, 240):
            a0, a1 = math.radians(base), math.radians(base + 34)
            pts = arc_pts(c, ra, a0, a1)
            dg.line(pts, fill=self.accent + (255,), width=6 * k, joint="curve")
            da.line(pts, fill=mix(self.accent, (255, 255, 255), 0.3) + (255,),
                    width=2 * k, joint="curve")
            for j in range(4):  # pontinhos atrás do arco
                p = polar(c, ra, math.radians(base + 40 + j * 5))
                d = 1.5 * k
                da.ellipse((p[0] - d, p[1] - d, p[0] + d, p[1] + d),
                           fill=self.accent + (220 - j * 50,))
        ring_a = g.filter(ImageFilter.GaussianBlur(5 * k))
        ring_a.alpha_composite(a)

        b = Image.new("RGBA", (S, S), (0, 0, 0, 0))
        db = ImageDraw.Draw(b)
        rb = (self.R + 14) * k
        for deg in range(0, 360, 4):
            if deg % 90 < 60:
                aa = math.radians(deg)
                db.line(arc_pts(c, rb, aa, aa + math.radians(2)), fill=self.neon + (110,),
                        width=1 * k)
        size = (self.size, self.size)
        return ring_a.resize(size, Image.LANCZOS), b.resize(size, Image.LANCZOS)

    # ---------- quadro animado ----------
    def frame(self, sel, t: float, opening: float = 1.0, animate: bool = True,
              progress: float = 0.0) -> Image.Image:
        img = self.static(sel).copy()
        if animate:
            img.alpha_composite(self.ring_a.rotate(-t * 40, resample=Image.BILINEAR))
            img.alpha_composite(self.ring_b.rotate(t * 15, resample=Image.BILINEAR))
            if sel is not None:
                pulse = 0.45 + 0.55 * (0.5 + 0.5 * math.sin(t * 7))
                img.alpha_composite(scale_alpha(self.sel_glow(sel), pulse))
            # tremidinha de neon ocasional
            if int(t * 20) % 53 == 0:
                img = scale_alpha(img, 0.82)
        else:
            img.alpha_composite(self.ring_a)
            img.alpha_composite(self.ring_b)
            if sel is not None:
                img.alpha_composite(self.sel_glow(sel))

        if sel is not None and progress > 0:  # carregando a subcamada (passar o mouse)
            c = self.size / 2
            step = 2 * math.pi / self.n
            a0 = sel * step - step / 2 + 0.03
            a1 = a0 + (step - 0.06) * min(1.0, progress)
            pts = arc_pts(c, self.R + 22, a0, a1)
            d = ImageDraw.Draw(img)
            d.line(pts, fill=self.accent + (150,), width=9, joint="curve")
            d.line(pts, fill=(255, 255, 255, 255), width=3, joint="curve")

        if opening < 1.0 and animate:
            e = ease_out(max(0.0, opening))
            s = 0.8 + 0.2 * e
            w = max(1, round(self.size * s))
            small = img.resize((w, w), Image.BILINEAR)
            img = Image.new("RGBA", (self.size, self.size), (0, 0, 0, 0))
            off = (self.size - w) // 2
            img.alpha_composite(small, (off, off))
            if opening < 0.7:  # glitch: separa os canais de cor
                shift = round((1 - opening) * 9)
                r_, g_, b_, a_ = img.split()
                r_ = ImageChops.offset(r_, shift, 0)
                b_ = ImageChops.offset(b_, -shift, 0)
                a_ = ImageChops.lighter(a_, ImageChops.offset(a_, shift, 0))
                img = Image.merge("RGBA", (r_, g_, b_, a_))
            img = scale_alpha(img, e)
        return img


def tray_image(neon: str, accent: str, size: int = 64) -> Image.Image:
    s = 64 * 4
    n, a = rgb(neon), rgb(accent)
    im = Image.new("RGBA", (s, s), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    c = s / 2
    step = 2 * math.pi / 8
    for i in range(8):
        pts = sector(c, 70, 124, i * step - step / 2, i * step + step / 2, 18)
        d.polygon(pts, fill=(a if i == 0 else mix((10, 10, 20), n, 0.35)) + (255,))
    d.ellipse(circle(c, 52), outline=n + (255,), width=14)
    return im.resize((size, size), Image.LANCZOS)
