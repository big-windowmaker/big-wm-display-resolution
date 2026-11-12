# SPDX-License-Identifier: GPL-2.0-or-later
"""Barras de rolagem no padrão do Window Maker (WINGs/WPrefs) e roda do
mouse que não muda valores por acidente.

O tema GTK do sistema (OneStepBack) já põe as setas no fim da barra, mas a
regra genérica "#bwmdr button" da janela também pegava os botões das setas
(padding de 8 pixels, altura mínima de 18): os botões ficavam mais largos
que a calha, desalinhados para a esquerda e soltos dela. A barra ainda era
"overlay" (some e flutua por cima do conteúdo). Aqui a barra é desenhada
como o WMScroller do WINGs (wscroller.c/widgets.c):

- 20 pixels de largura, contorno preto, calha pontilhada (cinza escuro e
  cinza do fundo alternados), botão deslizante em relevo com a covinha;
- vertical: as duas setas juntas EMBAIXO, "para cima" sobre "para baixo"
  (WMScrollView usa WSAMaxEnd); horizontal: as duas juntas à ESQUERDA,
  "para a esquerda" e depois "para a direita" (padrão WSAMinEnd);
- setas 9×9 copiadas dos XPM do WINGs; pressionado: fundo claro e a seta
  "hi" em cinza escuro; no limite (nada a rolar naquele sentido) a seta fica
  apagada; sem efeito de hover (o WINGs não tem).

A direção não muda: seta "para cima"/roda para cima levam ao começo, o
botão deslizante no alto é o começo do conteúdo.
"""

import os
import struct
import tempfile
import zlib
from urllib.parse import quote

# XPM do WINGs (widgets.c): '#' preto, '%' cinza escuro, ' ' branco,
# '.' cinza do fundo (aqui transparente).
ARROW_UP = (
    "....%....",
    "....#....",
    "...%#%...",
    "...###...",
    "..%###%..",
    "..#####..",
    ".%#####%.",
    ".#######.",
    "%#######%",
)
ARROW_LEFT = (
    "........%",
    "......%##",
    "....%####",
    "..%######",
    "%########",
    "..%######",
    "....%####",
    "......%##",
    "........%",
)
DIMPLE = (
    ".%###.",
    "%#%%%%",
    "#%%...",
    "#%..  ",
    "#%.   ",
    ".%.  .",
)


def _rgba(color, alpha=255):
    c = color.lstrip("#")
    return (int(c[0:2], 16), int(c[2:4], 16), int(c[4:6], 16), alpha)


def png(rows, colors):
    """PNG RGBA a partir de linhas de caracteres; colors: {char: (r,g,b,a)}."""
    h, w = len(rows), len(rows[0])
    raw = b"".join(b"\0" + b"".join(bytes(colors.get(ch, (0, 0, 0, 0))) for ch in row) for row in rows)

    def chunk(kind, data):
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF)

    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 6, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(raw, 9)) + chunk(b"IEND", b""))


def image_dir():
    """Onde gravar as imagens: o GTK 3 não carrega "data:" em url() do CSS
    (falha calada), então elas vão para arquivos no diretório de execução
    do usuário (tmpfs), regravados a cada abertura."""
    base = os.environ.get("XDG_RUNTIME_DIR")
    if not base or not os.path.isdir(base) or not os.access(base, os.W_OK):
        return tempfile.mkdtemp(prefix="big-wm-display-resolution-")
    path = os.path.join(base, "big-wm-display-resolution")
    os.makedirs(path, mode=0o700, exist_ok=True)
    return path


class Images:
    """Grava os PNG e devolve as URLs file:// para o CSS."""

    def __init__(self, directory, prefix):
        self.directory = directory
        self.prefix = prefix

    def url(self, name, rows, colors):
        path = os.path.join(self.directory, "%s-%s.png" % (self.prefix, name))
        tmp = path + ".tmp"
        with open(tmp, "wb") as f:
            f.write(png(rows, colors))
        os.replace(tmp, path)
        return "file://" + quote(path)


