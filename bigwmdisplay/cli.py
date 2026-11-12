# SPDX-License-Identifier: GPL-2.0-or-later
"""Linha de comando: interface, restauração no login, hotplug e vigias.

  big-wm-display-resolution              abre a janela (ou traz a aberta)
  big-wm-display-resolution --restore    login: aplica o perfil do conjunto
                                         de monitores conectado (sem janela)
  big-wm-display-resolution --hotplug    o mesmo, chamado pelo vigia quando
                                         um monitor chega ou sai
  big-wm-display-resolution --watch      vigia de hotplug: troca este
                                         processo pelo big-wm-display-helper
                                         (eventos do XRandR ou do compositor)
  big-wm-display-resolution --show       o que está conectado e o perfil que
                                         valeria
  big-wm-display-resolution --profiles   lista os perfis
  big-wm-display-resolution --apply-profile NOME
                                         aplica um perfil (sem confirmação)
  big-wm-display-resolution --guard ARQ  o vigia da reversão (interno)
"""

import os
import subprocess
import sys
from gettext import gettext as _, ngettext

from . import VERSION, backend as backendmod, guard, migrate, model, store


def usage():
    """A ajuda da linha de comando (traduzida; o docstring acima é para quem
    lê o código). As opções e os comandos não se traduzem."""
    return _("Usage: big-wm-display-resolution [OPTION]\n"
             "\n"
             "Monitors of the X11 (Window Maker) and Wayland (wlmaker) sessions.\n"
             "\n"
             "  (none)                 open the window (or raise the open one)\n"
             "  --restore              at login: apply the profile of the connected set\n"
             "                         of monitors (no window)\n"
             "  --hotplug              the same, run by the watcher when a monitor\n"
             "                         is plugged in or out\n"
             "  --watch                hotplug watcher (replaces this process with\n"
             "                         big-wm-display-helper)\n"
             "  --show                 what is connected and the profile that applies\n"
             "  --profiles             list the profiles\n"
             "  --apply-profile NAME   apply a profile (no confirmation)\n"
             "  --version              show the version\n")


