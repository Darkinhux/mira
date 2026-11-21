"""
Editor visual da roda: monta a roda sem mexer no config.json.

  esquerda  — árvore (roda principal, submenus, perfis). Arraste para reordenar
              ou para mover um item para dentro de outro submenu.
  meio      — prévia ao vivo da roda neon (clique numa fatia para selecionar).
  direita   — campos do item selecionado / configurações gerais.

Salvar confere tudo, guarda um backup (config.antes-do-editor.json) e recarrega
a roda na hora.
"""
from __future__ import annotations

import copy
import json
import math
import shlex
import tkinter as tk
from pathlib import Path
from tkinter import colorchooser, filedialog, messagebox, ttk

from PIL import Image, ImageTk

import neon

MAX_ITEMS = 12
BG, PANEL, FIELD, FG, DIM = "#0b0b16", "#11111f", "#07070f", "#e9fbff", "#7d86a8"
FONT = ("Segoe UI", 10)
MONO = ("Consolas", 10)

TYPES = [
    ("open", "Abrir programa, site ou pasta"),
    ("keys", "Apertar teclas"),
    ("menu", "Submenu (camada com itens)"),
    ("folder", "Pasta (mostra o que tem dentro)"),
    ("games", "Jogos instalados"),
    ("clipboard", "Copiados (histórico do Ctrl+C)"),
    ("snip", "Recortar a tela"),
    ("ocr", "Copiar texto da tela (OCR)"),
    ("screenshot", "Print da tela inteira"),
    ("command", "Rodar um comando"),
    ("default", "Roda normal (Geral)"),
]
TYPE_LABEL = dict(TYPES)
LABEL_TYPE = {v: k for k, v in TYPES}
TYPE_KEYS = {"target", "args", "keys", "command", "path", "sources", "items", "offset", "stay"}
STAY_TYPES = {"open", "keys", "command"}

FOLDER_PRESETS = ["{desktop}", "{downloads}", "{documents}", "{pictures}", "{videos}",
                  "{music}", "{pictures}/Mira", "C:\\"]
KEY_PRESETS = [("Play/Pause", "media_play_pause"), ("Próxima música", "media_next"),
               ("Música anterior", "media_previous"), ("Volume +", "media_volume_up"),
               ("Volume -", "media_volume_down"), ("Mudo", "media_volume_mute"),
               ("Gerenciador de Tarefas", "ctrl+shift+esc"), ("Explorador", "win+e"),
               ("Área de trabalho", "win+d"), ("Nova aba", "ctrl+t"),
               ("Reabrir aba", "ctrl+shift+t")]
TRIGGER_LABELS = {"mouse4": "Mouse 4 (lateral de trás)", "mouse5": "Mouse 5 (lateral da frente)",
                  "middle": "Botão do meio (rodinha)"}
EMOJIS = ("🎮 🕹️ 👾 🎯 🏆 🔫 ⚔️ 🃏 ⛏️ 🐉 🚀 🎧 🎵 🎬 📺 ▶️ ⏯️ ⏭️ ⏮️ 🔊 🔉 🔇 💬 📱 "
          "✉️ 🌐 🔎 🛒 👥 📚 📁 📂 🗂️ 💽 ⬇️ 📄 📝 🖼️ 📸 ✂️ 🔤 📋 🔗 🖥️ ⚙️ 🔒 🗑️ ⏻ ✋ "
          "🧭 ➕ ↩️ 🕶️ ✖️ 🧹 📊 🧮 🗓️ ⏰ 💡 🔥 ⚡ ⭐ ❤️ 🌙 🎨 🧪 🧩 🤖 💀 📦 🖨️").split()
TK_KEYS = {"Return": "enter", "Escape": "esc", "BackSpace": "backspace", "Tab": "tab",
           "space": "space", "Delete": "delete", "Insert": "insert", "Home": "home",
           "End": "end", "Prior": "page_up", "Next": "page_down", "Up": "up", "Down": "down",
           "Left": "left", "Right": "right", "Print": "print_screen"}
MODIFIER_SYMS = {"Shift_L", "Shift_R", "Control_L", "Control_R", "Alt_L", "Alt_R", "Win_L",
                 "Win_R", "Super_L", "Super_R", "Meta_L", "Meta_R", "Caps_Lock", "ISO_Level3_Shift"}


def tk_combo(event) -> str | None:
    """Converte um evento de tecla do Tk em "ctrl+shift+t" (formato do Mira)."""
    if event.keysym in MODIFIER_SYMS:
        return None
    mods = []
    if event.state & 0x4:
        mods.append("ctrl")
    if event.state & 0x20000 or event.state & 0x8:  # Alt no Windows / no X11
        mods.append("alt")
    if event.state & 0x1:
        mods.append("shift")
    sym = event.keysym
    if sym in TK_KEYS:
        key = TK_KEYS[sym]
    elif sym.lower().startswith("f") and sym[1:].isdigit():
        key = sym.lower()
    elif len(sym) == 1:
        key = sym.lower()
    elif event.char and event.char.isprintable() and len(event.char) == 1:
        key = event.char.lower()
    else:
        return None
    return "+".join(mods + [key])


def describe(item: dict) -> str:
    icon = item.get("icon", "")
    icon = "" if icon == "auto" or len(icon) > 4 else icon
    return f"{icon}  {item.get('name', '?')}".strip()


