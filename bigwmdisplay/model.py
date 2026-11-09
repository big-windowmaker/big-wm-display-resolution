# SPDX-License-Identifier: GPL-2.0-or-later
"""Modelo dos monitores: modos, saídas, layout, validação e encaixe.

Sem GTK e sem backend: as mesmas regras valem para a interface, a
restauração no login, o vigia de hotplug e os testes.
"""

import copy

# Transformações na ordem do wl_output_transform (0..7). As 4 primeiras são
# rotações (sentido anti-horário); as 4 últimas, as mesmas com reflexo
# horizontal.
TRANSFORMS = ("normal", "90", "180", "270", "flipped", "flipped-90", "flipped-180", "flipped-270")

# Escalas oferecidas no Wayland (o wlmaker aceita 1,0 ou mais; frações valem
# para os clientes com wp-fractional-scale).
WAYLAND_SCALES = (1.0, 1.25, 1.5, 1.75, 2.0, 2.25, 2.5, 3.0)
MAX_SCALE = 3.0

SNAP_PX = 32            # distância de encaixe, em pixels do layout


class Mode:
    __slots__ = ("width", "height", "refresh", "preferred", "id", "interlaced")

    def __init__(self, width, height, refresh=0, preferred=False, mode_id=None, interlaced=False):
        self.width = int(width)
        self.height = int(height)
        self.refresh = int(refresh)         # mHz (0: desconhecida)
        self.preferred = bool(preferred)
        self.id = mode_id                   # id do modo no XRandR
        self.interlaced = bool(interlaced)

    @property
    def size(self):
        return (self.width, self.height)

    @property
    def hz(self):
        return self.refresh / 1000.0

    def matches(self, width, height, refresh=0, tolerance=500):
        if (self.width, self.height) != (width, height):
            return False
        return not refresh or not self.refresh or abs(self.refresh - refresh) <= tolerance

    def key(self):
        return [self.width, self.height, self.refresh]

    def __repr__(self):
        return "Mode(%dx%d@%.3f%s)" % (self.width, self.height, self.hz, "*" if self.preferred else "")


def find_mode(modes, width, height, refresh=0):
    """O modo anunciado de mesmo tamanho com a frequência mais próxima
    (até 0,5 Hz); refresh 0 escolhe a maior. None se não existe."""
    best = None
    for m in modes:
        if (m.width, m.height) != (width, height) or m.interlaced:
            continue
        if not refresh:
            if best is None or m.refresh > best.refresh:
                best = m
            continue
        d = abs(m.refresh - refresh)
        if d <= 500 and (best is None or d < abs(best.refresh - refresh)):
            best = m
    return best


class Output:
    """Um monitor conectado e o que se quer dele."""

    def __init__(self, name, make="", model="", serial="", modes=None):
        self.name = name                    # conector (DP-1, HDMI-A-1...)
        self.make = make or ""
        self.model = model or ""
        self.serial = serial or ""
        self.description = ""
        self.physical = (0, 0)              # mm
        self.edid = None                    # edid.Edid ou None
        self.modes = list(modes or [])
        self.enabled = True
        self.mode = None                    # Mode atual/desejado
        self.x = 0
        self.y = 0
        self.transform = 0
        self.scale = 1.0
        self.primary = False
        self.mirror_of = None               # nome do conector de origem
        self.vrr = None                     # None: sem controle
        self.vrr_capable = None             # None: desconhecido
        self.transforms = list(range(8))    # transformações aceitas
        self.extra = {}

    # -- Identidade ---------------------------------------------------------

    def identity(self):
        """Fabricante, modelo e serial (do EDID). O conector só entra quando o
        monitor não informa nada (saídas virtuais)."""
        if self.make or self.model or self.serial:
            return "%s|%s|%s" % (_norm(self.make), _norm(self.model), _norm(self.serial))
        return "connector:" + self.name

    def label(self):
        if self.make or self.model:
            model = self.model if not self.model.startswith("0x") else ""
            text = " ".join(p for p in (self.make, model) if p)
            return text or self.name
        return self.description or self.name

    # -- Geometria ----------------------------------------------------------

    def native_mode(self):
        for m in self.modes:
            if m.preferred:
                return m
        if self.edid is not None and self.edid.native:
            w, h, r = self.edid.native
            m = find_mode(self.modes, w, h, r)
            if m:
                return m
        if self.modes:
            return max(self.modes, key=lambda m: (m.width * m.height, m.refresh))
        return self.mode

    def pixel_size(self):
        """Tamanho em pixels do framebuffer, já girado."""
        if self.mode is None:
            return (0, 0)
        w, h = self.mode.width, self.mode.height
        if self.transform % 2:
            w, h = h, w
        return (w, h)

    def logical_size(self):
        w, h = self.pixel_size()
        s = self.scale if self.scale and self.scale > 0 else 1.0
        return (int(round(w / s)), int(round(h / s)))

    def rect(self):
        w, h = self.logical_size()
        return (self.x, self.y, w, h)

    def copy(self):
        return copy.copy(self)


