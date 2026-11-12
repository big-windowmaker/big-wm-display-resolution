#!/usr/bin/python3
# SPDX-License-Identifier: GPL-2.0-or-later
"""Laboratório da tradução (precisa de um X ou de um wlmaker aninhado de
laboratório: NUNCA a sessão real). Usa o backend de teste (arquivo JSON),
então "Aplicar" só grava o arquivo, nenhum monitor de verdade muda. Grava
capturas da janela principal, do diálogo "Manter estas configurações de
monitores?" com a contagem, dos diálogos de perfil e das informações:

    BIGWM_DISPLAY_FAKE=monitores.json BIGWM_DISPLAY_LOCALEDIR=DIR LANG=pt_BR.UTF-8 \\
        python3 tests/lab/i18n_lab.py SAIDA SUFIXO

No Wayland a captura é a tela inteira do Xvfb do laboratório (import);
no X11, a janela de cada passo.
"""

import gettext
import locale
import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)

try:
    locale.setlocale(locale.LC_ALL, "")
except locale.Error:
    pass
gettext.bindtextdomain("big-wm-display-resolution", os.environ.get("BIGWM_DISPLAY_LOCALEDIR", "/usr/share/locale"))
gettext.textdomain("big-wm-display-resolution")

import gi  # noqa: E402

gi.require_version("Gtk", "3.0")
gi.require_version("Gdk", "3.0")
from gi.repository import Gdk, GLib, Gtk  # noqa: E402

from bigwmdisplay import ui  # noqa: E402

out, sfx = sys.argv[1], sys.argv[2]
ui.theme_mode = lambda: os.environ.get("LAB_THEME", "light")
os.makedirs(out, exist_ok=True)
X11 = type(Gdk.Display.get_default()).__name__.startswith("X11")


def pump(n=40, ms=0):
    for _ in range(n):
        while Gtk.events_pending():
            Gtk.main_iteration_do(False)
    if ms:
        done = []
        GLib.timeout_add(ms, lambda: done.append(1))
        while not done:
            Gtk.main_iteration_do(True)


def shot(name, widget):
    pump(ms=300)
    path = os.path.join(out, "dr-%s-%s.png" % (name, sfx))
    gw = widget.get_window()
    if X11 and gw is not None:
        pb = Gdk.pixbuf_get_from_window(gw, 0, 0, gw.get_width(), gw.get_height())
        pb.savev(path, "png", [], [])
    else:
        subprocess.run(["import", "-window", "root", path], check=False)
    print("captura:", path)


def with_dialog(name, action, respond):
    """Roda action() (que abre um diálogo modal com run()) e, de dentro do
    laço do diálogo, captura e responde."""
    def later():
        for w in Gtk.Window.list_toplevels():
            if isinstance(w, Gtk.Dialog) and w.get_visible():
                shot(name, w)
                w.response(respond)
                return False
        return True
    GLib.timeout_add(1800, later)
    action()


def run():
    win = app.window
    win.move(0, 0)
    win.resize(880, 840)
    pump(ms=500)
    shot("main", win)
    # Uma mudança (orientação) ainda não aplicada: o aviso com o prazo.
    win.orient_combo.set_active(1)
    pump(ms=300)
    shot("pending", win)
    # Aplicar: o diálogo com a contagem; responde "Reverter".
    with_dialog("keep", lambda: win._on_apply(None), Gtk.ResponseType.CANCEL)
    pump(ms=300)
    shot("reverted", win)
    # Perfis: salvar como, renomear, excluir.
    with_dialog("save-profile", lambda: win._on_save_as(None), Gtk.ResponseType.CANCEL)
    prof = win.st.add(win.edit, "Escritório", session=win.be.name)
    win._fill_profiles()
    win.profile_combo.set_active_id(prof["id"])
    pump()
    with_dialog("rename-profile", lambda: win._on_rename(None), Gtk.ResponseType.CANCEL)
    with_dialog("delete-profile", lambda: win._on_delete(None), Gtk.ResponseType.CANCEL)
    # O outro monitor (sem HDR) e a lista de perfis aberta.
    win.monitor_combo.set_active(1)
    pump(ms=300)
    shot("second", win)
    app.quit()
    return False


class LabApp(ui.App):
    def do_activate(self):
        ui.App.do_activate(self)
        GLib.idle_add(run)


app = LabApp()
app.run([sys.argv[0]])