def log(text):
    try:
        subprocess.run(["logger", "-t", "big-wm-display-resolution", "--", text], timeout=5,
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except (OSError, subprocess.SubprocessError):
        pass
    if os.environ.get("BIGWM_DISPLAY_VERBOSE"):
        print(text, file=sys.stderr)


def _homes():
    home = os.environ.get("HOME") or os.path.expanduser("~")
    config_home = os.environ.get("XDG_CONFIG_HOME") or os.path.join(home, ".config")
    return home, config_home


def run_migrations(st, layout):
    home, config_home = _homes()
    changed = migrate.migrate_arandr(st, layout, home, config_home, log=log) > 0
    changed = migrate.migrate_output_state(st, layout, config_home, log=log) or changed
    return changed


def extend_new(layout):
    """Sem perfil para o conjunto (X11): o que está ligado e bem posto fica;
    monitores conectados e apagados (ou sobrepostos a outro, como o X deixa
    um monitor novo) entram à direita, no modo nativo."""
    new = layout.copy()
    kept = []
    pending = []
    for o in sorted(new.outputs, key=lambda o: model._connector_order(o.name)):
        if o.enabled and o.mode is not None and not o.mirror_of and \
                not any(model.overlaps(o.rect(), k.rect()) for k in kept):
            kept.append(o)
        elif o.enabled and o.mirror_of and new.get(o.mirror_of) in kept and \
                o.logical_size() == new.get(o.mirror_of).logical_size():
            continue
        else:
            pending.append(o)
    right = max((o.x + o.logical_size()[0] for o in kept), default=0)
    for o in pending:
        o.mode = o.native_mode() if not o.enabled or o.mode is None else o.mode
        if o.mode is None:
            o.enabled = False
            continue
        o.enabled = True
        o.mirror_of = None
        o.primary = False
        o.x, o.y = right, 0
        right += o.logical_size()[0]
    if new.caps.get("primary") and not new.primary():
        for o in new.enabled():
            o.primary = True
            break
    model.normalize(new)
    return new


def _label(prof):
    return prof.get("name") or ("automático" if prof.get("kind") == "auto" else prof["id"])


def restore(be, st, hotplug=False):
    """Aplica o perfil do conjunto conectado. Devolve um código de saída."""
    if hotplug and guard.lock_active():
        log("hotplug ignorado: há uma configuração esperando confirmação")
        return 0
    try:
        layout = be.query()
    except Exception as e:  # noqa: BLE001
        log("sem o estado dos monitores: %s" % e)
        return 1
    session = be.name
    changed = run_migrations(st, layout)
    prof = st.best_for(layout, session)
    target = None
    why = ""
    if prof is not None:
        target = store.apply_profile(prof, layout)
        why = "perfil \"%s\"" % _label(prof)
        if target is None:
            log("%s não vale mais para estes monitores (modo não anunciado)" % why)
    elif hotplug and session == "x11":
        part = st.subset_target(layout, session)
        if part is not None:
            target, src = part
            why = "parte do perfil \"%s\"" % _label(src)
        else:
            target = extend_new(layout)
            why = "monitores novos à direita"
    if target is not None:
        errors = model.validate(target)
        if errors:
            log("%s recusado: %s" % (why, errors))
            target = None
    if target is not None and not model.same_config(target, layout):
        ok, msg = be.apply(target)
        if ok:
            log("aplicado (%s): %s" % (why, backendmod.layout_summary(target)))
            if prof is not None:
                st.mark_applied(target, prof, session)
                changed = True
        else:
            log("falhou ao aplicar %s: %s" % (why, msg))
            if changed:
                st.save()
            return 1
    if changed:
        st.save()
    return 0


def watch():
    session = backendmod.session_type()
    if session is None:
        return 0
    helper = os.environ.get("BIGWM_DISPLAY_HELPER") or backendmod.backend_wl.helper_path()
    mode = "wl-watch" if session == "wayland" else "x11-watch"
    cmd = [helper, mode, "--run-now", "--", sys.executable, "-I", guard.launcher(), "--hotplug"]
    os.execv(helper, cmd)
    return 1


def show(be, st):
    layout = be.query()
    print(_("session: %s") % be.name)
    ids = model.identities(layout.outputs)
    for o in layout.outputs:
        print("%s\t%s\t%s" % (o.name, ids[o.name], backendmod.layout_summary(model.Layout(layout.backend, [o]))))
    prof = st.best_for(layout, be.name)
    if prof is None:
        print(_("profile: none for this set of monitors"))
    else:
        auto = _("automatic") if prof.get("kind") == "auto" else prof["kind"]
        print(_("profile: %s") % (prof.get("name") or auto))
    return 0


def list_profiles(st):
    for p in st.profiles:
        n = len(p.get("outputs", []))
        count = ngettext("%d monitor", "%d monitors", n) % n
        print("%s\t%s\t%s\t%s" % (p["id"], p.get("session"), p.get("name") or "(%s)" % _("automatic"), count))
    return 0


def apply_named(be, st, name):
    layout = be.query()
    for p in st.profiles:
        if name in (p.get("name"), p["id"]):
            target = store.apply_profile(p, layout)
            if target is None:
                print(_("the profile is not for this set of monitors"), file=sys.stderr)
                return 1
            errors = model.validate(target)
            if errors:
                print(_("invalid profile: %s") % errors, file=sys.stderr)
                return 1
            ok, msg = be.apply(target)
            if ok:
                st.mark_applied(target, p, be.name)
                st.save()
                return 0
            print(msg, file=sys.stderr)
            return 1
    print(_("profile not found: %s") % name, file=sys.stderr)
    return 1


def main(argv):
    if "--version" in argv:
        print(VERSION)
        return 0
    if argv[:1] == ["--guard"] and len(argv) > 1:
        return guard.run_guard(argv[1])
    if argv[:1] == ["--watch"]:
        return watch()
    if argv and argv[0] in ("--restore", "--hotplug", "--show", "--profiles", "--apply-profile"):
        if backendmod.session_type() is None:
            return 0
        be = backendmod.get_backend()
        st = store.Store()
        if argv[0] == "--show":
            return show(be, st)
        if argv[0] == "--profiles":
            return list_profiles(st)
        if argv[0] == "--apply-profile":
            return apply_named(be, st, argv[1] if len(argv) > 1 else "")
        return restore(be, st, hotplug=argv[0] == "--hotplug")
    if argv[:1] in (["--help"], ["-h"]):
        print(usage(), end="")
        return 0
    if argv and argv[0].startswith("-") and argv[0] not in ("--gapplication-service",):
        print(usage(), file=sys.stderr, end="")
        return 2
    from . import ui
    return ui.run([sys.argv[0]])
