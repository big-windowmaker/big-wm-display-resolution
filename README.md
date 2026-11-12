<p align="center">
  <img src="data/big-wm-display-resolution.svg" width="96" alt="Ícone do Big WM Display Resolution">
</p>

<h1 align="center">Big WM Display Resolution</h1>

<p align="center">
  <a href="https://github.com/big-windowmaker/big-wm-display-resolution/actions/workflows/ci.yml"><img src="https://github.com/big-windowmaker/big-wm-display-resolution/actions/workflows/ci.yml/badge.svg" alt="CI"></a>
  <img src="https://img.shields.io/badge/licen%C3%A7a-GPL--2.0--or--later-blue" alt="Licença GPL-2.0-or-later">
  <img src="https://img.shields.io/badge/X11-XRandR-2d85c6" alt="X11 (XRandR)">
  <img src="https://img.shields.io/badge/Wayland-wlr--output--management-2d85c6" alt="Wayland (wlr-output-management)">
</p>

<p align="center">
  <img src="https://raw.githubusercontent.com/big-windowmaker/.github/main/profile/images/em-breve-display-resolution.png" alt="Janela do Big WM Display Resolution com o desenho dos monitores, perfil, resolução, frequência, escala, orientação e posição" width="720">
</p>


Gerenciador de monitores das sessões do Big WindowMaker: X11 (Window Maker,
pelo XRandR) e Wayland (wlmaker, pelo `wlr-output-management`). No menu,
Configurações > Monitores.

- Monitores em escala e na posição real; arrastar com encaixe, coordenadas
  exatas, Identificar.
- Resolução e frequência só dos modos anunciados (a nativa marcada), escala
  (Wayland), orientação e reflexo, ligar/desligar, estender/espelhar,
  monitor principal (X11).
- Informações do EDID; identidade do monitor = fabricante + modelo + serial.
- VRR e HDR só como existem de verdade (a janela explica o porquê).
- Aplicar sempre pergunta "Manter estas configurações?" e volta sozinho em
  15 s — por um processo vigia separado, mesmo se a janela travar.
- Perfis em `~/.config/big-wm/display-resolution/profiles.json` (com
  `profiles.json.bak`), aplicados no login e quando o conjunto de monitores
  muda (eventos do XRandR / do compositor, sem polling). Um conjunto que é
  parte de um perfil (os monitores voltando um de cada vez) usa os lugares
  desse perfil; a janela aberta acompanha a chegada e a saída de monitores.

    big-wm-display-resolution              a janela
    big-wm-display-resolution --restore    aplica o perfil do conjunto conectado
    big-wm-display-resolution --watch      vigia de hotplug (autostart)
    big-wm-display-resolution --show       o que está conectado e o perfil que vale
    big-wm-display-resolution --profiles   lista os perfis

Documentação completa:
[docs/display-resolution.md](https://github.com/big-windowmaker/big-wm/blob/main/docs/display-resolution.md)
no repositório big-wm.

## Instalar

No Big WindowMaker ele vem com o `big-wm-session` e o `big-wm-wayland`. Para
compilar o pacote a partir deste repositório:

```sh
cd pkgbuild
BWMDR_SOURCE="git+file://$PWD/.." makepkg -si
```

Remover: `sudo pacman -R big-wm-display-resolution` (os perfis ficam em
`~/.config/big-wm/display-resolution/`).

## Desenvolvimento

```sh
make            # o helper (wayland-client, Xlib/XRandR)
make check      # pytest: modelo, perfis, reversão, migração, X11, tradução
make po         # atualiza o .pot e o pt_BR.po (po/make-pt_BR.py)
make install DESTDIR=/tmp/destino
```

Requisitos: Python 3 com PyGObject e pycairo, GTK 3, `wayland`, `libx11`,
`libxrandr`, `xorg-xrandr`, `hwdata`; para os testes, `python-pytest`.
Problemas e sugestões: [issues](https://github.com/big-windowmaker/big-wm-display-resolution/issues).

## Créditos

**Mantenedores do Big WindowMaker:** Rafael Ruscher <rruscher@gmail.com> e
Barnabé Di Kartola <barnabedikartola@gmail.com>.

**Agradecimentos especiais:** Alfredo Kojima (pelo
[Window Maker](https://www.windowmaker.org/)), Philipp Kaeser (pelo
[wlmaker](https://github.com/phkaeser/wlmaker)), Bruno Gonçalves (pelo
[BigLinux](https://www.biglinux.com.br/)) e Tales A. Mendonça (pela
BigCommunity).

Os nomes dos fabricantes vêm do `pnp.ids` do pacote `hwdata`.

## Licença

GPL-2.0-or-later — ver [LICENSE](LICENSE).