def _flip_v(rows):
    return tuple(reversed(rows))


def _flip_h(rows):
    return tuple(r[::-1] for r in rows)


def complete(palette):
    """Cores próprias da barra a partir da paleta da janela: a seta é preta
    no claro (como no WINGs) e da cor do texto no escuro; contorno preto."""
    p = dict(palette)
    p.setdefault("arrow", "#000000" if p.get("fg", "#000000") == "#000000" else p["fg"])
    p.setdefault("edge", "#000000")
    p.setdefault("pressed", p["light"])
    return p


def arrows(palette, images):
    """URLs das setas: {(direção, estado): url}; estado normal/pressed/disabled."""
    palette = complete(palette)
    ink, mid = palette["arrow"], palette["dark"]
    normal = {"#": _rgba(ink), "%": _rgba(mid)}
    # "hi" do WINGs: a seta inteira em cinza escuro sobre o botão claro
    pressed = {"#": _rgba(mid), "%": _rgba(mid)}
    disabled = {"#": _rgba(palette["disabled"]), "%": _rgba(palette["disabled"], 128)}
    shapes = {"up": ARROW_UP, "down": _flip_v(ARROW_UP),
              "left": ARROW_LEFT, "right": _flip_h(ARROW_LEFT)}
    out = {}
    for name, rows in shapes.items():
        for state, colors in (("normal", normal), ("pressed", pressed), ("disabled", disabled)):
            out[(name, state)] = images.url("%s-%s" % (name, state), rows, colors)
    return out


def stipple(palette, images):
    """Calha pontilhada 2×2 (stippleGC do WINGs: cinza escuro sobre o fundo)."""
    return images.url("stipple", ("ab", "ba"), {"a": _rgba(palette["dark"]), "b": _rgba(palette["bg"])})


def dimple(palette, images):
    palette = complete(palette)
    return images.url("dimple", DIMPLE, {"#": _rgba(palette["arrow"]), "%": _rgba(palette["dark"]),
                             " ": _rgba(palette["light"])})


