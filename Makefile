# SPDX-License-Identifier: GPL-2.0-or-later
#
# Big WM Display Resolution.
#
#   make                 compila o big-wm-display-helper (C: wayland-client, Xlib/XRandR)
#   make check           testes (pytest)
#   make po              atualiza o .pot e o pt_BR.po
#   make install DESTDIR=...

PREFIX     ?= /usr
SYSCONFDIR ?= /etc
BINDIR      = $(PREFIX)/bin
LIBDIR      = $(PREFIX)/lib/big-wm-display-resolution
DATADIR     = $(PREFIX)/share
PKGDATADIR  = $(DATADIR)/big-wm-display-resolution
LOCALEDIR   = $(DATADIR)/locale

CC         ?= cc
PKG_CONFIG ?= pkg-config
SCANNER    ?= wayland-scanner
LIBS        = wayland-client x11 xrandr
PROTO       = helper/wlr-output-management-unstable-v1.xml

INSTALL      = install
INSTALL_BIN  = $(INSTALL) -Dm755
INSTALL_DATA = $(INSTALL) -Dm644

.PHONY: all check po install clean

all: build/big-wm-display-helper

build/wlr-output-management-unstable-v1-client-protocol.h: $(PROTO)
	@mkdir -p build
	$(SCANNER) client-header $< $@

build/wlr-output-management-unstable-v1-protocol.c: $(PROTO)
	@mkdir -p build
	$(SCANNER) private-code $< $@

build/big-wm-display-helper: helper/big-wm-display-helper.c build/wlr-output-management-unstable-v1-client-protocol.h \
		build/wlr-output-management-unstable-v1-protocol.c
	$(CC) -std=gnu11 $(CPPFLAGS) $(CFLAGS) -Wall -Wextra -Ibuild $$($(PKG_CONFIG) --cflags $(LIBS)) \
		-o $@ helper/big-wm-display-helper.c build/wlr-output-management-unstable-v1-protocol.c \
		$(LDFLAGS) $$($(PKG_CONFIG) --libs $(LIBS))

check: all
	env -u DISPLAY -u WAYLAND_DISPLAY python3 -m pytest -q -p no:cacheprovider tests

# Fontes com texto traduzível: po/POTFILES (o teste tests/test_i18n.py
# confere que o .pot é o que estes arquivos dão hoje).
XGETTEXT_ARGS = -L Python --keyword=_ --keyword=N_ --keyword=P_:1,2 --keyword=ngettext:1,2 \
		--from-code=UTF-8 --add-comments=TRANSLATORS: --package-name=big-wm-display-resolution

po:
	xgettext $(XGETTEXT_ARGS) -f po/POTFILES -o po/big-wm-display-resolution.pot
	python3 po/make-pt_BR.py po/big-wm-display-resolution.pot po/pt_BR.po

install: all
	$(INSTALL_BIN) big-wm-display-resolution $(DESTDIR)$(BINDIR)/big-wm-display-resolution
	$(INSTALL_BIN) build/big-wm-display-helper $(DESTDIR)$(LIBDIR)/big-wm-display-helper
	for f in bigwmdisplay/*.py; do $(INSTALL_DATA) $$f $(DESTDIR)$(PKGDATADIR)/$$f; done
	$(INSTALL_DATA) data/org.bigwindowmaker.DisplayResolution.desktop \
		$(DESTDIR)$(DATADIR)/applications/org.bigwindowmaker.DisplayResolution.desktop
	$(INSTALL_DATA) data/big-wm-display-resolution-watch.desktop \
		$(DESTDIR)$(SYSCONFDIR)/xdg/autostart/big-wm-display-resolution-watch.desktop
	$(INSTALL_DATA) data/big-wm-display-resolution.svg \
		$(DESTDIR)$(DATADIR)/icons/hicolor/scalable/apps/big-wm-display-resolution.svg
	for po in po/*.po; do \
		l=$${po##*/}; l=$${l%.po}; \
		$(INSTALL) -d $(DESTDIR)$(LOCALEDIR)/$$l/LC_MESSAGES; \
		msgfmt -c -o $(DESTDIR)$(LOCALEDIR)/$$l/LC_MESSAGES/big-wm-display-resolution.mo $$po || exit 1; \
	done
	$(INSTALL_DATA) README.md $(DESTDIR)$(DATADIR)/doc/big-wm-display-resolution/README.md

clean:
	rm -f build/big-wm-display-helper build/wlr-output-management-unstable-v1-*
