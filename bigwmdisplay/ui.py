# SPDX-License-Identifier: GPL-2.0-or-later
"""A janela "Big WM Display Resolution" (GTK 3), no visual OPENSTEP do Big
WindowMaker: cinzas, relevos de 1 pixel, controles compactos.

Organização como nas configurações de tela do KDE Plasma: a área com os
monitores (arrastar, com encaixe), os perfis no alto e os ajustes do
monitor escolhido embaixo. Aplicar sempre passa pelo vigia da reversão e
pela pergunta "Manter estas configurações de monitores?".
"""

import gettext
import os
import subprocess

import gi

gi.require_version("Gtk", "3.0")
gi.require_version("Gdk", "3.0")
from gi.repository import Gdk, Gio, GLib, Gtk, Pango  # noqa: E402

from . import APP_ID, backend as backendmod, guard, model, nextscroll, store  # noqa: E402
from .guard import CONFIRM_SECONDS  # noqa: E402


def _(text):
    return gettext.gettext(text)


def N_(text):
    return text


def P_(singular, plural, n):
    return gettext.ngettext(singular, plural, n)


# Depois de um evento de monitores: o vigia (debounce de 0,8 s) aplica o
# perfil do conjunto; a janela relê depois disso.
HOTPLUG_SETTLE_MS = 1500

PALETTES = {
    "light": dict(bg="#aeaaae", fg="#000000", light="#ffffff", dark="#515551", field="#c9c6c9",
                  note="#ffffd2", note_fg="#000000", sel="#ffffff", disabled="#6a666a",
                  canvas="#7b787b", screen="#2434b4", screen2="#5262dc", screen_off="#5e5c5e",
                  focus="#000000"),
    "dark": dict(bg="#3a3a3e", fg="#e8e8e8", light="#5e5e64", dark="#18181a", field="#2a2a2e",
                 note="#3b3622", note_fg="#f4e9b8", sel="#55555c", disabled="#8a8a90",
                 canvas="#28282b", screen="#1c2a8c", screen2="#3446b8", screen_off="#3e3e42",
                 focus="#f4e9b8"),
}

CSS = """
#bwmdr {{ background-color: {bg}; color: {fg}; }}
#bwmdr label {{ color: {fg}; }}
#bwmdr label:disabled {{ color: {disabled}; }}
#bwmdr button, #bwmdr combobox button {{
  background-image: none; background-color: {bg}; color: {fg};
  border-radius: 0; border-style: solid; border-width: 1px;
  border-color: {light} {dark} {dark} {light};
  box-shadow: inset -1px -1px 0 {dark}, inset 1px 1px 0 {light};
  padding: 2px 8px; min-height: 18px; text-shadow: none;
}}
#bwmdr button:hover {{ background-color: shade({bg}, 1.05); }}
#bwmdr button:active, #bwmdr button:checked {{
  border-color: {dark} {light} {light} {dark};
  box-shadow: inset 1px 1px 0 {dark}; background-color: shade({bg}, 0.93);
}}
#bwmdr button:disabled, #bwmdr button:disabled label {{ color: {disabled}; }}
#bwmdr button:focus {{ outline: 1px dotted {focus}; outline-offset: -4px; }}
#bwmdr entry, #bwmdr spinbutton, #bwmdr spinbutton entry, #bwmdr textview text {{
  background-color: {field}; color: {fg}; background-image: none; border-radius: 0;
  border: 1px solid; border-color: {dark} {light} {light} {dark}; box-shadow: none;
}}
#bwmdr spinbutton button {{ padding: 0 4px; min-height: 14px; }}
#bwmdr checkbutton, #bwmdr checkbutton label {{ background: transparent; color: {fg}; }}
#bwmdr checkbutton check {{
  background-color: {field}; border-radius: 0;
  border: 1px solid; border-color: {dark} {light} {light} {dark};
}}
#bwmdr checkbutton:disabled label {{ color: {disabled}; }}
#bwmdr frame > border {{
  border-style: solid; border-width: 1px; border-radius: 0;
  border-color: {dark} {light} {light} {dark};
}}
#bwmdr frame > label {{ font-weight: bold; }}
#bwmdr .sunken {{
  border-style: solid; border-width: 2px;
  border-color: {dark} {light} {light} {dark};
}}
#bwmdr .note {{
  background-color: {note}; color: {note_fg}; padding: 4px 8px;
  border-style: solid; border-width: 1px; border-color: {dark} {light} {light} {dark};
}}
#bwmdr .note label {{ color: {note_fg}; }}
#bwmdr .key {{ font-weight: bold; }}
#bwmdr .small {{ font-size: 0.9em; }}
#bwmdr menu, #bwmdr .popup {{ background-color: {bg}; }}
#bwmdr-osd {{ background-color: {bg}; border: 2px solid; border-color: {light} {dark} {dark} {light}; }}
#bwmdr-osd label {{ color: {fg}; }}
#bwmdr-osd .big {{ font-size: 40px; font-weight: bold; }}
"""

ORIENTATIONS = (
    (0, N_("Landscape")),
    (1, N_("Portrait (rotated left)")),
    (2, N_("Landscape (upside down)")),
    (3, N_("Portrait (rotated right)")),
)


def page_css(mode):
    """CSS da janela: controles OPENSTEP + barras de rolagem do WINGs."""
    palette = PALETTES[mode]
    return CSS.format(**palette) + nextscroll.css(palette, mode)


def theme_mode():
    try:
        out = subprocess.run(["big-wm-theme", "get"], capture_output=True, text=True, timeout=3).stdout.strip()
        if out in ("light", "dark"):
            return out
    except (OSError, subprocess.SubprocessError):
        pass
    return "light"


def describe_errors(errors):
    msgs = {
        "no-output": _("At least one monitor must stay on."),
        "no-mode": _("%(name)s has no resolution."),
        "bad-mode": _("%(name)s does not announce the mode %(mode)s."),
        "bad-transform": _("%(name)s does not support this orientation."),
        "no-scale": _("%(name)s: per-monitor scale does not exist on X11."),
        "bad-scale": _("%(name)s: the scale must be between 1 and 3."),
        "bad-mirror": _("%(name)s mirrors a monitor that is off or is itself a mirror."),
        "mirror-size": _("%(name)s and %(source)s need the same resolution to mirror."),
        "overlap": _("%(a)s and %(b)s overlap."),
        "gap": _("The monitors must touch each other: there is a gap between them."),
        "negative": _("Negative positions are not allowed."),
        "too-big": _("The arrangement (%(w)dx%(h)d) exceeds the maximum screen size (%(mw)dx%(mh)d)."),
        "primary": _("Only one monitor can be the primary one."),
    }
    out = []
    for code, data in errors:
        text = msgs.get(code, code)
        try:
            out.append(text % data)
        except (KeyError, TypeError, ValueError):
            out.append(text)
    return out


def refresh_text(m):
    return _("%.2f Hz") % m.hz if m.refresh else _("unknown")