def _norm(text):
    return " ".join((text or "").split()).casefold()


class Layout:
    """Os monitores conectados de um backend, com as capacidades dele."""

    def __init__(self, backend, outputs, caps=None):
        self.backend = backend              # "x11", "wayland", "fake"
        self.outputs = list(outputs)
        self.caps = dict(caps or {})
        # Valores padrão das capacidades.
        self.caps.setdefault("scale", backend != "x11")
        self.caps.setdefault("primary", backend == "x11")
        self.caps.setdefault("mirror", True)
        self.caps.setdefault("max_size", (32767, 32767))

    def get(self, name):
        for o in self.outputs:
            if o.name == name:
                return o
        return None

    def enabled(self):
        return [o for o in self.outputs if o.enabled and o.mode is not None]

    def setkey(self):
        return set_key(self.outputs)

    def copy(self):
        new = Layout(self.backend, [o.copy() for o in self.outputs], self.caps)
        return new

    def primary(self):
        for o in self.enabled():
            if o.primary:
                return o
        return None


def identities(outputs):
    """Identidade de cada saída; monitores iguais sem serial (mesmo fabricante
    e modelo) se distinguem pelo conector."""
    base = {o.name: o.identity() for o in outputs}
    count = {}
    for v in base.values():
        count[v] = count.get(v, 0) + 1
    return {name: (v if count[v] == 1 else "%s@%s" % (v, name)) for name, v in base.items()}


def set_key(outputs):
    return "\n".join(sorted(identities(outputs).values()))


# -- Geometria ----------------------------------------------------------------

def overlaps(a, b):
    ax, ay, aw, ah = a
    bx, by, bw, bh = b
    return ax < bx + bw and bx < ax + aw and ay < by + bh and by < ay + ah


def touches(a, b):
    """As áreas encostam (lado com lado, com algum trecho em comum)."""
    ax, ay, aw, ah = a
    bx, by, bw, bh = b
    if ax + aw == bx or bx + bw == ax:
        return ay < by + bh and by < ay + ah
    if ay + ah == by or by + bh == ay:
        return ax < bx + bw and bx < ax + aw
    return False


def snap(rect, others, threshold=SNAP_PX):
    """Encaixe ao arrastar: bordas encostadas e alinhadas com os outros
    monitores, quando estão a até `threshold` pixels."""
    x, y, w, h = rect
    best_x, best_y = (threshold + 1, x), (threshold + 1, y)
    for ox, oy, ow, oh in others:
        for cand in (ox - w, ox + ow, ox, ox + ow - w):
            d = abs(cand - x)
            if d < best_x[0]:
                best_x = (d, cand)
        for cand in (oy - h, oy + oh, oy, oy + oh - h):
            d = abs(cand - y)
            if d < best_y[0]:
                best_y = (d, cand)
    return (best_x[1], best_y[1])


def attach(rect, others):
    """Posição mais próxima de `rect` em que ele encosta num dos outros sem
    sobrepor nenhum (o que vale ao soltar o monitor)."""
    x, y, w, h = rect
    if not others:
        return (x, y)
    if any(touches(rect, o) for o in others) and not any(overlaps(rect, o) for o in others):
        return (x, y)
    best = None
    for ox, oy, ow, oh in others:
        cands = []
        # à esquerda/direita: y limitado a manter um trecho em comum
        cy = min(max(y, oy - h + 1), oy + oh - 1)
        cands += [(ox - w, cy), (ox + ow, cy)]
        cx = min(max(x, ox - w + 1), ox + ow - 1)
        cands += [(cx, oy - h), (cx, oy + oh)]
        for c in cands:
            r = (c[0], c[1], w, h)
            if any(overlaps(r, o) for o in others):
                continue
            d = (c[0] - x) ** 2 + (c[1] - y) ** 2
            if best is None or d < best[0]:
                best = (d, c)
    return best[1] if best else (x, y)


def normalize(layout):
    """Desloca tudo para o canto superior esquerdo ficar em (0, 0)."""
    act = [o for o in layout.enabled() if not o.mirror_of]
    if not act:
        return
    mx = min(o.x for o in act)
    my = min(o.y for o in act)
    for o in layout.outputs:
        o.x -= mx
        o.y -= my
    sync_mirrors(layout)


def sync_mirrors(layout):
    for o in layout.outputs:
        if o.mirror_of:
            src = layout.get(o.mirror_of)
            if src is not None:
                o.x, o.y = src.x, src.y


def bounding_box(layout):
    act = layout.enabled()
    if not act:
        return (0, 0, 0, 0)
    x0 = min(o.x for o in act)
    y0 = min(o.y for o in act)
    x1 = max(o.x + o.logical_size()[0] for o in act)
    y1 = max(o.y + o.logical_size()[1] for o in act)
    return (x0, y0, x1 - x0, y1 - y0)


