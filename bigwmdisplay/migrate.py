# SPDX-License-Identifier: GPL-2.0-or-later
"""Migração do que já existia, sem executar nada:

  ~/.screenlayout/*.sh           scripts do ARandR (o big-wm-monitors os
                                 aplicava no login do X11); o escolhido em
                                 ~/.config/big-wm/monitors vale primeiro
  ~/.config/wlmaker/OutputState.plist
                                 o estado salvo pelo wlmaker (Salvar estado
                                 dos monitores)

Os scripts são lidos como texto: só linhas "xrandr ..." com opções
conhecidas; qualquer outra coisa (variáveis, pipes, outros comandos) e o
script é recusado. Os conectores do script viram identidades (EDID) pelos
monitores conectados agora, e só quando todos os que ele liga estão
conectados; os outros esperam o conjunto aparecer.
"""

import os
import re
import shlex

from . import model, store

# Opções do xrandr que o ARandR grava, e quantos argumentos cada uma leva.
_XRANDR_OPTS = {"--output": 1, "--mode": 1, "--pos": 1, "--rotate": 1, "--reflect": 1, "--rate": 1,
                "--refresh": 1, "--primary": 0, "--off": 0, "--auto": 0, "--preferred": 0,
                "--same-as": 1, "--left-of": 1, "--right-of": 1, "--above": 1, "--below": 1,
                "--noprimary": 0, "--scale": 1, "--dpi": 1, "--fb": 1, "--transform": 1}


class ScriptError(ValueError):
    pass


def parse_arandr(text):
    """Script do ARandR -> {conector: {opções}}. ScriptError se o script
    tiver qualquer coisa além de chamadas ao xrandr."""
    outputs = {}
    joined = re.sub(r"\\\n", " ", text)
    for raw in joined.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        try:
            words = shlex.split(line, comments=True)
        except ValueError as e:
            raise ScriptError(str(e)) from None
        if not words:
            continue
        if os.path.basename(words[0]) != "xrandr":
            raise ScriptError("comando não permitido: %s" % words[0])
        if any(c in line for c in ";|&`$<>(){}"):
            raise ScriptError("construção de shell não permitida")
        cur = None
        i = 1
        while i < len(words):
            opt = words[i]
            if opt not in _XRANDR_OPTS:
                raise ScriptError("opção desconhecida: %s" % opt)
            n = _XRANDR_OPTS[opt]
            args = words[i + 1:i + 1 + n]
            if len(args) < n:
                raise ScriptError("falta o valor de %s" % opt)
            i += 1 + n
            if opt == "--output":
                cur = outputs.setdefault(args[0], {})
                continue
            if opt in ("--noprimary", "--fb", "--dpi"):
                continue
            if cur is None:
                raise ScriptError("%s antes de --output" % opt)
            cur[opt[2:]] = args[0] if n else True
    return outputs


def enabled_in_script(outs):
    return [name for name, o in outs.items() if not o.get("off") and
            (o.get("mode") or o.get("auto") or o.get("preferred"))]


def layout_from_arandr(outs, layout):
    """Aplica o script ao layout X11 atual (pelos conectores). None se o
    script liga uma saída que não está conectada, ou usa um modo que o
    monitor não anuncia."""
    new = layout.copy()
    for name in enabled_in_script(outs):
        if new.get(name) is None:
            return None
    for o in new.outputs:
        spec = outs.get(o.name)
        if spec is None or spec.get("off"):
            o.enabled = False
            continue
        o.enabled = True
        if spec.get("mode"):
            m = re.fullmatch(r"(\d+)x(\d+)i?", spec["mode"])
            if not m:
                return None
            rate = spec.get("rate") or spec.get("refresh")
            refresh = int(round(float(rate) * 1000)) if rate else 0
            mode = model.find_mode(o.modes, int(m.group(1)), int(m.group(2)), refresh)
            if mode is None:
                return None
            o.mode = mode
        else:
            o.mode = o.native_mode()
        if spec.get("pos"):
            p = re.fullmatch(r"(-?\d+)x(-?\d+)", spec["pos"])
            if not p:
                return None
            o.x, o.y = int(p.group(1)), int(p.group(2))
        rot = spec.get("rotate", "normal")
        refl = spec.get("reflect", "normal")
        r = ("normal", "left", "inverted", "right").index(rot) if rot in ("normal", "left", "inverted", "right") else 0
        o.transform = {"normal": r, "x": r + 4, "y": (r + 2) % 4 + 4, "xy": (r + 2) % 4}.get(refl, r)
        o.primary = bool(spec.get("primary"))
        o.mirror_of = spec.get("same-as")
        o.scale = 1.0
    # Posições relativas (--right-of etc.), que o ARandR não grava mas um
    # script feito à mão pode ter: em ordem, a partir das já resolvidas.
    for _ in range(len(new.outputs)):
        for o in new.outputs:
            spec = outs.get(o.name) or {}
            for rel in ("right-of", "left-of", "above", "below"):
                ref = new.get(spec.get(rel)) if spec.get(rel) else None
                if ref is None:
                    continue
                w, h = o.logical_size()
                rw, rh = ref.logical_size()
                o.x, o.y = {"right-of": (ref.x + rw, ref.y), "left-of": (ref.x - w, ref.y),
                            "above": (ref.x, ref.y - h), "below": (ref.x, ref.y + rh)}[rel]
    model.normalize(new)
    if model.validate(new):
        return None
    return new