def mode_text(o, size):
    w, h = size
    native = o.native_mode()
    text = "%d × %d" % (w, h)
    g = _gcd(w, h)
    ratio = "%d:%d" % (w // g, h // g)
    if ratio == "8:5":
        ratio = "16:10"
    elif ratio in ("43:18", "64:27"):
        ratio = "21:9"
    text += "  (%s)" % ratio
    if native is not None and native.size == (w, h):
        text += "  — " + _("recommended")
    return text


def _gcd(a, b):
    while b:
        a, b = b, a % b
    return a or 1


class App(Gtk.Application):
    def __init__(self):
        super().__init__(application_id=APP_ID, flags=Gio.ApplicationFlags.FLAGS_NONE)
        self.window = None

    def do_activate(self):
        if self.window is None:
            self.window = MainWindow(self)
        self.window.present()


class MainWindow(Gtk.ApplicationWindow):
    def __init__(self, app):
        super().__init__(application=app, title="Big WM Display Resolution")
        self.set_name("bwmdr")
        self.set_icon_name("big-wm-display-resolution")
        self.set_default_size(820, 640)
        self.provider = Gtk.CssProvider()
        Gtk.StyleContext.add_provider_for_screen(Gdk.Screen.get_default(), self.provider,
                                                 Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)
        self.mode = theme_mode()
        self.palette = PALETTES[self.mode]
        self.provider.load_from_data(page_css(self.mode).encode())
        Gtk.Settings.get_default().connect("notify::gtk-theme-name", self._theme_changed)

        self.be = backendmod.get_backend()
        self.st = store.Store()
        self.current = None
        self.edit = None
        self.selected = None
        self.loading = False
        self.applied_profile = None     # perfil escolhido para aplicar
        self._pending = None
        self.osd = []
        self._confirming = False
        self._hotplug_timer = 0
        self._notice = None             # aviso do hotplug, até a próxima edição
        self._build()
        for w in (self.profile_combo, self.monitor_combo, self.use_combo, self.res_combo, self.rate_combo,
                  self.scale_combo, self.orient_combo, self.spin_x, self.spin_y):
            nextscroll.guard_wheel(w)
        self.connect("key-press-event", self._on_key)
        # Monitor ligado, desligado ou reconfigurado por outro programa (o
        # vigia aplicando o perfil): a janela acompanha, por evento (RandR no
        # X11, wl_output no Wayland), sem consultar de tempos em tempos.
        Gdk.Screen.get_default().connect("monitors-changed", self._on_monitors_changed)
        # O GDK só conta monitores ligados: um monitor que acabou de ser
        # conectado (ainda apagado, ou ligado logo depois pelo vigia) às vezes
        # não gera sinal nenhum. O helper vigia as saídas conectadas.
        self._watcher = None
        self._start_watcher()
        self.connect("destroy", lambda *_a: self._stop_watcher())
        self.reload()
        self._fit_to_screen()
        self.show_all()
        self._update_controls()

    # -- Estado -------------------------------------------------------------

    def reload(self, select=None):
        try:
            self.current = self.be.query(probe_vrr=True) if self.be.name == "wayland" else self.be.query()
        except Exception as e:  # noqa: BLE001
            self._message(_("Could not read the monitors: %s") % e, error=True)
            self.current = model.Layout(self.be.name, [])
        from . import cli
        if cli.run_migrations(self.st, self.current):
            self.st.save()
        self.edit = self.current.copy()
        if select is None and self.selected is not None and self.edit.get(self.selected):
            select = self.selected
        if select is None:
            prim = self.edit.primary() or (self.edit.enabled() or self.edit.outputs or [None])[0]
            select = prim.name if prim else None
        self.selected = select
        self.applied_profile = None
        self._notice = None
        self._fill_monitor_combo()
        self._fill_profiles()
        self._update_controls()
        self.canvas.fit()

    def _start_watcher(self):
        session = backendmod.session_type()
        if session is None:
            return
        helper = backendmod.backend_wl.helper_path()
        mode = "wl-watch" if session == "wayland" else "x11-watch"
        try:
            self._watcher = subprocess.Popen([helper, mode, "--print"], stdin=subprocess.DEVNULL,
                                             stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
        except OSError:
            self._watcher = None
            return
        GLib.io_add_watch(self._watcher.stdout.fileno(), GLib.PRIORITY_DEFAULT,
                          GLib.IO_IN | GLib.IO_HUP | GLib.IO_ERR, self._on_watcher)

    def _on_watcher(self, fd, cond):
        if cond & GLib.IO_IN:
            data = os.read(fd, 4096)
            if data:
                self._on_monitors_changed()
                return True
        return False                    # o helper terminou

    def _stop_watcher(self):
        w, self._watcher = self._watcher, None
        if w is not None and w.poll() is None:
            w.terminate()
            try:
                w.wait(timeout=2)
            except subprocess.TimeoutExpired:
                w.kill()

    def _on_monitors_changed(self, *_a):
        # Os eventos chegam em rajada e o vigia ainda aplica o perfil logo
        # depois: espera acalmar.
        if self._hotplug_timer:
            GLib.source_remove(self._hotplug_timer)
        self._hotplug_timer = GLib.timeout_add(HOTPLUG_SETTLE_MS, self._monitors_settled)

    def _monitors_settled(self):
        self._hotplug_timer = 0
        if self._confirming:
            # "Manter estas configurações?" aberto: quem muda é a própria
            # janela, que relê tudo depois da resposta.
            return False
        try:
            now = self.be.query()
        except Exception as e:  # noqa: BLE001
            self._message(_("Could not read the monitors: %s") % e, error=True)
            return False
        if self.current is None:
            self.reload()
            return False
        same_set = model.set_key(now.outputs) == model.set_key(self.current.outputs)
        if same_set and model.same_config(now, self.current):
            return False
        edited = not model.same_config(self.edit, self.current)
        if same_set and edited:
            # Mesmos monitores, outra configuração vinda de fora: a edição
            # continua valendo; a reversão volta para o estado novo.
            self.current = now
            self._message(_("The monitors were reconfigured by another program; "
                            "your changes were kept and not applied yet."))
            return False
        self.reload(self.selected)
        if not same_set:
            n = len(self.current.outputs)
            if edited:
                self._notice = _("The connected monitors changed (%d now); the window was updated "
                                 "and the changes not applied were discarded.") % n
            else:
                self._notice = _("The connected monitors changed (%d now); the window was updated.") % n
            self._message(self._notice)
        return False

    def sel(self):
        return self.edit.get(self.selected) if self.edit and self.selected else None

    def changed(self, refit=False):
        model.sync_mirrors(self.edit)
        if refit:
            self.canvas.fit()
        self.canvas.queue_draw()
        self._update_controls()

    # -- Construção ---------------------------------------------------------

    def _build(self):
        top = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        self.add(top)
        scroller = Gtk.ScrolledWindow()
        scroller.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        # barra fixa ao lado do conteúdo, como no WINGs (não a "overlay",
        # que some e fica por cima dos controles)
        scroller.set_overlay_scrolling(False)
        scroller.set_propagate_natural_height(True)
        top.pack_start(scroller, True, True, 0)
        outer = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        outer.set_border_width(8)
        scroller.add(outer)
        self._bottom = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        self._bottom.set_border_width(8)
        top.pack_end(self._bottom, False, False, 0)

        # Perfis
        prow = Gtk.Box(spacing=4)
        prow.pack_start(Gtk.Label(label=_("Profile:")), False, False, 0)
        self.profile_combo = Gtk.ComboBoxText()
        self.profile_combo.set_hexpand(True)
        self.profile_combo.connect("changed", self._on_profile_chosen)
        prow.pack_start(self.profile_combo, True, True, 0)
        self.btn_save_as = Gtk.Button(label=_("Save as…"))
        self.btn_save_as.connect("clicked", self._on_save_as)
        self.btn_rename = Gtk.Button(label=_("Rename…"))
        self.btn_rename.connect("clicked", self._on_rename)
        self.btn_delete = Gtk.Button(label=_("Delete"))
        self.btn_delete.connect("clicked", self._on_delete)
        for b in (self.btn_save_as, self.btn_rename, self.btn_delete):
            prow.pack_start(b, False, False, 0)
        outer.pack_start(prow, False, False, 0)

        # Área dos monitores
        frame = Gtk.EventBox()
        frame.get_style_context().add_class("sunken")
        self.canvas = Canvas(self)
        self.canvas.set_size_request(-1, 170)
        frame.add(self.canvas)
        outer.pack_start(frame, True, True, 0)

        crow = Gtk.Box(spacing=4)
        self.btn_identify = Gtk.Button(label=_("Identify"))
        self.btn_identify.set_tooltip_text(_("Shows the name of each monitor on its screen"))
        self.btn_identify.connect("clicked", lambda _b: self.identify())
        self.btn_row = Gtk.Button(label=_("Side by side"))
        self.btn_row.set_tooltip_text(_("Arranges the monitors in a row, left to right, aligned at the top"))
        self.btn_row.connect("clicked", self._on_row)
        self.btn_default = Gtk.Button(label=_("Defaults"))
        self.btn_default.set_tooltip_text(_("All monitors on, at their native resolution, side by side"))
        self.btn_default.connect("clicked", self._on_default)
        for b in (self.btn_identify, self.btn_row, self.btn_default):
            crow.pack_start(b, False, False, 0)
        self.hint = Gtk.Label(xalign=1)
        self.hint.get_style_context().add_class("small")
        self.hint.set_ellipsize(Pango.EllipsizeMode.END)
        crow.pack_end(self.hint, True, True, 0)
        outer.pack_start(crow, False, False, 0)

        # Ajustes e informações
        body = Gtk.Box(spacing=8)
        outer.pack_start(body, False, False, 0)

        self.settings_frame = Gtk.Frame(label=_("Monitor"))
        grid = Gtk.Grid(row_spacing=4, column_spacing=6)
        grid.set_border_width(6)
        self.settings_frame.add(grid)
        body.pack_start(self.settings_frame, True, True, 0)
        r = 0

        self.monitor_combo = Gtk.ComboBoxText()
        self.monitor_combo.connect("changed", self._on_monitor_chosen)
        grid.attach(self._key(_("Monitor:")), 0, r, 1, 1)
        grid.attach(self.monitor_combo, 1, r, 3, 1)
        r += 1

        self.chk_enabled = Gtk.CheckButton(label=_("On"))
        self.chk_enabled.connect("toggled", self._on_enabled)
        self.chk_primary = Gtk.CheckButton(label=_("Primary monitor"))
        self.chk_primary.connect("toggled", self._on_primary)
        grid.attach(self.chk_enabled, 1, r, 1, 1)
        grid.attach(self.chk_primary, 2, r, 2, 1)
        r += 1

        self.use_combo = Gtk.ComboBoxText()
        self.use_combo.connect("changed", self._on_use)
        grid.attach(self._key(_("Use:")), 0, r, 1, 1)
        grid.attach(self.use_combo, 1, r, 3, 1)
        r += 1

        self.res_combo = Gtk.ComboBoxText()
        self.res_combo.connect("changed", self._on_resolution)
        grid.attach(self._key(_("Resolution:")), 0, r, 1, 1)
        grid.attach(self.res_combo, 1, r, 3, 1)
        r += 1

        self.rate_combo = Gtk.ComboBoxText()
        self.rate_combo.connect("changed", self._on_rate)
        grid.attach(self._key(_("Refresh rate:")), 0, r, 1, 1)
        grid.attach(self.rate_combo, 1, r, 3, 1)
        r += 1

        self.scale_combo = Gtk.ComboBoxText()
        self.scale_combo.connect("changed", self._on_scale)
        self.scale_note = Gtk.Label(xalign=0)
        self.scale_note.get_style_context().add_class("small")
        self.scale_note.set_line_wrap(True)
        self.scale_note.set_max_width_chars(36)
        self.scale_note.set_max_width_chars(60)
        grid.attach(self._key(_("Scale:")), 0, r, 1, 1)
        grid.attach(self.scale_combo, 1, r, 1, 1)
        r += 1
        grid.attach(self.scale_note, 1, r, 3, 1)
        r += 1

        self.orient_combo = Gtk.ComboBoxText()
        for _t, label in ORIENTATIONS:
            self.orient_combo.append_text(_(label))
        self.orient_combo.connect("changed", self._on_orientation)
        self.chk_flip = Gtk.CheckButton(label=_("Mirror image (reflect)"))
        self.chk_flip.connect("toggled", self._on_orientation)
        grid.attach(self._key(_("Orientation:")), 0, r, 1, 1)
        grid.attach(self.orient_combo, 1, r, 1, 1)
        grid.attach(self.chk_flip, 2, r, 2, 1)
        r += 1

        self.spin_x = Gtk.SpinButton.new_with_range(-32768, 32767, 1)
        self.spin_y = Gtk.SpinButton.new_with_range(-32768, 32767, 1)
        for s in (self.spin_x, self.spin_y):
            s.set_numeric(True)
            s.set_width_chars(6)
            s.connect("value-changed", self._on_position)
        pos = Gtk.Box(spacing=4)
        pos.pack_start(Gtk.Label(label="X"), False, False, 0)
        pos.pack_start(self.spin_x, False, False, 0)
        pos.pack_start(Gtk.Label(label="Y"), False, False, 0)
        pos.pack_start(self.spin_y, False, False, 0)
        grid.attach(self._key(_("Position:")), 0, r, 1, 1)
        grid.attach(pos, 1, r, 3, 1)
        r += 1

        self.chk_vrr = Gtk.CheckButton(label=_("Variable refresh rate (VRR / Adaptive Sync)"))
        self.chk_vrr.connect("toggled", self._on_vrr)
        self.vrr_note = Gtk.Label(xalign=0)
        self.vrr_note.get_style_context().add_class("small")
        self.vrr_note.set_line_wrap(True)
        self.vrr_note.set_max_width_chars(48)
        grid.attach(self._key(_("VRR:")), 0, r, 1, 1)
        grid.attach(self.chk_vrr, 1, r, 3, 1)
        r += 1
        grid.attach(self.vrr_note, 1, r, 3, 1)
        r += 1
        self.hdr_note = Gtk.Label(xalign=0)
        self.hdr_note.get_style_context().add_class("small")
        self.hdr_note.set_line_wrap(True)
        self.hdr_note.set_max_width_chars(48)
        grid.attach(self._key(_("HDR:")), 0, r, 1, 1)
        grid.attach(self.hdr_note, 1, r, 3, 1)

        info_frame = Gtk.Frame(label=_("Information"))
        ibox = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        ibox.set_border_width(6)
        info_frame.add(ibox)
        self.info_grid = Gtk.Grid(row_spacing=2, column_spacing=6)
        ibox.pack_start(self.info_grid, False, False, 0)
        self.edid_expander = Gtk.Expander(label=_("EDID"))
        self.edid_view = Gtk.TextView(editable=False, monospace=True, wrap_mode=Gtk.WrapMode.CHAR)
        self.edid_view.set_size_request(260, 90)
        sw = Gtk.ScrolledWindow()
        sw.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        sw.set_overlay_scrolling(False)
        sw.set_min_content_height(90)
        sw.add(self.edid_view)
        self.edid_expander.add(sw)
        ibox.pack_start(self.edid_expander, False, False, 0)
        body.pack_start(info_frame, False, False, 0)

        # Mensagens
        self.note = Gtk.EventBox()
        self.note.get_style_context().add_class("note")
        self.note_label = Gtk.Label(xalign=0)
        self.note_label.set_line_wrap(True)
        for side in ("start", "end", "top", "bottom"):
            getattr(self.note_label, "set_margin_" + side)(6 if side in ("start", "end") else 3)
        self.note.add(self.note_label)
        self._bottom.pack_start(self.note, False, False, 0)

        brow = Gtk.Box(spacing=6)
        self.btn_reset = Gtk.Button(label=_("Reset"))
        self.btn_reset.set_tooltip_text(_("Discards the changes not yet applied"))
        self.btn_reset.connect("clicked", lambda _b: self.reload(self.selected))
        brow.pack_start(self.btn_reset, False, False, 0)
        self.btn_close = Gtk.Button(label=_("Close"))
        self.btn_close.connect("clicked", lambda _b: self.close())
        self.btn_apply = Gtk.Button(label=_("Apply"))
        self.btn_apply.connect("clicked", self._on_apply)
        brow.pack_end(self.btn_close, False, False, 0)
        brow.pack_end(self.btn_apply, False, False, 0)
        self._bottom.pack_start(brow, False, False, 0)

    def _fit_to_screen(self):
        """Nunca maior que a área útil do monitor (telas pequenas rolam)."""
        display = Gdk.Display.get_default()
        mon = display.get_primary_monitor() or (display.get_monitor(0) if display.get_n_monitors() else None)
        if mon is not None:
            area = mon.get_workarea()
            self.set_default_size(min(820, area.width - 20), min(660, area.height - 40))

    def _key(self, text):
        lab = Gtk.Label(label=text, xalign=1)
        lab.get_style_context().add_class("key")
        return lab

    def _theme_changed(self, *_a):
        mode = theme_mode()
        if mode != self.mode:
            self.mode = mode
            self.palette = PALETTES[mode]
            self.provider.load_from_data(page_css(self.mode).encode())
            self.canvas.queue_draw()

    # -- Preenchimento dos controles ------------------------------------------

    def _fill_monitor_combo(self):
        self.loading = True
        self.monitor_combo.remove_all()
        for o in self.edit.outputs:
            self.monitor_combo.append(o.name, "%s — %s" % (o.name, o.label()))
        if self.selected:
            self.monitor_combo.set_active_id(self.selected)
        self.loading = False

    def _fill_profiles(self):
        self.loading = True
        self.profile_combo.remove_all()
        self.profile_ids = []
        session = self.be.name
        self.profile_combo.append("@current", _("Current configuration"))
        self.profile_combo.append("@default", _("Defaults (all on, side by side)"))
        for p in self.st.matching(self.current):
            name = p.get("name") or ""
            if p.get("kind") == "auto":
                name = _("Saved automatically") + (" — " + name if name else "")
            if p.get("session") != session:
                name += " (%s)" % ("X11" if p.get("session") == "x11" else "Wayland")
            self.profile_combo.append(p["id"], name)
        self.profile_combo.set_active_id("@current")
        self.loading = False

    def _update_controls(self):
        if self.edit is None:
            return
        self.loading = True
        o = self.sel()
        has = o is not None
        for w in (self.chk_enabled, self.chk_primary, self.use_combo, self.res_combo, self.rate_combo,
                  self.scale_combo, self.orient_combo, self.chk_flip, self.spin_x, self.spin_y, self.chk_vrr):
            w.set_sensitive(has)
        if has:
            self.settings_frame.set_label("%s — %s" % (o.name, o.label()))
            self.chk_enabled.set_active(o.enabled)
            on = o.enabled
            # Principal: só no X11.
            self.chk_primary.set_active(o.primary)
            self.chk_primary.set_sensitive(on and bool(self.edit.caps.get("primary")) and not o.mirror_of)
            if not self.edit.caps.get("primary"):
                self.chk_primary.set_tooltip_text(
                    _("On Wayland, wlmaker has no configurable primary monitor: the first one in the "
                      "arrangement holds the Dock."))
            else:
                self.chk_primary.set_tooltip_text(_("Panels, the Dock and new windows prefer this monitor"))
            # Estender / espelhar
            self.use_combo.remove_all()
            self.use_combo.append("", _("Extend the desktop"))
            for p in self.edit.outputs:
                if p is not o and p.enabled and not p.mirror_of:
                    self.use_combo.append(p.name, _("Mirror %s") % p.name)
            self.use_combo.set_active_id(o.mirror_of or "")
            self.use_combo.set_sensitive(on and len(self.use_combo.get_model()) > 1)
            # Resolução
            self.res_combo.remove_all()
            sizes = []
            for m in sorted(o.modes, key=lambda m: (m.width * m.height, m.width), reverse=True):
                if m.interlaced or m.size in sizes:
                    continue
                sizes.append(m.size)
                self.res_combo.append("%dx%d" % m.size, mode_text(o, m.size))
            if o.mode is not None:
                self.res_combo.set_active_id("%dx%d" % o.mode.size)
            self.res_combo.set_sensitive(on and len(sizes) > 1)
            # Frequência
            self.rate_combo.remove_all()
            if o.mode is not None:
                rates = sorted({m.refresh: m for m in o.modes if m.size == o.mode.size and not m.interlaced}.values(),
                               key=lambda m: -m.refresh)
                native = o.native_mode()
                for m in rates:
                    text = refresh_text(m)
                    if m.refresh and native is not None and m.size == native.size and m.refresh == native.refresh:
                        text += "  — " + _("recommended")
                    self.rate_combo.append(str(m.refresh), text)
                self.rate_combo.set_active_id(str(o.mode.refresh))
                self.rate_combo.set_sensitive(on and len(rates) > 1)
            # Escala
            self.scale_combo.remove_all()
            if self.edit.caps.get("scale"):
                scales = list(model.WAYLAND_SCALES)
                if all(abs(o.scale - s) > 1e-3 for s in scales):
                    scales.append(o.scale)
                for s in sorted(scales):
                    self.scale_combo.append("%.4f" % s, "%d%%" % round(s * 100))
                self.scale_combo.set_active_id("%.4f" % o.scale)
                self.scale_combo.set_sensitive(on and not o.mirror_of)
                self.scale_note.set_text(_("Fractional scales reach applications that support "
                                           "fractional-scale; the others are drawn at 1× and enlarged."))
            else:
                self.scale_combo.append("1.0000", "100%")
                self.scale_combo.set_active(0)
                self.scale_combo.set_sensitive(False)
                self.scale_note.set_text(_("X11 has no per-monitor scale (xrandr --scale only stretches "
                                           "the picture). Use the GTK/Qt scale for larger text."))
            # Orientação
            self.orient_combo.set_active(o.transform % 4)
            self.chk_flip.set_active(o.transform >= 4)
            rots = {t % 4 for t in o.transforms}
            self.orient_combo.set_sensitive(on and len(rots) > 1)
            self.chk_flip.set_sensitive(on and any(t >= 4 for t in o.transforms))
            if not any(t >= 4 for t in o.transforms):
                self.chk_flip.set_tooltip_text(_("This monitor's driver does not offer reflection"))
            else:
                self.chk_flip.set_tooltip_text(None)
            # Posição
            self.spin_x.set_value(o.x)
            self.spin_y.set_value(o.y)
            self.spin_x.set_sensitive(on and not o.mirror_of)
            self.spin_y.set_sensitive(on and not o.mirror_of)
            self._update_vrr_hdr(o)
            self._update_info(o)
        else:
            self.settings_frame.set_label(_("Monitor"))
        errors = model.validate(self.edit) if self.edit.outputs else [("no-output", {})]
        dirty = self.current is not None and not model.same_config(self.edit, self.current)
        self.btn_apply.set_sensitive(dirty and not errors)
        self.btn_reset.set_sensitive(dirty)
        if errors:
            self._message("\n".join(describe_errors(errors)), error=True)
        elif dirty:
            self._message(P_("Changes not applied yet. Apply asks for confirmation and goes back to the "
                             "previous configuration after %d second without an answer.",
                             "Changes not applied yet. Apply asks for confirmation and goes back to the "
                             "previous configuration after %d seconds without an answer.",
                             CONFIRM_SECONDS) % CONFIRM_SECONDS)
        else:
            self._message(self._notice or self._status_text())
        p = self.profile_combo.get_active_id() or ""
        custom = self.st.get(p) if not p.startswith("@") else None
        self.btn_rename.set_sensitive(custom is not None)
        self.btn_delete.set_sensitive(custom is not None)
        self.btn_save_as.set_sensitive(not errors and bool(self.edit.outputs))
        self.btn_row.set_sensitive(len(self.edit.enabled()) > 1)
        self.btn_identify.set_sensitive(bool(self.current and self.current.enabled()))
        self.loading = False

    def _status_text(self):
        prof = self.st.best_for(self.current, self.be.name)
        n = len(self.current.outputs)
        if prof is None:
            return P_("%d monitor connected. No saved configuration for this monitor yet: "
                      "the one you keep is restored at login and when it is plugged in.",
                      "%d monitors connected. No saved configuration for this set of monitors yet: "
                      "the one you keep is restored at login and when they are plugged in.", n) % n
        return P_("%d monitor connected. This configuration is restored at login and whenever this "
                  "same monitor is connected.",
                  "%d monitors connected. This configuration is restored at login and whenever this "
                  "same set of monitors is connected.", n) % n

    def _update_vrr_hdr(self, o):
        e = o.edid
        declared = ""
        if e is not None and e.vrr_range and e.vrr_range[0] and e.vrr_range[1] > e.vrr_range[0]:
            declared = _("The EDID declares %d–%d Hz.") % e.vrr_range
            if e.freesync:
                declared += " " + _("FreeSync block present.")
        if self.be.name == "x11":
            self.chk_vrr.set_visible(False)
            if o.vrr_capable is None:
                cap = _("The driver does not report whether this output supports VRR (no vrr_capable property).")
            elif o.vrr_capable:
                cap = _("The driver reports this output as VRR capable.")
            else:
                cap = _("The driver reports this output as not VRR capable.")
            self.vrr_note.set_text(cap + " " + _("On X11 VRR is a driver option (Option \"VariableRefresh\" "
                                                 "in xorg.conf), not a per-monitor setting.") +
                                   (" " + declared if declared else ""))
        else:
            if o.vrr is None:
                self.chk_vrr.set_visible(False)
                self.vrr_note.set_text(_("The compositor does not report adaptive sync (output management "
                                         "older than version 4).") + (" " + declared if declared else ""))
            elif o.vrr_capable:
                self.chk_vrr.set_visible(True)
                self.chk_vrr.set_active(bool(o.vrr))
                self.chk_vrr.set_sensitive(o.enabled)
                self.vrr_note.set_text(declared)
            else:
                self.chk_vrr.set_visible(False)
                if o.vrr:
                    fixed = _("Adaptive sync is on and cannot be changed: the compositor refused "
                              "the change in a test of this output.")
                else:
                    fixed = _("Adaptive sync is off and cannot be changed: the compositor refused "
                              "the change in a test of this output.")
                self.vrr_note.set_text(fixed + (" " + declared if declared else ""))
        if e is not None and e.hdr:
            hdr = _("The monitor declares HDR (%s).") % ", ".join(e.hdr_eotfs)
        elif e is not None:
            hdr = _("The monitor does not declare HDR in its EDID.")
        else:
            hdr = _("No EDID: HDR capability unknown.")
        if self.be.name == "x11":
            hdr += " " + _("X11 has no HDR output.")
        else:
            hdr += " " + _("wlmaker does not drive HDR outputs, and output management has no HDR "
                           "setting: there is nothing to turn on here.")
        self.hdr_note.set_text(hdr)

    def _update_info(self, o):
        e = o.edid
        native = o.native_mode()
        rows = [
            (_("Manufacturer"), o.make or _("unknown")),
            (_("Model"), o.model or _("unknown")),
            (_("Serial"), o.serial or _("not informed")),
            (_("Connector"), o.name),
            (_("Native"), "%d × %d @ %s" % (native.width, native.height, refresh_text(native)) if native else "—"),
            (_("Current"), ("%d × %d @ %s" % (o.mode.width, o.mode.height, refresh_text(o.mode))
                            if o.enabled and o.mode else _("off"))),
        ]
        mm = o.physical
        if (not mm or not mm[0]) and e is not None and e.width_cm:
            mm = (e.width_cm * 10, e.height_cm * 10)
        if mm and mm[0] and mm[1]:
            diag = ((mm[0] ** 2 + mm[1] ** 2) ** 0.5) / 25.4
            rows.append((_("Size"), _("%d × %d mm (%.1f″)") % (mm[0], mm[1], diag)))
        else:
            rows.append((_("Size"), _("not informed")))
        rows.append((_("Year"), str(e.year) if e is not None and e.year else "—"))
        # As linhas são criadas uma vez e só mudam de texto: recriar rótulos
        # (selecionáveis, com foco) durante um evento de teclado derrubava o GTK.
        if not getattr(self, "info_values", None):
            self.info_values = []
            for i, (k, _v) in enumerate(rows):
                kl = Gtk.Label(label=k + ":", xalign=1)
                kl.get_style_context().add_class("key")
                vl = Gtk.Label(xalign=0, selectable=True)
                vl.set_can_focus(False)
                vl.set_ellipsize(Pango.EllipsizeMode.END)
                vl.set_max_width_chars(22)
                self.info_grid.attach(kl, 0, i, 1, 1)
                self.info_grid.attach(vl, 1, i, 1, 1)
                self.info_values.append(vl)
            self.info_grid.show_all()
        for vl, (_k, v) in zip(self.info_values, rows, strict=True):
            vl.set_text(v)
            vl.set_tooltip_text(v)
        if e is not None:
            h = e.hex()
            self.edid_view.get_buffer().set_text("\n".join(h[i:i + 32] for i in range(0, len(h), 32)))
            self.edid_expander.set_sensitive(True)
            self.edid_expander.set_label(_("EDID (%d bytes)") % len(e.raw))
        else:
            self.edid_view.get_buffer().set_text("")
            self.edid_expander.set_sensitive(False)
            self.edid_expander.set_label(_("EDID: not available"))

    def _message(self, text, error=False):
        self.note_label.set_text(text)
        self.note_label.set_tooltip_text(text)

    # -- Ações dos controles ------------------------------------------------

    def _on_monitor_chosen(self, combo):
        if self.loading:
            return
        name = combo.get_active_id()
        if name:
            self.selected = name
            self.canvas.queue_draw()
            self._update_controls()

    def select(self, name):
        self.selected = name
        self.loading = True
        self.monitor_combo.set_active_id(name)
        self.loading = False
        self.canvas.queue_draw()
        self._update_controls()

    def _on_enabled(self, chk):
        o = self.sel()
        if self.loading or o is None:
            return
        o.enabled = chk.get_active()
        if o.enabled:
            if o.mode is None:
                o.mode = o.native_mode()
            others = [p.rect() for p in self.edit.enabled() if p is not o and not p.mirror_of]
            right = max((r[0] + r[2] for r in others), default=0)
            o.x, o.y = right, 0
            o.mirror_of = None
        else:
            o.primary = False
            for p in self.edit.outputs:
                if p.mirror_of == o.name:
                    p.mirror_of = None
        if self.edit.caps.get("primary") and not self.edit.primary():
            for p in self.edit.enabled():
                p.primary = True
                break
        model.normalize(self.edit)
        self.changed(refit=True)

    def _on_primary(self, chk):
        o = self.sel()
        if self.loading or o is None:
            return
        for p in self.edit.outputs:
            p.primary = False
        o.primary = chk.get_active()
        self.changed()

    def _on_use(self, combo):
        o = self.sel()
        if self.loading or o is None:
            return
        src_name = combo.get_active_id() or None
        o.mirror_of = src_name
        if src_name:
            src = self.edit.get(src_name)
            # Espelhar pede o mesmo tamanho: a resolução da origem, se este
            # monitor a anuncia.
            m = model.find_mode(o.modes, src.mode.width, src.mode.height, 0) if src and src.mode else None
            if m is not None:
                o.mode = m
            o.transform = src.transform if src.transform in o.transforms else o.transform
            o.scale = src.scale
            o.primary = False
        else:
            others = [p.rect() for p in self.edit.enabled() if p is not o and not p.mirror_of]
            right = max((r[0] + r[2] for r in others), default=0)
            o.x, o.y = right, 0
        model.normalize(self.edit)
        self.changed(refit=True)

    def _on_resolution(self, combo):
        o = self.sel()
        if self.loading or o is None or not combo.get_active_id():
            return
        w, h = (int(v) for v in combo.get_active_id().split("x"))
        native = o.native_mode()
        prefer = native.refresh if native is not None and native.size == (w, h) else 0
        o.mode = model.find_mode(o.modes, w, h, prefer) or model.find_mode(o.modes, w, h, 0)
        self._relayout_after_resize(o)

    def _on_rate(self, combo):
        o = self.sel()
        if self.loading or o is None or not combo.get_active_id() or o.mode is None:
            return
        m = model.find_mode(o.modes, o.mode.width, o.mode.height, int(combo.get_active_id()))
        if m is not None:
            o.mode = m
        self.changed()

    def _on_scale(self, combo):
        o = self.sel()
        if self.loading or o is None or not combo.get_active_id():
            return
        o.scale = float(combo.get_active_id())
        self._relayout_after_resize(o)

    def _on_orientation(self, _w):
        o = self.sel()
        if self.loading or o is None:
            return
        t = self.orient_combo.get_active() % 4 + (4 if self.chk_flip.get_active() else 0)
        if t not in o.transforms:
            t = self.orient_combo.get_active() % 4
        o.transform = t
        self._relayout_after_resize(o)

    def _relayout_after_resize(self, o):
        """Mudou o tamanho de um monitor: os que estavam encostados à direita
        e embaixo dele acompanham, e nada fica sobreposto."""
        for p in self.edit.outputs:
            if p.mirror_of == o.name:
                m = model.find_mode(p.modes, o.mode.width, o.mode.height, 0) if o.mode else None
                if m is not None:
                    p.mode = m
                p.scale, p.transform = o.scale, o.transform if o.transform in p.transforms else p.transform
        others = [p for p in self.edit.enabled() if p is not o and not p.mirror_of]
        if others and any(model.overlaps(o.rect(), p.rect()) for p in others) or (
                others and not any(model.touches(o.rect(), p.rect()) for p in others)):
            model.arrange_row(self.edit)
        model.normalize(self.edit)
        self.changed(refit=True)

    def _on_position(self, _s):
        o = self.sel()
        if self.loading or o is None:
            return
        o.x, o.y = int(self.spin_x.get_value()), int(self.spin_y.get_value())
        self.changed()

    def _on_vrr(self, chk):
        o = self.sel()
        if self.loading or o is None or o.vrr is None:
            return
        o.vrr = chk.get_active()
        self.changed()

    def _on_row(self, _b):
        model.arrange_row(self.edit)
        self.changed(refit=True)

    def _on_default(self, _b):
        self.edit = model.default_layout(self.current)
        self.changed(refit=True)

    def _on_key(self, _w, ev):
        o = self.sel()
        if o is None or not o.enabled or o.mirror_of:
            return False
        if isinstance(self.get_focus(), (Gtk.Entry, Gtk.SpinButton, Gtk.ComboBox)):
            return False
        step = 10 if ev.state & Gdk.ModifierType.SHIFT_MASK else 1
        dx, dy = {Gdk.KEY_Left: (-step, 0), Gdk.KEY_Right: (step, 0),
                  Gdk.KEY_Up: (0, -step), Gdk.KEY_Down: (0, step)}.get(ev.keyval, (None, None))
        if dx is None or not self.canvas.has_focus():
            return False
        o.x += dx
        o.y += dy
        self.changed()
        return True

    # -- Perfis -------------------------------------------------------------

    def _on_profile_chosen(self, combo):
        if self.loading:
            return
        pid = combo.get_active_id()
        self.applied_profile = None
        if pid == "@current":
            self.edit = self.current.copy()
        elif pid == "@default":
            self.edit = model.default_layout(self.current)
        else:
            p = self.st.get(pid)
            new = store.apply_profile(p, self.current) if p else None
            if new is None:
                self._message(_("This profile no longer fits these monitors (a mode it uses is not "
                                "announced any more)."), error=True)
                return
            self.edit = new
            self.applied_profile = pid
        self.changed(refit=True)

    def _ask_name(self, title, initial=""):
        dlg = Gtk.Dialog(title=title, transient_for=self, modal=True)
        dlg.set_name("bwmdr")
        dlg.add_button(_("Cancel"), Gtk.ResponseType.CANCEL)
        dlg.add_button(_("OK"), Gtk.ResponseType.OK)
        dlg.set_default_response(Gtk.ResponseType.OK)
        entry = Gtk.Entry(text=initial, activates_default=True)
        box = dlg.get_content_area()
        box.set_border_width(8)
        box.set_spacing(6)
        box.add(Gtk.Label(label=_("Profile name:"), xalign=0))
        box.add(entry)
        dlg.show_all()
        resp = dlg.run()
        name = entry.get_text().strip()
        dlg.destroy()
        return name if resp == Gtk.ResponseType.OK and name else None

    def _on_save_as(self, _b):
        name = self._ask_name(_("Save profile"))
        if not name:
            return
        prof = self.st.add(self.edit, name, session=self.be.name)
        self.st.save()
        self._fill_profiles()
        self.loading = True
        self.profile_combo.set_active_id(prof["id"])
        self.loading = False
        self.applied_profile = prof["id"]
        self._update_controls()

    def _on_rename(self, _b):
        pid = self.profile_combo.get_active_id()
        p = self.st.get(pid)
        if p is None:
            return
        name = self._ask_name(_("Rename profile"), p.get("name", ""))
        if name and self.st.rename(pid, name):
            self.st.save()
            self._fill_profiles()
            self.loading = True
            self.profile_combo.set_active_id(pid)
            self.loading = False
            self._update_controls()

    def _on_delete(self, _b):
        pid = self.profile_combo.get_active_id()
        p = self.st.get(pid)
        if p is None:
            return
        dlg = Gtk.MessageDialog(transient_for=self, modal=True, message_type=Gtk.MessageType.QUESTION,
                                buttons=Gtk.ButtonsType.NONE,
                                text=_("Delete the profile \"%s\"?") % (p.get("name") or _("saved automatically")))
        dlg.set_name("bwmdr")
        dlg.add_button(_("Cancel"), Gtk.ResponseType.CANCEL)
        dlg.add_button(_("Delete"), Gtk.ResponseType.OK)
        resp = dlg.run()
        dlg.destroy()
        if resp == Gtk.ResponseType.OK:
            self.st.delete(pid)
            self.st.save()
            self._fill_profiles()
            self._update_controls()

    # -- Aplicar -------------------------------------------------------------

    def _on_apply(self, _b):
        self._pending = self.applied_profile
        errors = model.validate(self.edit)
        if errors:
            self._message("\n".join(describe_errors(errors)), error=True)
            return
        ok, msg = self.be.test(self.edit)
        if not ok:
            self._message(_("The configuration was refused in the test: %s") % msg, error=True)
            return
        previous = self.current
        try:
            g = guard.Guard(previous)
        except (OSError, RuntimeError) as e:
            self._message(_("Could not start the revert guard, nothing was changed: %s") % e, error=True)
            return
        target = self.edit
        ok, msg = self.be.apply(target)
        if not ok:
            g.revert()
            self.reload(self.selected)
            self._message(_("Applying failed (%s); the previous configuration is back.") % msg, error=True)
            return
        self._confirm(g, target)

    def _confirm(self, g, target):
        dlg = Gtk.Dialog(title=_("Keep these display settings?"), transient_for=self, modal=True)
        dlg.set_name("bwmdr")
        dlg.set_keep_above(True)
        btn_revert = dlg.add_button(_("Revert"), Gtk.ResponseType.CANCEL)
        dlg.add_button(_("Keep"), Gtk.ResponseType.OK)
        btn_revert.grab_focus()
        box = dlg.get_content_area()
        box.set_border_width(10)
        box.set_spacing(6)
        title = Gtk.Label(xalign=0)
        title.set_markup("<b>%s</b>" % GLib.markup_escape_text(_("Keep these display settings?")))
        box.add(title)
        label = Gtk.Label(xalign=0)
        box.add(label)
        left = [CONFIRM_SECONDS]

        def tick():
            if left[0] <= 0:
                dlg.response(Gtk.ResponseType.CANCEL)
                return False
            # Conta de 15 a 1 (com 0 o diálogo já respondeu): o plural vale
            # para todos os números mostrados.
            label.set_text(P_("Reverting to the previous configuration in %d second.",
                              "Reverting to the previous configuration in %d seconds.", left[0]) % left[0])
            left[0] -= 1
            return True

        tick()
        timer = GLib.timeout_add_seconds(1, tick)
        dlg.show_all()
        _center_on_primary(dlg)
        self._confirming = True
        try:
            resp = dlg.run()
        finally:
            self._confirming = False
        if left[0] > 0:
            GLib.source_remove(timer)
        dlg.destroy()
        if resp == Gtk.ResponseType.OK:
            result = g.keep()
            if result != "kept":
                # O vigia já tinha revertido (a janela travou além do prazo).
                self.reload(self.selected)
                self._message(_("The confirmation came too late; the previous configuration was restored."),
                              error=True)
                return
            self.reload(self.selected)
            self._save_kept()
            self.st.save()
            self._fill_profiles()
            self._update_controls()
            self._message(_("Configuration kept and saved for this set of monitors."))
        else:
            result = g.revert()
            self.reload(self.selected)
            if result == "revert-failed":
                self._message(_("Could not restore the previous configuration automatically."), error=True)
            else:
                self._message(_("The previous configuration was restored."))

    def _save_kept(self):
        """Grava o que ficou: o perfil escolhido passa a ser o do conjunto;
        sem perfil escolhido, vira o perfil automático do conjunto."""
        pid = self._pending
        p = self.st.get(pid) if pid else None
        if p is not None:
            self.st.mark_applied(self.current, p, self.be.name)
        else:
            self.st.remember(self.current, session=self.be.name)

    # -- Identificar ----------------------------------------------------------

    def identify(self):
        for w in self.osd:
            w.destroy()
        self.osd = []
        display = Gdk.Display.get_default()
        mons = [display.get_monitor(i) for i in range(display.get_n_monitors())]
        try:
            gi.require_version("GtkLayerShell", "0.1")
            from gi.repository import GtkLayerShell
            layer = GtkLayerShell if GtkLayerShell.is_supported() else None
        except (ValueError, ImportError):
            layer = None
        for o in self.current.enabled():
            mon = None
            for m in mons:
                g = m.get_geometry()
                if (g.x, g.y) == (o.x, o.y):
                    mon = m
                    break
            w = Gtk.Window(type=Gtk.WindowType.POPUP if layer is None else Gtk.WindowType.TOPLEVEL)
            w.set_name("bwmdr-osd")
            box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
            box.set_border_width(18)
            big = Gtk.Label(label=o.name)
            big.get_style_context().add_class("big")
            box.add(big)
            box.add(Gtk.Label(label=o.label()))
            if o.mode:
                box.add(Gtk.Label(label="%d × %d @ %s" % (o.mode.width, o.mode.height, refresh_text(o.mode))))
            w.add(box)
            if layer is not None:
                layer.init_for_window(w)
                layer.set_layer(w, layer.Layer.OVERLAY)
                layer.set_namespace(w, "big-wm-display-identify")
                if mon is not None:
                    layer.set_monitor(w, mon)
            w.show_all()
            if layer is None and mon is not None:
                g = mon.get_geometry()
                ww, wh = w.get_size()
                w.move(g.x + (g.width - ww) // 2, g.y + (g.height - wh) // 2)
            self.osd.append(w)
        GLib.timeout_add_seconds(3, self._close_osd)

    def _close_osd(self):
        for w in self.osd:
            w.destroy()
        self.osd = []
        return False


def _center_on_primary(dlg):
    dlg.set_position(Gtk.WindowPosition.CENTER_ON_PARENT)


class Canvas(Gtk.DrawingArea):
    """Os monitores em escala, na posição real. Arrastar move o monitor (com
    encaixe nas bordas e alinhamentos); clicar escolhe; as setas do teclado
    movem 1 pixel (10 com Shift)."""

    MARGIN = 16
    STRIP = 44          # faixa de baixo com os monitores desligados

    def __init__(self, win):
        super().__init__()
        self.win = win
        self.set_can_focus(True)
        self.add_events(Gdk.EventMask.BUTTON_PRESS_MASK | Gdk.EventMask.BUTTON_RELEASE_MASK |
                        Gdk.EventMask.POINTER_MOTION_MASK | Gdk.EventMask.KEY_PRESS_MASK)
        self.connect("draw", self._draw)
        self.connect("button-press-event", self._press)
        self.connect("button-release-event", self._release)
        self.connect("motion-notify-event", self._motion)
        self.connect("size-allocate", lambda *_a: self.fit())
        self.scale = 0.05
        self.ox = self.oy = 0
        self.drag = None
        self.hits = []

    def fit(self):
        lay = self.win.edit
        if lay is None:
            return
        a = self.get_allocation()
        bx, by, bw, bh = model.bounding_box(lay)
        bw, bh = max(bw, 640), max(bh, 480)
        has_off = any(not o.enabled for o in lay.outputs)
        avail_h = a.height - 2 * self.MARGIN - (self.STRIP if has_off else 0)
        self.scale = max(0.01, min((a.width - 2 * self.MARGIN) / bw, avail_h / bh))
        bx, by, bw2, bh2 = model.bounding_box(lay)
        self.ox = (a.width - bw2 * self.scale) / 2 - bx * self.scale
        self.oy = self.MARGIN + (avail_h - bh2 * self.scale) / 2 - by * self.scale
        self.queue_draw()

    def to_screen(self, x, y):
        return (self.ox + x * self.scale, self.oy + y * self.scale)

    def _draw(self, _w, cr):
        p = self.win.palette
        a = self.get_allocation()
        _set(cr, p["canvas"])
        cr.paint()
        lay = self.win.edit
        self.hits = []
        if lay is None:
            return
        order = sorted(lay.outputs, key=lambda o: (o.name == self.win.selected, bool(o.mirror_of)))
        for o in order:
            if not o.enabled or o.mode is None:
                continue
            x, y = self.to_screen(o.x, o.y)
            w, h = o.logical_size()
            self._monitor(cr, o, x, y, w * self.scale, h * self.scale, True)
            self.hits.append((o.name, x, y, w * self.scale, h * self.scale))
        off = [o for o in lay.outputs if not o.enabled]
        if off:
            y = a.height - self.STRIP + 6
            x = self.MARGIN
            _set(cr, p["light"])
            cr.select_font_face("Sans", 0, 0)
            cr.set_font_size(11)
            cr.move_to(x, y + 12)
            text = _("Off:")
            cr.show_text(text)
            x += cr.text_extents(text).x_advance + 8
            for o in off:
                w = 90
                self._monitor(cr, o, x, y, w, 30, False)
                self.hits.append((o.name, x, y, w, 30))
                x += w + 8
        if self.drag and self.drag.get("guides"):
            _set(cr, "#ffd75a")
            cr.set_line_width(1)
            cr.set_dash([4, 3])
            for kind, v in self.drag["guides"]:
                if kind == "x":
                    sx, _sy = self.to_screen(v, 0)
                    cr.move_to(int(sx) + 0.5, 0)
                    cr.line_to(int(sx) + 0.5, a.height)
                else:
                    _sx, sy = self.to_screen(0, v)
                    cr.move_to(0, int(sy) + 0.5)
                    cr.line_to(a.width, int(sy) + 0.5)
            cr.stroke()
            cr.set_dash([])

    def _monitor(self, cr, o, x, y, w, h, on):
        p = self.win.palette
        sel = o.name == self.win.selected
        x, y, w, h = int(x), int(y), max(int(w), 8), max(int(h), 8)
        # moldura em relevo
        _set(cr, p["bg"])
        cr.rectangle(x, y, w, h)
        cr.fill()
        _set(cr, p["light"])
        cr.move_to(x + 0.5, y + h - 0.5)
        cr.line_to(x + 0.5, y + 0.5)
        cr.line_to(x + w - 0.5, y + 0.5)
        cr.set_line_width(1)
        cr.stroke()
        _set(cr, p["dark"])
        cr.move_to(x + w - 0.5, y + 0.5)
        cr.line_to(x + w - 0.5, y + h - 0.5)
        cr.line_to(x + 0.5, y + h - 0.5)
        cr.stroke()
        # tela
        b = 4 if w > 40 else 2
        if on:
            import cairo
            grad = cairo.LinearGradient(x, y, x + w, y + h)
            c1, c2 = _rgb(p["screen"]), _rgb(p["screen2"])
            grad.add_color_stop_rgb(0, *c1)
            grad.add_color_stop_rgb(1, *c2)
            cr.set_source(grad)
        else:
            _set(cr, p["screen_off"])
        cr.rectangle(x + b, y + b, w - 2 * b, h - 2 * b)
        cr.fill()
        if o.mirror_of:
            cr.set_source_rgba(1, 1, 1, 0.12)
            cr.rectangle(x + b, y + b, w - 2 * b, h - 2 * b)
            cr.fill()
        # topo da imagem (orientação): uma barra clara na borda de cima
        if on:
            cr.set_source_rgba(1, 1, 1, 0.55)
            t = o.transform % 4
            k = 3
            if t == 0:
                cr.rectangle(x + b, y + b, w - 2 * b, k)
            elif t == 1:
                cr.rectangle(x + w - b - k, y + b, k, h - 2 * b)
            elif t == 2:
                cr.rectangle(x + b, y + h - b - k, w - 2 * b, k)
            else:
                cr.rectangle(x + b, y + b, k, h - 2 * b)
            cr.fill()
        if sel:
            _set(cr, "#ffffff" if self.win.mode == "light" else "#f4e9b8")
            cr.set_line_width(2)
            cr.rectangle(x + 1, y + 1, w - 2, h - 2)
            cr.stroke()
        # textos
        cr.set_source_rgb(1, 1, 1)
        cr.select_font_face("Sans", 0, 1)
        lines = [o.name]
        if on:
            lines.append("%d×%d" % o.pixel_size())
            if abs(o.scale - 1) > 1e-3:
                lines[-1] += "  %d%%" % round(o.scale * 100)
            if o.primary:
                lines.append(_("primary"))
            if o.mirror_of:
                lines.append(_("mirrors %s") % o.mirror_of)
        size = max(8, min(14, h / 6))
        cr.set_font_size(size)
        total = len(lines) * (size + 3)
        ty = y + (h - total) / 2 + size
        for i, line in enumerate(lines):
            if i == 1:
                cr.select_font_face("Sans", 0, 0)
            ext = cr.text_extents(line)
            if ext.width > w - 2 * b - 4:
                continue
            cr.move_to(x + (w - ext.width) / 2, ty)
            cr.show_text(line)
            ty += size + 3

    def _hit(self, ex, ey):
        for name, x, y, w, h in reversed(self.hits):
            if x <= ex <= x + w and y <= ey <= y + h:
                return name
        return None

    def _press(self, _w, ev):
        self.grab_focus()
        name = self._hit(ev.x, ev.y)
        if name is None:
            return False
        if name != self.win.selected:
            self.win.select(name)
        o = self.win.edit.get(name)
        if ev.button == 1 and o.enabled and not o.mirror_of:
            self.drag = {"name": name, "x0": ev.x, "y0": ev.y, "ox": o.x, "oy": o.y, "guides": []}
        return True

    def _motion(self, _w, ev):
        if not self.drag:
            name = self._hit(ev.x, ev.y)
            o = self.win.edit.get(name) if name else None
            if o is not None and o.enabled and not o.mirror_of:
                self.win.hint.set_text(_("Drag to place; arrows move 1 pixel (Shift: 10)"))
            else:
                self.win.hint.set_text("")
            return False
        o = self.win.edit.get(self.drag["name"])
        nx = self.drag["ox"] + (ev.x - self.drag["x0"]) / self.scale
        ny = self.drag["oy"] + (ev.y - self.drag["y0"]) / self.scale
        w, h = o.logical_size()
        others = [p.rect() for p in self.win.edit.enabled() if p is not o and not p.mirror_of]
        sx, sy = model.snap((int(nx), int(ny), w, h), others, threshold=max(8, int(10 / self.scale)))
        guides = []
        for ox, oy, ow, oh in others:
            for v in (ox, ox + ow):
                if v in (sx, sx + w):
                    guides.append(("x", v))
            for v in (oy, oy + oh):
                if v in (sy, sy + h):
                    guides.append(("y", v))
        o.x, o.y = sx, sy
        self.drag["guides"] = guides
        model.sync_mirrors(self.win.edit)
        self.win.hint.set_text(_("%s at %d, %d") % (o.name, o.x, o.y))
        self.queue_draw()
        return True

    def _release(self, _w, _ev):
        if not self.drag:
            return False
        o = self.win.edit.get(self.drag["name"])
        others = [p.rect() for p in self.win.edit.enabled() if p is not o and not p.mirror_of]
        o.x, o.y = model.attach(o.rect(), others)
        self.drag = None
        model.normalize(self.win.edit)
        self.win.changed(refit=True)
        return True


def _rgb(hexcolor):
    h = hexcolor.lstrip("#")
    return tuple(int(h[i:i + 2], 16) / 255 for i in (0, 2, 4))


def _set(cr, hexcolor):
    cr.set_source_rgb(*_rgb(hexcolor))


def run(argv):
    GLib.set_prgname(APP_ID)
    GLib.set_application_name("Big WM Display Resolution")
    app = App()
    return app.run(argv)
