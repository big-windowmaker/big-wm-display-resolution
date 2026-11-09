# SPDX-License-Identifier: GPL-2.0-or-later
"""Escolha do backend pela sessão, e o backend de teste (arquivo JSON)."""

import json
import os

from . import backend_wl, model


def session_type(env=None):
    env = os.environ if env is None else env
    if env.get("BIGWM_DISPLAY_FAKE"):
        return env.get("BIGWM_DISPLAY_FAKE_SESSION", "wayland")
    if env.get("WAYLAND_DISPLAY") or env.get("XDG_SESSION_TYPE") == "wayland":
        return "wayland"
    if env.get("DISPLAY"):
        return "x11"
    return None


def get_backend(env=None):
    env = os.environ if env is None else env
    if env.get("BIGWM_DISPLAY_FAKE"):
        return FakeBackend(env["BIGWM_DISPLAY_FAKE"], env.get("BIGWM_DISPLAY_FAKE_SESSION", "wayland"))
    s = session_type(env)
    if s == "wayland":
        return backend_wl.WaylandBackend()
    if s == "x11":
        from . import backend_x11
        return backend_x11.X11Backend()
    raise RuntimeError("nenhuma sessão gráfica (DISPLAY/WAYLAND_DISPLAY)")


class FakeBackend:
    """Monitores descritos num arquivo JSON no formato do wl-dump; aplicar
    grava o arquivo. Para os testes (e para o vigia ser testado sem tela).

    "fail_apply": true faz toda aplicação falhar; "apply_log" guarda cada
    configuração aplicada."""

    def __init__(self, path, session="wayland"):
        self.path = path
        self.name = session

    def _load(self):
        with open(self.path, encoding="utf-8") as f:
            return json.load(f)

    def query(self, probe_vrr=False):
        data = self._load()
        layout = backend_wl.to_layout(data, edid_reader=None)
        layout.backend = self.name
        if self.name == "x11":
            layout.caps.update(scale=False, primary=True)
            for o, h in zip(layout.outputs, data.get("heads", []), strict=False):
                o.primary = bool(h.get("primary"))
        for o in layout.outputs:
            o.vrr_capable = o.vrr is not None
        return layout

    def test(self, layout):
        data = self._load()
        if data.get("fail_test"):
            return False, "failed"
        return True, "succeeded"

    def apply(self, layout):
        data = self._load()
        if data.get("fail_apply"):
            return False, "failed"
        heads = {h["name"]: h for h in data.get("heads", [])}
        for o in layout.outputs:
            h = heads.get(o.name)
            if h is None:
                return False, "monitor %s não está conectado" % o.name
            h["enabled"] = bool(o.enabled)
            if o.enabled and o.mode is not None:
                h["current"] = [o.mode.width, o.mode.height, o.mode.refresh]
                h["x"], h["y"] = o.x, o.y
                h["transform"] = o.transform
                h["scale"] = o.scale
                h["primary"] = bool(o.primary)
                if o.vrr is not None:
                    h["adaptive_sync"] = int(o.vrr)
        data.setdefault("apply_log", []).append(
            [[o.name, o.enabled, o.x, o.y] + (o.mode.key() if o.mode else []) for o in layout.outputs])
        tmp = self.path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=1)
        os.replace(tmp, self.path)
        return True, "succeeded"


def layout_summary(layout):
    """Texto curto do layout (logs e --show)."""
    parts = []
    for o in layout.outputs:
        if not o.enabled or o.mode is None:
            parts.append("%s: desligado" % o.name)
            continue
        extra = ""
        if o.mirror_of:
            extra += " espelhando %s" % o.mirror_of
        if o.transform:
            extra += " %s" % model.TRANSFORMS[o.transform]
        if abs(o.scale - 1) > 1e-3:
            extra += " x%g" % o.scale
        if o.primary:
            extra += " principal"
        parts.append("%s: %dx%d@%.2f em %d,%d%s" % (o.name, o.mode.width, o.mode.height, o.mode.hz,
                                                    o.x, o.y, extra))
    return "; ".join(parts)
