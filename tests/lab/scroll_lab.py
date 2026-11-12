#!/usr/bin/python3
# SPDX-License-Identifier: GPL-2.0-or-later
"""Laboratório da rolagem (precisa de um X, p.ex. um Xvfb: NUNCA a sessão
real, a janela não aplica nada, mas lê os monitores). Abre a janela de
verdade, injeta eventos de roda (passos discretos e "touchpad" com deltas
suaves, vertical e horizontal) e teclado, confere o resultado e grava
capturas em DIR:

    DISPLAY=:N python3 tests/lab/scroll_lab.py DIR [light|dark]

Sai com 1 se alguma verificação falhar.
"""

import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)

import gi  # noqa: E402

gi.require_version("Gtk", "3.0")
gi.require_version("Gdk", "3.0")
from gi.repository import Gdk, Gio, GLib, Gtk  # noqa: E402

from bigwmdisplay import ui  # noqa: E402

out = sys.argv[1]
mode = sys.argv[2] if len(sys.argv) > 2 else "light"
ui.theme_mode = lambda: mode          # sem big-wm-theme no laboratório
os.makedirs(out, exist_ok=True)
fails = []


def check(cond, what):
    print(("ok   " if cond else "FAIL ") + what)
    if not cond:
        fails.append(what)


def pump(n=30, ms=0):
    """Processa os eventos; ms > 0 espera também as animações da rolagem."""
    for _ in range(n):
        while Gtk.events_pending():
            Gtk.main_iteration_do(False)
    if ms:
        done = []
        GLib.timeout_add(ms, lambda: done.append(1))
        while not done:
            Gtk.main_iteration_do(True)


