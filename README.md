# Big WM Display Resolution

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

Documentação completa: `docs/display-resolution.md` no repositório big-wm.

Compilar e testar: `make && make check`; instalar: `make install DESTDIR=...`
(ou `pkgbuild/PKGBUILD`).
