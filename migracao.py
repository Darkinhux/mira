"""
Atualiza o config.json do usuário com as novidades de cada versão,
sem apagar nem mudar o que ele personalizou.

* Opções novas (chaves que não existem no arquivo) são acrescentadas.
* Itens novos da roda principal e perfis novos são oferecidos UMA vez:
  os ids ficam guardados em "_seen_items" / "_seen_profiles". Se o usuário
  apagar um item depois, ele não volta.
* Configs antigos (sem essas listas) são reconhecidos pelos nomes dos itens.
"""
from __future__ import annotations

import copy

MAX_ROOT = 12


def _item_key(item: dict) -> str:
    return str(item.get("id") or item.get("name", "")).lower()


def _names(items: list) -> set[str]:
    out = set()
    for it in items:
        if isinstance(it, dict):
            out.add(str(it.get("name", "")).lower())
            if it.get("id"):
                out.add(str(it["id"]).lower())
    return out


def migrate(user: dict, defaults: dict) -> tuple[dict, list[str], list[str]]:
    """Devolve (config novo, novidades adicionadas, avisos)."""
    cfg = copy.deepcopy(user)
    added: list[str] = []
    notes: list[str] = []

    # 1) opções novas
    for key, value in defaults.items():
        if key not in cfg and key not in ("items", "profiles") and not key.startswith("_"):
            cfg[key] = copy.deepcopy(value)

    # 2) itens novos na roda principal
    items = cfg.setdefault("items", [])
    seen = cfg.get("_seen_items")
    if seen is None:  # config antigo: o que ele já tem conta como "visto"
        present = _names(items)
        seen = [_item_key(d) for d in defaults.get("items", [])
                if _item_key(d) in present or str(d.get("name", "")).lower() in present]
    seen = list(dict.fromkeys(seen))
    default_items = defaults.get("items", [])
    for idx, d in enumerate(default_items):
        key = _item_key(d)
        if key in seen:
            continue
        seen.append(key)
        if key in _names(items) or str(d.get("name", "")).lower() in _names(items):
            continue
        if len(items) >= MAX_ROOT:
            notes.append(f"sem espaço na roda para \"{d['name']}\" (máximo {MAX_ROOT})")
            continue
        # coloca logo depois do item que vem antes dele no padrão, se existir
        # (ou antes do que vem depois dele); se nenhum existir, vai pro fim
        names = [str(i.get("name", "")).lower() for i in items]
        pos = len(items)
        prev = next((str(p.get("name", "")).lower() for p in reversed(default_items[:idx])
                     if str(p.get("name", "")).lower() in names), None)
        if prev is not None:
            pos = names.index(prev) + 1
        else:
            nxt = next((str(n.get("name", "")).lower() for n in default_items[idx + 1:]
                        if str(n.get("name", "")).lower() in names), None)
            if nxt is not None:
                pos = names.index(nxt)
        items.insert(pos, copy.deepcopy(d))
        added.append(d["name"])
    cfg["_seen_items"] = seen

    # 3) perfis novos
    profiles = cfg.setdefault("profiles", [])
    seen_p = cfg.get("_seen_profiles")
    if seen_p is None:
        seen_p = [str(p.get("name", "")).lower() for p in profiles if isinstance(p, dict)]
    for d in defaults.get("profiles", []):
        key = str(d.get("name", "")).lower()
        if key in seen_p:
            continue
        seen_p.append(key)
        if key not in {str(p.get("name", "")).lower() for p in profiles if isinstance(p, dict)}:
            profiles.append(copy.deepcopy(d))
            added.append(f"perfil {d['name']}")
    cfg["_seen_profiles"] = seen_p
    return cfg, added, notes