def arandr_scripts(home):
    d = os.path.join(home, ".screenlayout")
    try:
        names = sorted(n for n in os.listdir(d) if n.endswith(".sh"))
    except OSError:
        return []
    return [os.path.join(d, n) for n in names]


def chosen_script(config_home):
    try:
        with open(os.path.join(config_home, "big-wm", "monitors"), encoding="utf-8") as f:
            path = f.readline().strip()
    except OSError:
        return None
    return path if path and os.path.isfile(path) else None


def migrate_arandr(st, layout, home, config_home, log=print):
    """Scripts do ARandR -> perfis personalizados "ARandR: nome". O escolhido
    (ou o mais novo) vira também o automático do conjunto, se ainda não há
    um: o login continua com o layout que o big-wm-monitors aplicava.
    Devolve quantos perfis foram criados."""
    if layout.backend != "x11":
        return 0
    done = st.data["migrated"].setdefault("screenlayout", {})
    scripts = arandr_scripts(home)
    if not scripts:
        return 0
    chosen = chosen_script(config_home)
    usable = []
    for path in scripts:
        try:
            mtime = int(os.path.getmtime(path))
        except OSError:
            continue
        if done.get(path) == mtime:
            continue
        try:
            with open(path, encoding="utf-8", errors="replace") as f:
                outs = parse_arandr(f.read())
        except (OSError, ScriptError) as e:
            log("ARandR: %s recusado: %s" % (path, e))
            done[path] = mtime
            continue
        new = layout_from_arandr(outs, layout)
        if new is None:
            # Outro conjunto de monitores: tenta de novo quando ele estiver conectado.
            continue
        usable.append((path, mtime, new))
    if not usable:
        return 0
    # O automático do conjunto: o escolhido no big-wm-monitors, senão o mais novo.
    paths = [u[0] for u in usable]
    preferred = chosen if chosen in paths else max(usable, key=lambda u: u[1])[0]
    for path, mtime, new in usable:
        name = "ARandR: " + os.path.basename(path)[:-3]
        prof = store.layout_to_profile(new, name, kind="custom", session="x11")
        for p in list(st.profiles):
            if p.get("name") == name and p.get("setkey") == prof["setkey"] and p.get("kind") == "custom":
                st.profiles.remove(p)
        st.profiles.append(prof)
        if path == preferred and st.auto_profile(new, "x11") is None:
            auto = st.remember(new, session="x11")
            auto["name"] = name
            auto["migrated_from"] = path
        done[path] = mtime
        log("ARandR: %s importado como perfil" % path)
    return len(usable)


# -- OutputState.plist do wlmaker ----------------------------------------------

