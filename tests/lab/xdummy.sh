#!/bin/bash
# SPDX-License-Identifier: GPL-2.0-or-later
#
# Laboratório X11 com saídas RandR de verdade: Xorg sem root com o driver
# dummy (xf86-video-dummy 0.4: 16 saídas DUMMYn, modos reais, sem tocar no
# hardware nem nos terminais). Uso:
#
#   tests/lab/xdummy.sh DIR_DO_DRIVER :NUMERO
#
# DIR_DO_DRIVER é o usr/lib/xorg/modules extraído do pacote
# xf86-video-dummy (não precisa instalar: pacman -Sp mostra a URL; confira
# a assinatura com gpgv --keyring /etc/pacman.d/gnupg/pubring.gpg).
# "Conectar" um monitor: xrandr --addmode DUMMY2 1280x1024 e ligar um modo
# nele (a saída passa a "connected" e o XRandR avisa os clientes).
set -eu
modules=${1:?uso: xdummy.sh DIR_DO_DRIVER :N}
dpy=${2:?uso: xdummy.sh DIR_DO_DRIVER :N}
dir=$(mktemp -d)
cat >"$dir/xorg.conf" <<CONF
Section "Files"
  ModulePath "$modules"
  ModulePath "/usr/lib/xorg/modules"
EndSection
Section "ServerFlags"
  Option "AutoAddDevices" "false"
  Option "AutoAddGPU" "false"
  Option "AllowMouseOpenFail" "true"
EndSection
Section "Device"
  Identifier "d"
  Driver "dummy"
  VideoRam 256000
EndSection
Section "Monitor"
  Identifier "m"
  HorizSync 5.0-1000.0
  VertRefresh 5.0-200.0
EndSection
Section "Screen"
  Identifier "s"
  Device "d"
  Monitor "m"
  DefaultDepth 24
  SubSection "Display"
    Depth 24
    Virtual 8192 4096
  EndSubSection
EndSection
CONF
/usr/lib/Xorg "$dpy" -config "$dir/xorg.conf" -configdir "$dir/none" -logfile "$dir/Xorg.log" \
	-nolisten tcp -noreset >"$dir/out.log" 2>&1 &
echo "$!" >"$dir/pid"
echo "$dir"