CSS = """
#bwmdr scrollbar, #bwmdr scrollbar.overlay-indicator {{
  background-color: {bg}; background-image: none; border-radius: 0;
  border: 1px solid {edge}; padding: 1px; opacity: 1;
}}
#bwmdr scrollbar.vertical {{
  -GtkScrollbar-has-backward-stepper: false;
  -GtkScrollbar-has-secondary-backward-stepper: true;
  -GtkScrollbar-has-forward-stepper: true;
  -GtkScrollbar-has-secondary-forward-stepper: false;
}}
#bwmdr scrollbar.horizontal {{
  -GtkScrollbar-has-backward-stepper: true;
  -GtkScrollbar-has-secondary-backward-stepper: false;
  -GtkScrollbar-has-forward-stepper: false;
  -GtkScrollbar-has-secondary-forward-stepper: true;
}}
#bwmdr scrollbar contents {{ margin: 0; padding: 0; }}
#bwmdr scrollbar trough {{
  background-color: {dark}; background-image: url("{stipple}"); background-repeat: repeat;
  border: none; border-radius: 0; margin: 0; padding: 0; min-width: 16px; min-height: 16px;
}}
#bwmdr scrollbar slider, #bwmdr scrollbar slider:hover, #bwmdr scrollbar slider:active {{
  background-color: {bg}; background-image: url("{dimple}");
  background-repeat: no-repeat; background-position: center center;
  border-radius: 0; border-style: solid; border-width: 1px;
  border-color: {light} {edge} {edge} {light};
  box-shadow: inset -1px -1px 0 {dark};
  margin: 0; min-width: 14px; min-height: 14px; transition: none;
}}
#bwmdr scrollbar.vertical slider {{ min-height: 16px; }}
#bwmdr scrollbar.horizontal slider {{ min-width: 16px; }}
#bwmdr scrollbar button, #bwmdr scrollbar button:hover {{
  background-color: {bg}; background-image: none; color: {arrow};
  border-radius: 0; border-style: solid; border-width: 1px;
  border-color: {light} {edge} {edge} {light};
  box-shadow: inset -1px -1px 0 {dark};
  padding: 0; margin: 0; min-width: 14px; min-height: 14px; outline: none;
  -gtk-icon-shadow: none; transition: none;
}}
#bwmdr scrollbar.vertical button.up {{ margin-top: 1px; }}
#bwmdr scrollbar.vertical button.down {{ margin-top: 1px; }}
#bwmdr scrollbar.horizontal button.up {{ margin-right: 1px; }}
#bwmdr scrollbar.horizontal button.down {{ margin-right: 0; }}
#bwmdr scrollbar.horizontal trough {{ margin-left: 1px; }}
#bwmdr scrollbar button:active {{
  background-color: {pressed}; border-color: {light} {edge} {edge} {light};
  box-shadow: inset -1px -1px 0 {dark};
}}
#bwmdr scrollbar button:disabled {{ background-color: {bg}; }}
#bwmdr scrollbar.vertical button.up {{ -gtk-icon-source: url("{up}"); }}
#bwmdr scrollbar.vertical button.up:active {{ -gtk-icon-source: url("{up_pressed}"); }}
#bwmdr scrollbar.vertical button.up:disabled {{ -gtk-icon-source: url("{up_disabled}"); }}
#bwmdr scrollbar.vertical button.down {{ -gtk-icon-source: url("{down}"); }}
#bwmdr scrollbar.vertical button.down:active {{ -gtk-icon-source: url("{down_pressed}"); }}
#bwmdr scrollbar.vertical button.down:disabled {{ -gtk-icon-source: url("{down_disabled}"); }}
#bwmdr scrollbar.horizontal button.up {{ -gtk-icon-source: url("{left}"); }}
#bwmdr scrollbar.horizontal button.up:active {{ -gtk-icon-source: url("{left_pressed}"); }}
#bwmdr scrollbar.horizontal button.up:disabled {{ -gtk-icon-source: url("{left_disabled}"); }}
#bwmdr scrollbar.horizontal button.down {{ -gtk-icon-source: url("{right}"); }}
#bwmdr scrollbar.horizontal button.down:active {{ -gtk-icon-source: url("{right_pressed}"); }}
#bwmdr scrollbar.horizontal button.down:disabled {{ -gtk-icon-source: url("{right_disabled}"); }}
#bwmdr scrolledwindow junction {{ background-color: {bg}; background-image: none; border: none; }}
"""


def css(palette, mode="light", directory=None):
    """CSS das barras de rolagem para a paleta (chaves de PALETTES em ui.py);
    as imagens são gravadas em directory (padrão: image_dir())."""
    images = Images(directory or image_dir(), mode)
    p = complete(palette)
    vals = dict(p, stipple=stipple(p, images), dimple=dimple(p, images))
    for (name, state), url in arrows(p, images).items():
        vals[name if state == "normal" else "%s_%s" % (name, state)] = url
    return CSS.format(**vals)


# -- Roda do mouse ---------------------------------------------------------

def guard_wheel(widget):
    """A roda só muda o valor de um campo (SpinButton/ComboBox) que tem o
    foco; sem foco, o evento sobe para a janela com rolagem, que rola a
    página. Antes, rolar o formulário com o ponteiro passando sobre "Posição"
    ou "Resolução" mudava o monitor sem querer."""
    widget.connect("scroll-event", _on_scroll)


def _on_scroll(widget, _event):
    if _focused(widget):
        return False
    # interrompe o tratamento do próprio campo e deixa o evento propagar
    widget.stop_emission_by_name("scroll-event")
    return False


def _focused(widget):
    """O campo (ou um filho dele, como o botão interno do ComboBox) tem o foco."""
    top = widget.get_toplevel()
    focus = top.get_focus() if hasattr(top, "get_focus") else None
    return focus is not None and (focus is widget or focus.is_ancestor(widget))