def parse_plist(text):
    """Leitor do formato de texto do GNUstep (o que o wlmaker grava): dict,
    array e strings."""
    pos = 0
    n = len(text)

    def skip():
        nonlocal pos
        while pos < n:
            if text[pos].isspace():
                pos += 1
            elif text.startswith("//", pos):
                pos = text.find("\n", pos)
                pos = n if pos < 0 else pos
            elif text.startswith("/*", pos):
                end = text.find("*/", pos + 2)
                pos = n if end < 0 else end + 2
            else:
                break

    def value():
        nonlocal pos
        skip()
        if pos >= n:
            raise ValueError("fim inesperado")
        c = text[pos]
        if c == "{":
            pos += 1
            d = {}
            while True:
                skip()
                if text[pos] == "}":
                    pos += 1
                    return d
                k = value()
                skip()
                if text[pos] != "=":
                    raise ValueError("esperava = em %d" % pos)
                pos += 1
                d[k] = value()
                skip()
                if text[pos] == ";":
                    pos += 1
        if c == "(":
            pos += 1
            arr = []
            while True:
                skip()
                if text[pos] == ")":
                    pos += 1
                    return arr
                arr.append(value())
                skip()
                if text[pos] == ",":
                    pos += 1
        if c == '"':
            pos += 1
            out = []
            while text[pos] != '"':
                if text[pos] == "\\":
                    pos += 1
                    out.append({"n": "\n", "t": "\t"}.get(text[pos], text[pos]))
                else:
                    out.append(text[pos])
                pos += 1
            pos += 1
            return "".join(out)
        m = re.compile(r"[A-Za-z0-9_.$:/+\-]+").match(text, pos)
        if not m:
            raise ValueError("valor inválido em %d" % pos)
        pos = m.end()
        return m.group(0)

    return value()


_WLM_TRANSFORMS = {"Normal": 0, "Rotate90": 1, "Rotate180": 2, "Rotate270": 3, "Flip": 4,
                   "FlipAndRotate90": 5, "FlipAndRotate180": 6, "FlipAndRotate270": 7}


def layout_from_output_state(entries, layout):
    """Entradas do OutputState.plist -> layout (pela identidade de cada
    monitor). None se falta a entrada de algum monitor conectado."""
    new = layout.copy()
    for o in new.outputs:
        found = None
        for e in entries:
            if not isinstance(e, dict):
                continue
            ident = (e.get("Manufacturer", ""), e.get("Model", ""), e.get("Serial", ""))
            if any(ident) and model.Output("", *ident).identity() == o.identity():
                found = e
                break
            if not any(ident) and e.get("Name") == o.name:
                found = e
                break
        if found is None:
            return None
        o.enabled = str(found.get("Enabled", "True")).lower() in ("true", "yes", "1")
        m = re.fullmatch(r"(\d+)x(\d+)(?:@([\d.]+))?", str(found.get("Mode", "")))
        if m:
            refresh = int(round(float(m.group(3)) * 1000)) if m.group(3) else 0
            mode = model.find_mode(o.modes, int(m.group(1)), int(m.group(2)), refresh) if o.modes else None
            if mode is None and o.enabled:
                return None
            o.mode = mode or o.mode
        p = re.fullmatch(r"(-?\d+),(-?\d+)", str(found.get("Position", "")))
        if p:
            o.x, o.y = int(p.group(1)), int(p.group(2))
        try:
            o.scale = max(1.0, float(found.get("Scale", 1.0)))
        except ValueError:
            o.scale = 1.0
        o.transform = _WLM_TRANSFORMS.get(found.get("Transformation", "Normal"), 0)
    if model.validate(new):
        return None
    return new


def migrate_output_state(st, layout, config_home, log=print):
    """O OutputState.plist do wlmaker vira o perfil automático do conjunto
    no Wayland, se ainda não há um. Devolve True se importou."""
    if layout.backend != "wayland" or st.auto_profile(layout, "wayland") is not None:
        return False
    path = os.path.join(config_home, "wlmaker", "OutputState.plist")
    try:
        mtime = int(os.path.getmtime(path))
        with open(path, encoding="utf-8", errors="replace") as f:
            data = parse_plist(f.read())
    except (OSError, ValueError, IndexError) as e:
        if os.path.exists(path):
            log("OutputState.plist ilegível: %s" % e)
        return False
    done = st.data["migrated"].setdefault("output_state", {})
    key = model.set_key(layout.outputs)
    if done.get(key) == mtime:
        return False
    entries = data.get("Outputs", []) if isinstance(data, dict) else []
    new = layout_from_output_state(entries, layout)
    done[key] = mtime
    if new is None:
        return False
    auto = st.remember(new, session="wayland")
    auto["name"] = "wlmaker (OutputState.plist)"
    auto["migrated_from"] = path
    log("OutputState.plist importado como perfil automático")
    return True