def scroll(widget, direction=Gdk.ScrollDirection.DOWN, dx=0.0, dy=0.0):
    """Leva o ponteiro ao meio do widget e entrega um GdkEventScroll à janela
    GDK que está sob ele, como faria o X: o evento passa pelo widget e sobe
    aos pais se ninguém tratar."""
    seat = Gdk.Display.get_default().get_default_seat()
    ptr = seat.get_pointer()
    top = widget.get_toplevel()
    wx, wy = widget.translate_coordinates(top, widget.get_allocated_width() // 2,
                                          widget.get_allocated_height() // 2)
    ox, oy = top.get_window().get_origin()[1:]
    ptr.warp(top.get_screen(), ox + wx, oy + wy)
    pump()
    win, x, y = ptr.get_window_at_position()
    ev = Gdk.Event.new(Gdk.EventType.SCROLL)
    ev.scroll.window = win
    ev.scroll.send_event = 1
    ev.scroll.direction = direction
    ev.scroll.delta_x, ev.scroll.delta_y = dx, dy
    ev.scroll.time = Gtk.get_current_event_time()
    ev.scroll.x, ev.scroll.y = x, y
    ev.scroll.x_root, ev.scroll.y_root = ox + wx, oy + wy
    ev.set_device(ptr)
    ev.set_source_device(ptr)
    if os.environ.get("SCROLL_LAB_DEBUG"):
        print("  evento em", Gtk.get_event_widget(ev), "para", widget)
    Gtk.main_do_event(ev)
    pump(ms=400)


def shot(name):
    pump()
    w = app.window
    gw = w.get_window()
    pb = Gdk.pixbuf_get_from_window(gw, 0, 0, gw.get_width(), gw.get_height())
    pb.savev(os.path.join(out, "%s-%s.png" % (mode, name)), "png", [], [])


class LabApp(ui.App):
    def do_activate(self):
        ui.App.do_activate(self)
        GLib.idle_add(run)


def run():
    win = app.window
    win.resize(820, 560)              # menor que o conteúdo: há rolagem
    pump(60)
    sc = win.get_child().get_children()[0]
    check(isinstance(sc, Gtk.ScrolledWindow), "a área principal é um GtkScrolledWindow")
    check(not sc.get_overlay_scrolling(), "barra de rolagem fixa (não overlay)")
    vadj = sc.get_vadjustment()
    check(vadj.get_upper() > vadj.get_page_size(), "há o que rolar (upper %d > página %d)"
          % (vadj.get_upper(), vadj.get_page_size()))
    bar = sc.get_vscrollbar()
    check(bar.get_visible() and bar.get_allocated_width() >= 18,
          "barra vertical visível com %d px (WINGs: 20)" % bar.get_allocated_width())
    shot("top")

    # roda (passo discreto) sobre o campo X sem foco: rola a página, X não muda.
    # Primeiro deixa X à vista, no meio da rolagem (dá para rolar nos dois sentidos)
    _, y = win.spin_x.translate_coordinates(sc.get_child().get_child(), 0, 0)
    vadj.set_value(min(y - vadj.get_page_size() / 2, vadj.get_upper() - vadj.get_page_size() - 40))
    win.set_focus(None)
    pump(ms=200)
    x0, top0 = win.spin_x.get_value(), vadj.get_value()
    scroll(win.spin_x, Gdk.ScrollDirection.DOWN)
    check(win.spin_x.get_value() == x0, "roda sobre X sem foco não muda o valor (%g)" % win.spin_x.get_value())
    check(vadj.get_value() > top0, "roda para baixo sobre X sem foco rola a página para baixo")
    # touchpad: deltas suaves
    v1 = vadj.get_value()
    scroll(win.spin_x, Gdk.ScrollDirection.SMOOTH, dy=-1.0)
    check(win.spin_x.get_value() == x0, "touchpad (delta) sobre X sem foco não muda o valor")
    check(vadj.get_value() < v1, "touchpad para cima rola a página para cima")
    # combo sem foco
    res0 = win.res_combo.get_active()
    scroll(win.res_combo, Gdk.ScrollDirection.DOWN)
    check(win.res_combo.get_active() == res0, "roda sobre Resolução sem foco não troca o modo")

    # com foco, a roda volta a mudar o valor e para cima = aumentar
    sens = win.spin_x.get_sensitive()
    win.spin_x.set_sensitive(True)
    win.spin_x.grab_focus()
    pump()
    v2 = vadj.get_value()
    scroll(win.spin_x, Gdk.ScrollDirection.UP)
    check(win.spin_x.get_value() == x0 + 1, "roda para cima sobre X com foco aumenta 1 (%g)" % win.spin_x.get_value())
    check(vadj.get_value() == v2, "com foco no X a página não rola")
    win.spin_x.set_value(x0)
    win.spin_x.set_sensitive(sens)

    # horizontal: a página não tem barra horizontal (política NEVER) e o
    # gesto lateral não pode mexer no valor nem rolar na vertical
    win.set_focus(None)
    pump()
    v3 = vadj.get_value()
    scroll(win.spin_x, Gdk.ScrollDirection.SMOOTH, dx=2.0)
    check(win.spin_x.get_value() == x0 and vadj.get_value() == v3,
          "gesto horizontal não muda X nem a rolagem vertical")

    # teclado: Tab até um campo fora da vista rola até ele
    vadj.set_value(0)
    pump()
    win.spin_y.set_sensitive(True)
    win.spin_y.grab_focus()
    pump(60)
    alloc = win.spin_y.translate_coordinates(sc, 0, 0)
    vis = alloc is not None and 0 <= alloc[1] <= sc.get_allocated_height() - win.spin_y.get_allocated_height()
    check(vis, "foco por teclado leva a página até o campo Y (y=%s)" % (alloc and alloc[1]))

    # setas: no começo "para cima" apagada; botões e calha alinhados
    vadj.set_value(vadj.get_upper())
    pump()
    shot("bottom")
    vadj.set_value(vadj.get_lower() + (vadj.get_upper() - vadj.get_page_size()) / 2)
    pump()
    shot("middle")
    # janela de demonstração com as duas barras (a página só rola na vertical)
    win.hide()
    demo = Gtk.Window(title="scroll-demo")
    demo.set_name("bwmdr")
    sw = Gtk.ScrolledWindow()
    sw.set_overlay_scrolling(False)
    sw.set_policy(Gtk.PolicyType.ALWAYS, Gtk.PolicyType.ALWAYS)
    area = Gtk.DrawingArea()
    area.set_size_request(900, 900)
    sw.add(area)
    demo.add(sw)
    demo.resize(260, 200)
    demo.show_all()
    pump(60)
    sw.get_hadjustment().set_value(200)
    sw.get_vadjustment().set_value(200)
    pump(30)
    gw = demo.get_window()
    pb = Gdk.pixbuf_get_from_window(gw, 0, 0, gw.get_width(), gw.get_height())
    pb.savev(os.path.join(out, "%s-both-bars.png" % mode), "png", [], [])
    h0 = sw.get_hadjustment().get_value()
    scroll(sw, Gdk.ScrollDirection.SMOOTH, dx=1.0)
    check(sw.get_hadjustment().get_value() > h0, "touchpad para a direita rola para a direita")
    h1 = sw.get_hadjustment().get_value()
    scroll(sw, Gdk.ScrollDirection.LEFT)
    check(sw.get_hadjustment().get_value() < h1, "roda lateral para a esquerda rola para a esquerda")
    v4 = sw.get_vadjustment().get_value()
    scroll(sw, Gdk.ScrollDirection.DOWN)
    check(sw.get_vadjustment().get_value() > v4, "roda para baixo rola para baixo")
    demo.destroy()
    print("%d falha(s)" % len(fails))
    app.quit()
    return False


app = LabApp()
app.set_flags(Gio.ApplicationFlags.NON_UNIQUE)
app.run([])
sys.exit(1 if fails else 0)
