# SPDX-License-Identifier: GPL-2.0-or-later
"""Perfis gravados em ~/.config/big-wm/display-resolution/.

  profiles.json       os perfis (JSON legível, com "version"); gravação
                      atômica: arquivo temporário, fsync, rename
  profiles.json.bak   a última versão boa (lida e validada) antes da
                      gravação atual; usada se profiles.json quebrar

Um perfil guarda o conjunto de monitores pela identidade do EDID
(fabricante, modelo, serial), nunca só pelo conector: o mesmo layout vale
quando o cabo muda de porta. Cada sessão (x11, wayland) tem o seu perfil
automático por conjunto, gravado quando o usuário mantém uma configuração.
"""

import json
import os
import time
import uuid

from . import model

FORMAT = "big-wm-display-resolution"
VERSION = 1


def config_dir(env=None):
    env = os.environ if env is None else env
    home = env.get("XDG_CONFIG_HOME") or os.path.join(env.get("HOME") or os.path.expanduser("~"), ".config")
    return os.path.join(home, "big-wm", "display-resolution")


def runtime_dir(env=None):
    env = os.environ if env is None else env
    base = env.get("XDG_RUNTIME_DIR") or "/tmp"
    return os.path.join(base, "big-wm-display-resolution-%d" % os.getuid())


# -- Conversão layout <-> perfil -----------------------------------------------

def output_entry(o, ids):
    return {
        "identity": {"make": o.make, "model": o.model, "serial": o.serial},
        "key": ids[o.name],
        "connector": o.name,
        "enabled": bool(o.enabled),
        "mode": None if o.mode is None else {"width": o.mode.width, "height": o.mode.height,
                                             "refresh_mhz": o.mode.refresh},
        "position": [int(o.x), int(o.y)],
        "scale": round(float(o.scale), 4),
        "transform": model.TRANSFORMS[o.transform],
        "primary": bool(o.primary),
        "mirror_of": ids.get(o.mirror_of) if o.mirror_of else None,
        "vrr": o.vrr,
    }


def layout_to_profile(layout, name, kind="custom", session=None):
    ids = model.identities(layout.outputs)
    now = int(time.time())
    return {
        "id": uuid.uuid4().hex,
        "name": name,
        "kind": kind,
        "session": session or layout.backend,
        "setkey": model.set_key(layout.outputs),
        "outputs": [output_entry(o, ids) for o in layout.outputs],
        "created": now,
        "updated": now,
    }


def profile_matches(profile, layout):
    return profile.get("setkey") == model.set_key(layout.outputs)


def apply_profile(profile, layout):
    """O layout atual com os valores do perfil (pela identidade de cada
    monitor). None se o conjunto de monitores não é o do perfil."""
    if not profile_matches(profile, layout):
        return None
    new = layout.copy()
    ids = model.identities(new.outputs)
    by_key = {v: k for k, v in ids.items()}
    for entry in profile.get("outputs", []):
        name = by_key.get(entry.get("key"))
        o = new.get(name) if name else None
        if o is None:
            return None
        o.enabled = bool(entry.get("enabled", True))
        mode = entry.get("mode")
        if mode:
            w, h, r = int(mode["width"]), int(mode["height"]), int(mode.get("refresh_mhz") or 0)
            m = model.find_mode(o.modes, w, h, r) if o.modes else model.Mode(w, h, r)
            if m is None:
                # O monitor não anuncia mais esse modo: o perfil não vale.
                return None
            o.mode = m
        elif o.enabled:
            o.mode = o.native_mode()
        pos = entry.get("position") or [0, 0]
        o.x, o.y = int(pos[0]), int(pos[1])
        o.scale = float(entry.get("scale") or 1.0)
        if not new.caps.get("scale"):
            o.scale = 1.0
        t = entry.get("transform", "normal")
        o.transform = model.TRANSFORMS.index(t) if t in model.TRANSFORMS else 0
        o.primary = bool(entry.get("primary")) and bool(new.caps.get("primary"))
        mk = entry.get("mirror_of")
        o.mirror_of = by_key.get(mk) if mk else None
        vrr = entry.get("vrr")
        if o.vrr is not None and vrr is not None and o.vrr_capable is not False:
            o.vrr = bool(vrr)
    model.sync_mirrors(new)
    return new


# -- Arquivo --------------------------------------------------------------------