class RodaEditor:
    def __init__(self, root: tk.Misc, config_path: Path, defaults: dict, helpers: dict):
        """helpers: check_items(items, where, minimum), file_icon(path, size),
        resolve_path(spec), on_saved() — vêm do mira.py."""
        self.config_path = Path(config_path)
        self.defaults = defaults
        self.h = helpers
        self.data = json.loads(self.config_path.read_text(encoding="utf-8"))
        self.data.setdefault("items", [])
        self.data.setdefault("profiles", [])
        self.dirty = False
        self.nodes: dict[str, tuple] = {}       # iid -> ("container"|"item"|..., objeto, lista-pai)
        self.iid_of: dict[int, str] = {}         # id(objeto) -> iid
        self.current = None                      # (tipo, objeto, lista-pai)
        self.vars: dict[str, tk.Variable] = {}
        self._preview_job = None
        self._photo = None
        self._icon_photos: list = []
        self._drag = None
        self._preview_geom = None

        w = self.win = tk.Toplevel(root)
        w.title("Mira — Editor da roda")
        w.configure(bg=BG)
        w.geometry("1180x700")
        w.minsize(980, 600)
        w.protocol("WM_DELETE_WINDOW", self.close)
        self._style()
        self._layout()
        self.rebuild_tree()
        self.select(self.data["items"], "container")
        w.bind("<Control-s>", lambda e: self.save())
        w.lift()
        w.focus_force()

    # ================================================================ visual
    def _style(self):
        st = ttk.Style(self.win)
        try:
            st.theme_use("clam")
        except tk.TclError:
            pass
        neon_c = self.data.get("neon", "#00f0ff")
        st.configure("Mira.Treeview", background=PANEL, fieldbackground=PANEL, foreground=FG,
                     rowheight=26, borderwidth=0, font=FONT)
        st.map("Mira.Treeview", background=[("selected", "#1e2a44")],
               foreground=[("selected", neon_c)])
        st.configure("TCombobox", fieldbackground=FIELD, background=PANEL, foreground=FG,
                     arrowcolor=neon_c, bordercolor="#2a2a44")
        st.map("TCombobox", fieldbackground=[("readonly", FIELD)], foreground=[("readonly", FG)])
        st.configure("Mira.TCheckbutton", background=PANEL, foreground=FG, font=FONT)
        st.map("Mira.TCheckbutton", background=[("active", PANEL)])
        st.configure("Mira.Horizontal.TScale", background=PANEL, troughcolor=FIELD)
        self.win.option_add("*TCombobox*Listbox.background", FIELD)
        self.win.option_add("*TCombobox*Listbox.foreground", FG)

    def _button(self, parent, text, cmd, accent=False, width=None):
        neon_c, acc = self.data.get("neon", "#00f0ff"), self.data.get("accent", "#ff2a6d")
        b = tk.Button(parent, text=text, command=cmd, font=("Segoe UI", 10, "bold"),
                      bg=acc if accent else "#16162a", fg="#ffffff" if accent else neon_c,
                      activebackground=neon_c, activeforeground=BG, relief="flat", bd=0,
                      padx=10, pady=5, cursor="hand2", highlightthickness=1,
                      highlightbackground=acc if accent else "#2a2a44")
        if width:
            b.configure(width=width)
        return b

    def _layout(self):
        w = self.win
        neon_c = self.data.get("neon", "#00f0ff")
        bar = tk.Frame(w, bg=BG, pady=8, padx=10)
        bar.pack(fill="x")
        tk.Label(bar, text="MIRA.SYS // EDITOR", bg=BG, fg=neon_c,
                 font=("Consolas", 12, "bold")).pack(side="left", padx=(0, 16))
        for text, cmd in (("＋ Item", self.add_item), ("＋ Submenu", self.add_menu),
                          ("＋ Perfil", self.add_profile), ("⧉ Duplicar", self.duplicate),
                          ("▲", lambda: self.move(-1)), ("▼", lambda: self.move(1)),
                          ("🗑 Remover", self.remove)):
            self._button(bar, text, cmd).pack(side="left", padx=2)
        self._button(bar, "💾 Salvar", self.save, accent=True).pack(side="right", padx=2)
        self._button(bar, "Fechar", self.close).pack(side="right", padx=2)
        self.status = tk.Label(bar, text="", bg=BG, fg=DIM, font=FONT)
        self.status.pack(side="right", padx=10)

        body = tk.Frame(w, bg=BG)
        body.pack(fill="both", expand=True, padx=10, pady=(0, 10))

        left = tk.Frame(body, bg=PANEL, highlightthickness=1, highlightbackground="#2a2a44")
        left.pack(side="left", fill="y")
        self.tree = ttk.Treeview(left, style="Mira.Treeview", show="tree", selectmode="browse")
        self.tree.column("#0", width=290)
        self.tree.pack(fill="both", expand=True, padx=4, pady=4)
        self.tree.bind("<<TreeviewSelect>>", self._on_tree_select)
        self.tree.bind("<ButtonPress-1>", self._drag_start, add="+")
        self.tree.bind("<B1-Motion>", self._drag_motion, add="+")
        self.tree.bind("<ButtonRelease-1>", self._drag_end, add="+")
        tk.Label(left, text="Arraste para reordenar ou mover\npara dentro de outro submenu.",
                 bg=PANEL, fg=DIM, font=("Segoe UI", 8), justify="left").pack(anchor="w",
                                                                              padx=8, pady=4)

        mid = tk.Frame(body, bg=BG)
        mid.pack(side="left", fill="both", expand=True)
        self.preview = tk.Canvas(mid, bg=BG, highlightthickness=0, width=420, height=420)
        self.preview.pack(expand=True)
        self.preview.bind("<Button-1>", self._on_preview_click)
        self.preview_hint = tk.Label(mid, text="Clique numa fatia para editar", bg=BG, fg=DIM,
                                     font=FONT)
        self.preview_hint.pack(pady=(0, 6))

        right = tk.Frame(body, bg=PANEL, highlightthickness=1, highlightbackground="#2a2a44",
                         width=380)
        right.pack(side="left", fill="y")
        right.pack_propagate(False)
        self.form = tk.Frame(right, bg=PANEL, padx=14, pady=12)
        self.form.pack(fill="both", expand=True)

    # ================================================================ árvore
    def _add_node(self, parent_iid, iid, text, kind, obj, parent_list):
        self.tree.insert(parent_iid, "end", iid=iid, text=text, open=True)
        self.nodes[iid] = (kind, obj, parent_list)
        self.iid_of[id(obj)] = iid

    def rebuild_tree(self):
        sel_obj = self.current[1] if self.current else None
        self.tree.delete(*self.tree.get_children())
        self.nodes.clear()
        self.iid_of.clear()
        counter = [0]

        def nid():
            counter[0] += 1
            return f"n{counter[0]}"

        self.tree.insert("", "end", iid="settings", text="⚙  Configurações gerais")
        self.nodes["settings"] = ("settings", None, None)

        def add_items(parent_iid, items):
            for it in items:
                iid = nid()
                self._add_node(parent_iid, iid, describe(it), "item", it, items)
                if it.get("type") == "menu":
                    add_items(iid, it.setdefault("items", []))

        root_items = self.data["items"]
        self._add_node("", "root", f"◉  Roda principal ({len(root_items)}/{MAX_ITEMS})",
                       "container", root_items, None)
        add_items("root", root_items)
        self.tree.insert("", "end", iid="profiles", text="◎  Perfis por programa", open=True)
        self.nodes["profiles"] = ("profiles", self.data["profiles"], None)
        for prof in self.data["profiles"]:
            iid = nid()
            self._add_node("profiles", iid, f"@ {prof.get('name', '?')}", "profile", prof,
                           self.data["profiles"])
            add_items(iid, prof.setdefault("items", []))
        if sel_obj is not None and id(sel_obj) in self.iid_of:
            iid = self.iid_of[id(sel_obj)]
            self.tree.selection_set(iid)
            self.tree.see(iid)

    def _refresh_label(self, obj):
        iid = self.iid_of.get(id(obj))
        if not iid:
            return
        kind = self.nodes[iid][0]
        if kind == "item":
            self.tree.item(iid, text=describe(obj))
        elif kind == "profile":
            self.tree.item(iid, text=f"@ {obj.get('name', '?')}")
        self.tree.item("root", text=f"◉  Roda principal ({len(self.data['items'])}/{MAX_ITEMS})")

    def _on_tree_select(self, _e=None):
        sel = self.tree.selection()
        if not sel:
            return
        kind, obj, parent = self.nodes[sel[0]]
        if self.current and self.current[1] is obj and self.current[0] == kind:
            return
        self.current = (kind, obj, parent)
        self.build_form()
        self.schedule_preview()

    def select(self, obj, kind=None):
        """Seleciona um objeto (lista de itens, item ou perfil) na árvore."""
        iid = "settings" if obj == "settings" else self.iid_of.get(id(obj))
        if iid:
            self.tree.selection_set(iid)
            self.tree.see(iid)
            self._on_tree_select()

    # ---- arrastar e soltar
    def _drag_start(self, e):
        iid = self.tree.identify_row(e.y)
        ok = iid and self.nodes.get(iid, ("",))[0] == "item"
        self._drag = (iid, e.y, False) if ok else None

    def _drag_motion(self, e):
        if self._drag and abs(e.y - self._drag[1]) > 6:  # só arrasta depois de mover um pouco
            self._drag = (self._drag[0], self._drag[1], True)
            self.tree.configure(cursor="fleur")

    def _drag_end(self, e):
        drag, self._drag = self._drag, None
        self.tree.configure(cursor="")
        if not drag or not drag[2]:
            return
        src = drag[0]
        dst = self.tree.identify_row(e.y)
        if not dst or dst == src:
            return
        self.move_to(self.nodes[src][1], dst)

    def move_to(self, item: dict, dst_iid: str) -> bool:
        """Move o item para antes do item de destino, ou para dentro de uma camada."""
        kind, obj, parent = self.nodes[dst_iid]
        if kind == "item" and obj.get("type") != "menu":
            target_list, pos = parent, None
        elif kind in ("container", "profile") or (kind == "item" and obj.get("type") == "menu"):
            target_list = obj if kind == "container" else obj.setdefault("items", [])
            pos = len(target_list)  # soltar em cima de uma camada/submenu: entra no fim dela
        else:
            return False
        if item.get("type") == "menu" and self._contains(item, target_list):
            return False  # não dá para colocar um submenu dentro dele mesmo
        src_list = self.nodes[self.iid_of[id(item)]][2]
        if target_list is not src_list and len(target_list) >= MAX_ITEMS:
            self.flash(f"Essa camada já tem {MAX_ITEMS} itens.", error=True)
            return False
        src_list.remove(item)
        if pos is None:
            pos = target_list.index(obj)
        target_list.insert(min(pos, len(target_list)), item)
        self.current = ("item", item, target_list)
        self.changed(structure=True)
        return True

    @staticmethod
    def _contains(menu: dict, lst: list) -> bool:
        if menu.get("items") is lst:
            return True
        return any(c.get("type") == "menu" and RodaEditor._contains(c, lst)
                   for c in menu.get("items", []))

    # ================================================================ ações
    def _target_list(self):
        """Lista onde um item novo entra, e a posição."""
        kind, obj, parent = self.current or ("container", self.data["items"], None)
        if kind == "container":
            return obj, len(obj)
        if kind == "profile":
            return obj.setdefault("items", []), len(obj["items"])
        if kind == "item" and obj.get("type") == "menu":
            return obj.setdefault("items", []), len(obj["items"])
        if kind == "item":
            return parent, parent.index(obj) + 1
        return self.data["items"], len(self.data["items"])

    def _insert(self, new: dict):
        lst, pos = self._target_list()
        if len(lst) >= MAX_ITEMS:
            self.flash(f"Cada camada aceita no máximo {MAX_ITEMS} itens.", error=True)
            return None
        lst.insert(pos, new)
        self.current = ("item", new, lst)
        self.changed(structure=True)
        return new

    def add_item(self):
        return self._insert({"name": "Novo item", "icon": "⭐", "type": "open", "target": ""})

    def add_menu(self):
        return self._insert({"name": "Novo submenu", "icon": "📂", "type": "menu", "items": []})

    def add_profile(self):
        prof = {"name": "Novo perfil", "match": [], "items": [
            {"name": "Recortar", "icon": "✂️", "type": "snip"},
            {"name": "Geral", "icon": "🧭", "type": "default"}]}
        self.data["profiles"].append(prof)
        self.current = ("profile", prof, self.data["profiles"])
        self.changed(structure=True)
        return prof

    def duplicate(self):
        if not self.current or self.current[0] not in ("item", "profile"):
            return
        kind, obj, parent = self.current
        if kind == "item" and len(parent) >= MAX_ITEMS:
            self.flash(f"Essa camada já tem {MAX_ITEMS} itens.", error=True)
            return
        clone = copy.deepcopy(obj)
        clone.pop("id", None)
        clone["name"] = f"{obj.get('name', '')} (cópia)"
        parent.insert(parent.index(obj) + 1, clone)
        self.current = (kind, clone, parent)
        self.changed(structure=True)

    def move(self, delta: int):
        if not self.current or self.current[0] not in ("item", "profile"):
            return
        _, obj, parent = self.current
        i = parent.index(obj)
        j = max(0, min(len(parent) - 1, i + delta))
        if i != j:
            parent.insert(j, parent.pop(i))
            self.changed(structure=True)

    def remove(self, ask: bool = True):
        if not self.current or self.current[0] not in ("item", "profile"):
            return
        kind, obj, parent = self.current
        n = len(obj.get("items", []))
        if ask and (kind == "profile" or n):
            what = f"o perfil \"{obj.get('name')}\"" if kind == "profile" else \
                f"o submenu \"{obj.get('name')}\" e os {n} itens dentro dele"
            if not messagebox.askyesno("Remover", f"Remover {what}?", parent=self.win):
                return
        idx = parent.index(obj)
        parent.remove(obj)
        if parent:
            nxt = parent[min(idx, len(parent) - 1)]
            self.current = (kind, nxt, parent)
        else:
            owner = self._owner_of(parent)
            self.current = owner
        self.changed(structure=True)

    def _owner_of(self, lst):
        if lst is self.data["items"]:
            return ("container", lst, None)
        for iid, (kind, obj, parent) in self.nodes.items():
            if kind in ("item", "profile") and obj.get("items") is lst:
                return (kind, obj, parent)
        return ("container", self.data["items"], None)

    # ================================================================ formulário
    def _clear_form(self):
        for c in self.form.winfo_children():
            c.destroy()
        self.vars = {}
        self._icon_photos = []

    def _title(self, text, sub=""):
        tk.Label(self.form, text=text, bg=PANEL, fg=self.data.get("neon", "#00f0ff"),
                 font=("Consolas", 13, "bold"), anchor="w").pack(fill="x")
        if sub:
            tk.Label(self.form, text=sub, bg=PANEL, fg=DIM, font=("Segoe UI", 9), anchor="w",
                     justify="left", wraplength=340).pack(fill="x", pady=(2, 8))

    def _label(self, text, parent=None):
        tk.Label(parent or self.form, text=text, bg=PANEL, fg=DIM, font=("Segoe UI", 9),
                 anchor="w").pack(fill="x", pady=(8, 2))

    def _entry(self, key, value, on_change, parent=None, mono=False):
        var = tk.StringVar(value=value)
        self.vars[key] = var
        e = tk.Entry(parent or self.form, textvariable=var, bg=FIELD, fg=FG,
                     insertbackground=FG, relief="flat", font=MONO if mono else FONT,
                     highlightthickness=1, highlightbackground="#2a2a44",
                     highlightcolor=self.data.get("neon", "#00f0ff"))
        e.pack(fill="x", ipady=4)
        var.trace_add("write", lambda *_: on_change(var.get()))
        return e

    def _row(self):
        f = tk.Frame(self.form, bg=PANEL)
        f.pack(fill="x", pady=(4, 0))
        return f

    def _check(self, key, text, value, on_change, parent=None):
        var = tk.BooleanVar(value=bool(value))
        self.vars[key] = var
        ttk.Checkbutton(parent or self.form, text=text, variable=var, style="Mira.TCheckbutton",
                        command=lambda: on_change(var.get())).pack(anchor="w", pady=2)
        return var

    def build_form(self):
        self._clear_form()
        kind, obj, _ = self.current
        if kind == "settings":
            return self._settings_form()
        if kind == "container":
            self._title("Roda principal", "É a roda que abre com o botão do mouse. Selecione "
                        "um item à esquerda (ou uma fatia na prévia) para editar, ou use "
                        "＋ Item / ＋ Submenu.")
            return
        if kind == "profiles":
            self._title("Perfis por programa", "Uma roda diferente quando um programa está "
                        "na frente. Use ＋ Perfil para criar.")
            return
        if kind == "profile":
            return self._profile_form(obj)
        return self._item_form(obj)

    def _profile_form(self, prof):
        self._title("Perfil", "Esta roda aparece no lugar da principal quando o programa "
                    "abaixo está na frente.")
        self._label("Nome")
        self._entry("name", prof.get("name", ""), lambda v: self._set(prof, "name", v))
        self._label("Programas (.exe), separados por vírgula — aceita *")
        self._entry("match", ", ".join(prof.get("match", [])),
                    lambda v: self._set(prof, "match",
                                        [s.strip() for s in v.split(",") if s.strip()]), mono=True)
        tk.Label(self.form, text="Descubra o nome no Gerenciador de Tarefas → Detalhes.\n"
                 "Ex.: VALORANT-Win64-Shipping.exe, chrome.exe, javaw.exe", bg=PANEL, fg=DIM,
                 font=("Segoe UI", 8), justify="left", anchor="w").pack(fill="x")
        self._label("Ou um pedaço do título da janela (opcional)")
        self._entry("title", ", ".join(prof.get("title", [])),
                    lambda v: self._set(prof, "title",
                                        [s.strip() for s in v.split(",") if s.strip()]))

    def _item_form(self, item):
        t = item.get("type", "open")
        self._title("Item", "As mudanças aparecem na prévia na hora. Lembre de salvar.")
        self._label("Nome")
        self._entry("name", item.get("name", ""), lambda v: self._set(item, "name", v))

        self._label("Ícone (emoji, imagem ou auto)")
        row = self._row()
        self.icon_preview = tk.Label(row, bg=PANEL)
        self.icon_preview.pack(side="left", padx=(0, 6))
        ent = tk.Frame(row, bg=PANEL)
        ent.pack(side="left", fill="x", expand=True)
        self._entry("icon", item.get("icon", ""), lambda v: (self._set(item, "icon", v),
                                                             self._update_icon_preview(item)),
                    parent=ent)
        row2 = self._row()
        self._button(row2, "😀 Emoji…", lambda: self.emoji_picker(item)).pack(side="left")
        self._button(row2, "🖼 Imagem…", lambda: self._pick_image(item)).pack(side="left", padx=4)
        if t == "open":
            self._button(row2, "Auto", lambda: self.vars["icon"].set("auto")).pack(side="left")
        self._update_icon_preview(item)

        self._label("O que faz")
        combo = ttk.Combobox(self.form, values=[lbl for _, lbl in TYPES], state="readonly",
                             font=FONT)
        combo.set(TYPE_LABEL.get(t, t))
        combo.pack(fill="x", ipady=3)
        combo.bind("<<ComboboxSelected>>", lambda e: self.set_type(item, LABEL_TYPE[combo.get()]))
        self.vars["type"] = combo

        if t == "open":
            self._label("Abrir (programa, arquivo, pasta, site ou steam://…)")
            self._entry("target", item.get("target", ""), lambda v: self._set(item, "target", v),
                        mono=True)
            r = self._row()
            self._button(r, "Arquivo…", lambda: self._browse(item, "target", "file")).pack(
                side="left")
            self._button(r, "Pasta…", lambda: self._browse(item, "target", "dir")).pack(
                side="left", padx=4)
            self._label("Argumentos (opcional)")
            args = item.get("args") or []
            self._entry("args", " ".join(f'"{a}"' if " " in a else a for a in args),
                        lambda v: self._set_args(item, v), mono=True)
        elif t == "keys":
            self._label("Teclas (ex.: ctrl+shift+t, win+e, media_next)")
            self._entry("keys", item.get("keys", ""), lambda v: self._set(item, "keys", v),
                        mono=True)
            r = self._row()
            self._button(r, "⏺ Gravar", lambda: self.record_keys(item)).pack(side="left")
            preset = ttk.Combobox(r, values=[n for n, _ in KEY_PRESETS], state="readonly",
                                  width=22)
            preset.set("Prontas…")
            preset.pack(side="left", padx=6)
            preset.bind("<<ComboboxSelected>>", lambda e: self.vars["keys"].set(
                dict(KEY_PRESETS)[preset.get()]))
        elif t == "command":
            self._label("Comando (Prompt do Windows)")
            self._entry("command", item.get("command", ""),
                        lambda v: self._set(item, "command", v), mono=True)
        elif t == "folder":
            self._label("Pasta")
            var = tk.StringVar(value=item.get("path", ""))
            self.vars["path"] = var
            c = ttk.Combobox(self.form, textvariable=var, values=FOLDER_PRESETS, font=MONO)
            c.pack(fill="x", ipady=3)
            var.trace_add("write", lambda *_: self._set(item, "path", var.get()))
            r = self._row()
            self._button(r, "Escolher…", lambda: self._browse(item, "path", "dir")).pack(
                side="left")
        elif t == "games":
            self._label("Procurar jogos em")
            srcs = item.setdefault("sources", ["steam", "epic", "riot"])
            for s, lbl in (("steam", "Steam"), ("epic", "Epic Games"), ("riot", "Riot")):
                self._check(f"src_{s}", lbl, s in srcs,
                            lambda on, s=s: self._toggle_source(item, s, on))
        elif t == "menu":
            n = len(item.get("items", []))
            tk.Label(self.form, text=f"Este submenu tem {n} item(ns). Eles aparecem embaixo "
                     "dele na lista à esquerda.", bg=PANEL, fg=DIM, font=("Segoe UI", 9),
                     wraplength=340, justify="left", anchor="w").pack(fill="x", pady=(10, 4))
            r = self._row()
            self._button(r, "＋ Item dentro", self.add_item).pack(side="left")
            self._button(r, "＋ Submenu dentro", self.add_menu).pack(side="left", padx=4)
        else:
            tk.Label(self.form, text="Não precisa configurar mais nada.", bg=PANEL, fg=DIM,
                     font=("Segoe UI", 9), anchor="w").pack(fill="x", pady=(10, 0))
        if t in STAY_TYPES:
            self._check("stay", "Manter a roda aberta depois (bom para volume)",
                        item.get("stay"), lambda on: self._set(item, "stay", on or None))

    def _settings_form(self):
        d = self.data
        self._title("Configurações gerais")
        self._label("Botão que abre a roda")
        trig = ttk.Combobox(self.form, values=list(TRIGGER_LABELS.values()), state="readonly")
        trig.set(TRIGGER_LABELS.get(d.get("trigger", "mouse4"), "Mouse 4 (lateral de trás)"))
        trig.pack(fill="x", ipady=3)
        trig.bind("<<ComboboxSelected>>", lambda e: self._set(
            d, "trigger", {v: k for k, v in TRIGGER_LABELS.items()}[trig.get()]))
        self.vars["trigger"] = trig

        self._label("Cores")
        row = self._row()
        for key, lbl in (("neon", "Neon"), ("accent", "Destaque"), ("background", "Fundo")):
            self._color_button(row, key, lbl)

        def scale(key, lbl, lo, hi, default, fmt):
            self._label(lbl)
            var = tk.IntVar(value=int(d.get(key, default)))
            self.vars[key] = var
            txt = tk.Label(self.form, text=fmt(var.get()), bg=PANEL, fg=FG, font=MONO)
            ttk.Scale(self.form, from_=lo, to=hi, variable=var, style="Mira.Horizontal.TScale",
                      command=lambda v: (var.set(int(float(v))), txt.configure(text=fmt(var.get())),
                                         self._set(d, key, var.get()))).pack(fill="x")
            txt.pack(anchor="e")

        scale("radius", "Tamanho da roda", 120, 260, 170, lambda v: f"{v} px")
        scale("hover_open_ms", "Parar o mouse em cima abre a camada em", 0, 1500, 450,
              lambda v: "só clicando" if v == 0 else f"{v / 1000:.2f} s")

        self._label("Opções")
        for key, lbl in (("animations", "Animações (anéis girando, glitch)"),
                         ("print_screen", "PrtSc abre o recorte do Mira"),
                         ("clipboard_history", "Guardar histórico do Ctrl+C"),
                         ("clipboard_save", "…e salvar os textos copiados no disco"),
                         ("update_check", "Procurar atualizações sozinho")):
            self._check(key, lbl, d.get(key, self.defaults.get(key, True)),
                        lambda on, k=key: self._set(d, k, bool(on)))

        self._label("Pasta dos prints")
        self._entry("screenshot_folder", d.get("screenshot_folder", "{pictures}/Mira"),
                    lambda v: self._set(d, "screenshot_folder", v), mono=True)

    def _color_button(self, parent, key, label):
        color = self.data.get(key, self.defaults.get(key, "#00f0ff"))
        b = tk.Button(parent, text=label, bg=color, fg=BG if key != "background" else FG,
                      relief="flat", font=("Segoe UI", 9, "bold"), padx=8, pady=4,
                      cursor="hand2")

        def pick():
            _, hexc = colorchooser.askcolor(self.data.get(key, color), parent=self.win,
                                            title=f"Cor: {label}")
            if hexc:
                self._set(self.data, key, hexc)
                b.configure(bg=hexc)

        b.configure(command=pick)
        b.pack(side="left", padx=(0, 6))

    # ---- mudanças nos campos
    def _set(self, obj, key, value):
        if value in (None, "", []) and key in ("stay", "args"):
            obj.pop(key, None)
        else:
            obj[key] = value
        if obj is self.current[1] or key in ("name", "icon"):
            self._refresh_label(obj)
        self.changed()

    def _set_args(self, item, text):
        try:
            args = shlex.split(text, posix=False)
        except ValueError:
            return
        self._set(item, "args", [a.strip('"') for a in args] or None)

    def _toggle_source(self, item, src, on):
        srcs = [s for s in item.get("sources", []) if s != src]
        if on:
            srcs.append(src)
        self._set(item, "sources", srcs)

    def set_type(self, item, new_type):
        if item.get("type") == new_type:
            return
        if item.get("type") == "menu" and item.get("items"):
            if not messagebox.askyesno("Trocar tipo", "Este submenu tem itens dentro. Trocar o "
                                       "tipo apaga esses itens. Continuar?", parent=self.win):
                self.build_form()
                return
        for k in TYPE_KEYS:
            item.pop(k, None)
        item["type"] = new_type
        if new_type == "menu":
            item["items"] = []
        elif new_type == "games":
            item["sources"] = ["steam", "epic", "riot"]
        elif new_type in ("open", "keys", "command", "folder"):
            item[{"open": "target", "keys": "keys", "command": "command",
                  "folder": "path"}[new_type]] = ""
        self.changed(structure=True)

    def _browse(self, item, key, mode):
        if mode == "dir":
            p = filedialog.askdirectory(parent=self.win, title="Escolher pasta")
        else:
            p = filedialog.askopenfilename(parent=self.win, title="Escolher programa ou arquivo",
                                           filetypes=[("Programas e atalhos", "*.exe *.lnk *.url"),
                                                      ("Todos", "*.*")])
        if p:
            self.vars[key].set(str(Path(p)))
            if key == "target" and item.get("icon") in ("", "⭐") and p.lower().endswith(".exe"):
                self.vars["icon"].set("auto")
            if not item.get("name") or item.get("name") == "Novo item":
                self.vars["name"].set(Path(p).stem)

    def _pick_image(self, item):
        p = filedialog.askopenfilename(parent=self.win, title="Escolher imagem",
                                       filetypes=[("Imagens", "*.png *.ico *.jpg *.jpeg *.gif "
                                                   "*.bmp *.webp")])
        if p:
            self.vars["icon"].set(str(Path(p)))

    def _icon_image(self, item, size=32):
        spec = item.get("icon", "")
        if spec == "auto":
            target = self.h["resolve_path"](str(item.get("target") or ""))
            return self.h["file_icon"](target, size) if Path(target).exists() else None
        return neon.load_icon(spec, size) if spec else None

    def _update_icon_preview(self, item):
        img = self._icon_image(item)
        if img is None:
            img = Image.new("RGBA", (32, 32), (0, 0, 0, 0))
        ph = ImageTk.PhotoImage(img)
        self._icon_photos.append(ph)
        self.icon_preview.configure(image=ph)

    # ---- seletor de emoji
    def emoji_picker(self, item):
        pop = tk.Toplevel(self.win)
        pop.title("Escolher emoji")
        pop.configure(bg=PANEL)
        pop.transient(self.win)
        photos = []
        cols = 10
        for i, emo in enumerate(EMOJIS):
            im = neon.load_icon(emo, 28)
            if im is None:
                b = tk.Button(pop, text=emo, font=("Segoe UI Emoji", 16), bg=PANEL, fg=FG,
                              relief="flat")
            else:
                ph = ImageTk.PhotoImage(im)
                photos.append(ph)
                b = tk.Button(pop, image=ph, bg=PANEL, activebackground="#1e2a44",
                              relief="flat", width=40, height=40)
            b.configure(command=lambda e=emo: (self.vars["icon"].set(e), pop.destroy()),
                        cursor="hand2")
            b.grid(row=i // cols, column=i % cols, padx=1, pady=1)
        pop._photos = photos  # mantém as imagens vivas
        return pop

    # ---- gravar teclas
    def record_keys(self, item):
        pop = tk.Toplevel(self.win)
        pop.title("Gravar teclas")
        pop.configure(bg=PANEL, padx=20, pady=16)
        pop.transient(self.win)
        tk.Label(pop, text="Aperte a combinação de teclas…", bg=PANEL, fg=FG,
                 font=("Segoe UI", 12, "bold")).pack()
        shown = tk.Label(pop, text="", bg=PANEL, fg=self.data.get("neon", "#00f0ff"),
                         font=("Consolas", 16, "bold"))
        shown.pack(pady=10)
        tk.Label(pop, text="A tecla Windows não dá para gravar: digite \"win+…\" no campo.",
                 bg=PANEL, fg=DIM, font=("Segoe UI", 8)).pack()

        def on_key(e):
            combo = tk_combo(e)
            if combo:
                shown.configure(text=combo)
                self.vars["keys"].set(combo)
                pop.after(500, pop.destroy)
            return "break"

        pop.bind("<KeyPress>", on_key)
        pop.focus_force()
        return pop, on_key

    # ================================================================ prévia
    def _layer_for_preview(self):
        """(itens, título, índice selecionado) da camada que a prévia mostra."""
        kind, obj, parent = self.current or ("container", self.data["items"], None)
        if kind == "item" and obj.get("type") == "menu":
            return obj.get("items", []), obj.get("name", ""), None
        if kind == "item":
            owner = self._owner_of(parent)
            title = "MIRA" if owner[1] is self.data["items"] else owner[1].get("name", "")
            return parent, title, parent.index(obj)
        if kind == "profile":
            return obj.get("items", []), obj.get("name", ""), None
        return self.data["items"], "MIRA", None

    def schedule_preview(self):
        if self._preview_job:
            self.win.after_cancel(self._preview_job)
        self._preview_job = self.win.after(120, self.render_preview)

    def render_preview(self):
        self._preview_job = None
        items, title, sel = self._layer_for_preview()
        self._preview_items = items
        cv = self.preview
        cv.delete("all")
        if not items:
            cv.create_text(210, 210, text="Camada vazia\nuse ＋ Item", fill=DIM,
                           font=("Consolas", 14, "bold"), justify="center")
            self._preview_geom = None
            return
        view_cfg = {**self.defaults, **{k: v for k, v in self.data.items()
                                        if k not in ("items", "profiles")}}
        shown = []
        for it in items:
            c = dict(it)
            if c.get("icon") == "auto":
                c["_icon_img"] = self._icon_image(it, int(view_cfg.get("icon_size", 34)))
                c["icon"] = "" if c["_icon_img"] is not None else "⚙️"
            shown.append(c)
        try:
            is_root = items is self.data["items"] or any(
                p.get("items") is items for p in self.data["profiles"])  # perfil = roda principal
            wheel = neon.NeonWheel(view_cfg, shown, title or "MIRA", f"MIRA.SYS / {title}".upper(),
                                   0 if is_root else 1)
            img = wheel.frame(sel, 1.0, 1.0, animate=False)
        except Exception as e:
            cv.create_text(210, 210, text=f"Erro na prévia:\n{e}", fill="#ff6b6b", width=380)
            return
        size = 420
        bg = Image.new("RGBA", img.size, BG)
        bg.alpha_composite(img)
        bg = bg.resize((size, size), Image.LANCZOS)
        self._photo = ImageTk.PhotoImage(bg)
        cv.create_image(0, 0, anchor="nw", image=self._photo)
        self._preview_geom = (size / img.size[0], wheel)

    def _on_preview_click(self, e):
        if not self._preview_geom:
            return
        scale, wheel = self._preview_geom
        c = 210
        dx, dy = (e.x - c) / scale, (e.y - c) / scale
        if math.hypot(dx, dy) < wheel.r or math.hypot(dx, dy) > wheel.R + 20:
            return
        n = len(self._preview_items)
        ang = math.atan2(dx, -dy) % (2 * math.pi)
        step = 2 * math.pi / n
        idx = int(((ang + step / 2) % (2 * math.pi)) // step) % n
        self.select(self._preview_items[idx])

    # ================================================================ salvar
    def changed(self, structure=False):
        self.dirty = True
        self.status.configure(text="● alterações não salvas", fg=self.data.get("accent",
                                                                                "#ff2a6d"))
        if structure:
            self.rebuild_tree()
            self.build_form()
        self.schedule_preview()

    def flash(self, text, error=False):
        self.status.configure(text=text, fg=self.data.get("accent", "#ff2a6d") if error
                              else self.data.get("neon", "#00f0ff"))

    def problems(self) -> list[tuple[object, str]]:
        """Lista de (objeto, problema) que impedem salvar."""
        out = []

        def walk(items, where):
            for it in items:
                name = it.get("name") or "(sem nome)"
                t = it.get("type", "open")
                if not str(it.get("name", "")).strip():
                    out.append((it, f"um item em {where} está sem nome"))
                if t == "open" and not str(it.get("target", "")).strip():
                    out.append((it, f"\"{name}\": falta dizer o que abrir"))
                if t == "keys" and not str(it.get("keys", "")).strip():
                    out.append((it, f"\"{name}\": falta escolher as teclas"))
                if t == "command" and not str(it.get("command", "")).strip():
                    out.append((it, f"\"{name}\": falta o comando"))
                if t == "folder" and not str(it.get("path", "")).strip():
                    out.append((it, f"\"{name}\": falta escolher a pasta"))
                if t == "games" and not it.get("sources"):
                    out.append((it, f"\"{name}\": marque pelo menos uma loja"))
                if t == "menu":
                    if not it.get("items"):
                        out.append((it, f"o submenu \"{name}\" está vazio"))
                    walk(it.get("items", []), f"\"{name}\"")

        if len(self.data["items"]) < 2:
            out.append((self.data["items"], "a roda principal precisa de pelo menos 2 itens"))
        walk(self.data["items"], "Roda principal")
        for prof in self.data["profiles"]:
            if not prof.get("match") and not prof.get("title"):
                out.append((prof, f"o perfil \"{prof.get('name')}\" precisa de um programa"))
            if not prof.get("items"):
                out.append((prof, f"o perfil \"{prof.get('name')}\" está vazio"))
            walk(prof.get("items", []), f"perfil \"{prof.get('name')}\"")
        return out

    def save(self, quiet: bool = False) -> bool:
        probs = self.problems()
        if probs:
            obj, msg = probs[0]
            self.select(obj)
            extra = f"\n\n(e mais {len(probs) - 1} problema(s))" if len(probs) > 1 else ""
            if not quiet:
                messagebox.showwarning("Falta pouco", f"Não deu para salvar: {msg}.{extra}",
                                       parent=self.win)
            self.flash(f"⚠ {msg}", error=True)
            return False
        try:  # a mesma validação que o Mira usa ao carregar
            self.h["check_items"](copy.deepcopy(self.data["items"]), "a roda principal", 2)
        except ValueError as e:
            if not quiet:
                messagebox.showwarning("Falta pouco", str(e), parent=self.win)
            return False
        if self.config_path.exists():
            self.config_path.with_name("config.antes-do-editor.json").write_text(
                self.config_path.read_text(encoding="utf-8"), encoding="utf-8")
        self.config_path.write_text(json.dumps(self.data, ensure_ascii=False, indent=2) + "\n",
                                    encoding="utf-8")
        self.dirty = False
        self.flash("✔ salvo — a roda já está atualizada")
        self.h["on_saved"]()
        return True

    def close(self):
        if self.dirty:
            ans = messagebox.askyesnocancel("Salvar?", "Salvar as alterações antes de fechar?",
                                            parent=self.win)
            if ans is None or (ans and not self.save()):
                return
        self.win.destroy()