def arrange_row(layout, order=None):
    """Lado a lado, da esquerda para a direita, alinhados no topo."""
    x = 0
    outs = order or sorted(layout.enabled(), key=lambda o: (o.x, o.y, o.name))
    for o in outs:
        if o.mirror_of:
            continue
        o.x, o.y = x, 0
        x += o.logical_size()[0]
    sync_mirrors(layout)


def default_layout(layout):
    """O padrão: todos ligados no modo nativo, escala 1, lado a lado na
    ordem dos conectores, o primeiro como principal."""
    new = layout.copy()
    for o in new.outputs:
        o.enabled = True
        o.mode = o.native_mode()
        o.transform = 0
        o.scale = 1.0
        o.mirror_of = None
        o.primary = False
        if o.vrr is not None:
            o.vrr = False
    outs = sorted((o for o in new.outputs if o.mode is not None), key=lambda o: _connector_order(o.name))
    for o in new.outputs:
        if o.mode is None:
            o.enabled = False
    arrange_row(new, outs)
    if outs and new.caps.get("primary"):
        outs[0].primary = True
    return new


def _connector_order(name):
    # eDP/LVDS (tela do notebook) primeiro, depois a ordem natural.
    internal = 0 if name.split("-")[0].lower() in ("edp", "lvds", "dsi") else 1
    parts = []
    num = ""
    for ch in name:
        if ch.isdigit():
            num += ch
        else:
            if num:
                parts.append(int(num))
                num = ""
            parts.append(ch)
    if num:
        parts.append(int(num))
    return (internal, [(0, p) if isinstance(p, int) else (1, p) for p in parts])


# -- Validação ----------------------------------------------------------------

def validate(layout):
    """Lista de problemas (texto já traduzível pelo chamador: tuplas
    (código, dados)). Vazia = pode aplicar."""
    errors = []
    act = layout.enabled()
    if not act:
        errors.append(("no-output", {}))
        return errors
    for o in layout.outputs:
        if not o.enabled:
            continue
        if o.mode is None:
            errors.append(("no-mode", {"name": o.name}))
            continue
        if o.modes and not any(m.matches(o.mode.width, o.mode.height, o.mode.refresh) for m in o.modes):
            errors.append(("bad-mode", {"name": o.name, "mode": "%dx%d" % o.mode.size}))
        if o.transform not in o.transforms:
            errors.append(("bad-transform", {"name": o.name}))
        if not layout.caps.get("scale"):
            if abs(o.scale - 1.0) > 1e-6:
                errors.append(("no-scale", {"name": o.name}))
        elif not (1.0 <= o.scale <= MAX_SCALE):
            errors.append(("bad-scale", {"name": o.name}))
        if o.mirror_of:
            src = layout.get(o.mirror_of)
            if src is None or not src.enabled or src.mirror_of or src is o:
                errors.append(("bad-mirror", {"name": o.name}))
            elif src.logical_size() != o.logical_size():
                errors.append(("mirror-size", {"name": o.name, "source": src.name}))
    if errors:
        return errors
    main = [o for o in act if not o.mirror_of]
    rects = [(o, o.rect()) for o in main]
    for i, (a, ra) in enumerate(rects):
        for b, rb in rects[i + 1:]:
            if overlaps(ra, rb):
                errors.append(("overlap", {"a": a.name, "b": b.name}))
    if not errors and len(rects) > 1 and not _connected([r for _, r in rects]):
        errors.append(("gap", {}))
    bx, by, bw, bh = bounding_box(layout)
    mw, mh = layout.caps.get("max_size", (32767, 32767))
    if bx < 0 or by < 0:
        errors.append(("negative", {}))
    if bw > mw or bh > mh:
        errors.append(("too-big", {"w": bw, "h": bh, "mw": mw, "mh": mh}))
    if layout.caps.get("primary") and sum(1 for o in main if o.primary) > 1:
        errors.append(("primary", {}))
    return errors


def _connected(rects):
    seen = {0}
    todo = [0]
    while todo:
        i = todo.pop()
        for j, r in enumerate(rects):
            if j not in seen and touches(rects[i], r):
                seen.add(j)
                todo.append(j)
    return len(seen) == len(rects)


def same_config(a, b):
    """As duas configurações dão o mesmo resultado na tela."""
    for oa in a.outputs:
        ob = b.get(oa.name)
        if ob is None:
            return False
        if oa.enabled != ob.enabled:
            return False
        if not oa.enabled:
            continue
        if oa.mode is None or ob.mode is None or not oa.mode.matches(ob.mode.width, ob.mode.height, ob.mode.refresh):
            return False
        if (oa.x, oa.y, oa.transform) != (ob.x, ob.y, ob.transform):
            return False
        if abs(oa.scale - ob.scale) > 1e-3:
            return False
        if a.caps.get("primary") and oa.primary != ob.primary:
            return False
        if (oa.mirror_of or None) != (ob.mirror_of or None):
            return False
        if oa.vrr is not None and ob.vrr is not None and oa.vrr != ob.vrr:
            return False
    return len(a.outputs) == len(b.outputs)