class Store:
    def __init__(self, directory=None):
        self.dir = directory or config_dir()
        self.path = os.path.join(self.dir, "profiles.json")
        self.backup = self.path + ".bak"
        self.data = self._empty()
        self.loaded_from = None
        self.load()

    @staticmethod
    def _empty():
        return {"format": FORMAT, "version": VERSION, "profiles": [], "last_applied": {}, "migrated": {}}

    @staticmethod
    def _valid(data):
        if not isinstance(data, dict) or data.get("format") != FORMAT:
            return False
        if not isinstance(data.get("version"), int) or data["version"] > VERSION:
            return False
        profiles = data.get("profiles")
        if not isinstance(profiles, list):
            return False
        for p in profiles:
            if not isinstance(p, dict) or not isinstance(p.get("outputs"), list):
                return False
            if not isinstance(p.get("id"), str) or not isinstance(p.get("setkey"), str):
                return False
        return True

    def load(self):
        for path in (self.path, self.backup):
            try:
                with open(path, encoding="utf-8") as f:
                    data = json.load(f)
            except (OSError, ValueError):
                continue
            if self._valid(data):
                data.setdefault("last_applied", {})
                data.setdefault("migrated", {})
                self.data = data
                self.loaded_from = path
                return True
        self.data = self._empty()
        self.loaded_from = None
        return False

    def save(self):
        os.makedirs(self.dir, mode=0o700, exist_ok=True)
        # A versão atual, se for boa, vira a cópia de segurança.
        try:
            with open(self.path, encoding="utf-8") as f:
                current = json.load(f)
            if self._valid(current):
                _atomic_write(self.backup, json.dumps(current, indent=2, ensure_ascii=False) + "\n")
        except (OSError, ValueError):
            pass
        _atomic_write(self.path, json.dumps(self.data, indent=2, ensure_ascii=False) + "\n")

    # -- Perfis ----------------------------------------------------------------

    @property
    def profiles(self):
        return self.data["profiles"]

    def get(self, pid):
        for p in self.profiles:
            if p["id"] == pid:
                return p
        return None

    def matching(self, layout, session=None):
        key = model.set_key(layout.outputs)
        return [p for p in self.profiles if p.get("setkey") == key
                and (session is None or p.get("session") == session)]

    def auto_profile(self, layout, session):
        for p in self.matching(layout, session):
            if p.get("kind") == "auto":
                return p
        return None

    def best_for(self, layout, session):
        """O perfil a aplicar para este conjunto, nesta sessão: o último
        aplicado, senão o automático, senão o personalizado mais recente."""
        cands = self.matching(layout, session)
        if not cands:
            return None
        last = self.data["last_applied"].get(session + "\n" + model.set_key(layout.outputs))
        for p in cands:
            if p["id"] == last:
                return p
        for p in cands:
            if p.get("kind") == "auto":
                return p
        return max(cands, key=lambda p: p.get("updated", 0))

    def remember(self, layout, name=None, session=None):
        """Grava o layout como o perfil automático do conjunto."""
        session = session or layout.backend
        prof = layout_to_profile(layout, name or "", kind="auto", session=session)
        old = self.auto_profile(layout, session)
        if old is not None:
            prof["id"] = old["id"]
            prof["created"] = old.get("created", prof["created"])
            # O nome de uma migração (ARandR, OutputState) não vale mais.
            prof["name"] = prof["name"] or ""

            self.profiles[self.profiles.index(old)] = prof
        else:
            self.profiles.append(prof)
        self.mark_applied(layout, prof, session)
        return prof

    def add(self, layout, name, session=None):
        prof = layout_to_profile(layout, name, kind="custom", session=session)
        self.profiles.append(prof)
        return prof

    def update(self, pid, layout):
        p = self.get(pid)
        if p is None:
            return None
        new = layout_to_profile(layout, p["name"], kind=p.get("kind", "custom"), session=p.get("session"))
        new["id"], new["created"] = p["id"], p.get("created", new["created"])
        self.profiles[self.profiles.index(p)] = new
        return new

    def rename(self, pid, name):
        p = self.get(pid)
        if p is None or not name.strip():
            return False
        p["name"] = name.strip()
        p["updated"] = int(time.time())
        return True

    def delete(self, pid):
        p = self.get(pid)
        if p is None:
            return False
        self.profiles.remove(p)
        for k, v in list(self.data["last_applied"].items()):
            if v == pid:
                del self.data["last_applied"][k]
        return True

    def mark_applied(self, layout, profile, session=None):
        session = session or layout.backend
        self.data["last_applied"][session + "\n" + model.set_key(layout.outputs)] = profile["id"]


def _atomic_write(path, text):
    d = os.path.dirname(path)
    tmp = os.path.join(d, ".%s.%d.tmp" % (os.path.basename(path), os.getpid()))
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(text)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise
    try:
        dfd = os.open(d, os.O_RDONLY)
        try:
            os.fsync(dfd)
        finally:
            os.close(dfd)
    except OSError:
        pass
