// SPDX-License-Identifier: GPL-2.0-or-later
//
// big-wm-display-helper: o lado "protocolo" do Big WM Display Resolution.
//
//   wl-dump                 estado dos monitores pelo wlr-output-management
//                           (JSON na saída padrão)
//   wl-apply [--test]       aplica (ou só testa) a configuração lida da
//                           entrada padrão, uma linha por monitor:
//                           nome<TAB>ligado<TAB>largura<TAB>altura<TAB>mHz
//                           <TAB>x<TAB>y<TAB>transformação<TAB>escala<TAB>vrr
//                           (vrr: 0, 1 ou "-" para não mexer)
//   wl-watch [--run-now] -- COMANDO...
//   x11-watch [--run-now] -- COMANDO...
//                           vigia a chegada e a saída de monitores (eventos
//                           do compositor ou do XRandR, sem polling) e
//                           executa COMANDO quando o conjunto muda
//   wl-watch --print | x11-watch --print
//                           o mesmo, mas escreve o conjunto novo (uma linha)
//                           na saída padrão, para a janela; termina junto
//                           com o processo pai
//   x11-outputs             saídas conectadas e o EDID (testes)
//
// No Wayland a configuração só passa pelo compositor (nunca xrandr no
// XWayland). Os vigias ficam bloqueados no poll() esperando eventos.

#define _GNU_SOURCE
#include <errno.h>
#include <poll.h>
#include <signal.h>
#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/prctl.h>
#include <sys/wait.h>
#include <time.h>
#include <unistd.h>

#include <wayland-client.h>

#include <X11/Xatom.h>
#include <X11/Xlib.h>
#include <X11/extensions/Xrandr.h>

#include "wlr-output-management-unstable-v1-client-protocol.h"

#define DEBOUNCE_MS 800

/* ---------------------------------------------------------------- util -- */

static void *xcalloc(size_t n, size_t s)
{
    void *p = calloc(n, s);
    if (!p) {
        perror("calloc");
        exit(70);
    }
    return p;
}

static void set_str(char **dst, const char *src)
{
    free(*dst);
    *dst = strdup(src ? src : "");
}

static void json_str(FILE *f, const char *s)
{
    fputc('"', f);
    for (const unsigned char *p = (const unsigned char *)(s ? s : ""); *p; p++) {
        switch (*p) {
        case '"': fputs("\\\"", f); break;
        case '\\': fputs("\\\\", f); break;
        case '\n': fputs("\\n", f); break;
        case '\t': fputs("\\t", f); break;
        default:
            if (*p < 0x20) fprintf(f, "\\u%04x", *p);
            else fputc(*p, f);
        }
    }
    fputc('"', f);
}

static long long now_ms(void)
{
    struct timespec ts;
    clock_gettime(CLOCK_MONOTONIC, &ts);
    return (long long)ts.tv_sec * 1000 + ts.tv_nsec / 1000000;
}

static volatile sig_atomic_t quit;

static void on_signal(int sig)
{
    (void)sig;
    quit = 1;
}

// Executa o comando e espera terminar (os eventos ficam na fila enquanto
// isso; o próximo conjunto é comparado depois).
static bool print_mode;

static void run_command(char **argv, const char *signature)
{
    if (print_mode) {
        // A janela fechou o pipe: não há mais quem avisar.
        if (printf("%s\n", signature) < 0 || fflush(stdout) != 0) quit = 1;
        return;
    }
    pid_t pid = fork();
    if (pid == 0) {
        setenv("BIGWM_DISPLAY_SIGNATURE", signature, 1);
        execvp(argv[0], argv);
        perror(argv[0]);
        _exit(127);
    }
    if (pid > 0) {
        int status;
        while (waitpid(pid, &status, 0) < 0 && errno == EINTR) {
        }
    }
}

/* ------------------------------------------------------------- wayland -- */

struct mode {
    struct zwlr_output_mode_v1 *obj;
    struct head *head;
    int32_t width, height, refresh;
    bool preferred;
    struct wl_list link;
};

struct head {
    struct zwlr_output_head_v1 *obj;
    char *name, *description, *make, *model, *serial;
    int32_t phys_width, phys_height;
    bool enabled;
    struct mode *current;
    int32_t x, y, transform;
    double scale;
    int adaptive_sync;          // -1: o compositor não informa
    struct wl_list modes;
    struct wl_list link;
};

struct wl_state {
    struct wl_display *display;
    struct wl_registry *registry;
    struct zwlr_output_manager_v1 *manager;
    uint32_t manager_version;
    uint32_t serial;
    bool done;                  // recebeu "done" depois da última mudança
    int done_count;
    struct wl_list heads;
    int result;                 // 0 esperando, 1 ok, 2 falhou, 3 cancelado
};

static void mode_size(void *data, struct zwlr_output_mode_v1 *m, int32_t w, int32_t h)
{
    (void)m;
    struct mode *mode = data;
    mode->width = w;
    mode->height = h;
}

static void mode_refresh(void *data, struct zwlr_output_mode_v1 *m, int32_t r)
{
    (void)m;
    ((struct mode *)data)->refresh = r;
}

static void mode_preferred(void *data, struct zwlr_output_mode_v1 *m)
{
    (void)m;
    ((struct mode *)data)->preferred = true;
}

static void mode_finished(void *data, struct zwlr_output_mode_v1 *m)
{
    struct mode *mode = data;
    if (mode->head && mode->head->current == mode) mode->head->current = NULL;
    wl_list_remove(&mode->link);
    if (zwlr_output_mode_v1_get_version(m) >= ZWLR_OUTPUT_MODE_V1_RELEASE_SINCE_VERSION) {
        zwlr_output_mode_v1_release(m);
    } else {
        zwlr_output_mode_v1_destroy(m);
    }
    free(mode);
}

static const struct zwlr_output_mode_v1_listener mode_listener = {
    .size = mode_size,
    .refresh = mode_refresh,
    .preferred = mode_preferred,
    .finished = mode_finished,
};

static void head_name(void *data, struct zwlr_output_head_v1 *h, const char *s)
{
    (void)h;
    set_str(&((struct head *)data)->name, s);
}

static void head_description(void *data, struct zwlr_output_head_v1 *h, const char *s)
{
    (void)h;
    set_str(&((struct head *)data)->description, s);
}

static void head_physical_size(void *data, struct zwlr_output_head_v1 *h, int32_t w, int32_t ht)
{
    (void)h;
    struct head *head = data;
    head->phys_width = w;
    head->phys_height = ht;
}

static void head_mode(void *data, struct zwlr_output_head_v1 *h, struct zwlr_output_mode_v1 *m)
{
    (void)h;
    struct head *head = data;
    struct mode *mode = xcalloc(1, sizeof(*mode));
    mode->obj = m;
    mode->head = head;
    wl_list_insert(head->modes.prev, &mode->link);
    zwlr_output_mode_v1_add_listener(m, &mode_listener, mode);
}

static void head_enabled(void *data, struct zwlr_output_head_v1 *h, int32_t enabled)
{
    (void)h;
    struct head *head = data;
    head->enabled = enabled;
    if (!enabled) head->current = NULL;
}

static void head_current_mode(void *data, struct zwlr_output_head_v1 *h, struct zwlr_output_mode_v1 *m)
{
    (void)h;
    struct head *head = data;
    struct mode *mode;
    wl_list_for_each(mode, &head->modes, link) {
        if (mode->obj == m) head->current = mode;
    }
}

static void head_position(void *data, struct zwlr_output_head_v1 *h, int32_t x, int32_t y)
{
    (void)h;
    struct head *head = data;
    head->x = x;
    head->y = y;
}

static void head_transform(void *data, struct zwlr_output_head_v1 *h, int32_t t)
{
    (void)h;
    ((struct head *)data)->transform = t;
}

static void head_scale(void *data, struct zwlr_output_head_v1 *h, wl_fixed_t s)
{
    (void)h;
    ((struct head *)data)->scale = wl_fixed_to_double(s);
}

static void head_free(struct head *head)
{
    struct mode *mode, *tmp;
    wl_list_for_each_safe(mode, tmp, &head->modes, link) {
        wl_list_remove(&mode->link);
        zwlr_output_mode_v1_destroy(mode->obj);
        free(mode);
    }
    wl_list_remove(&head->link);
    free(head->name);
    free(head->description);
    free(head->make);
    free(head->model);
    free(head->serial);
    free(head);
}

static void head_finished(void *data, struct zwlr_output_head_v1 *h)
{
    struct head *head = data;
    if (zwlr_output_head_v1_get_version(h) >= ZWLR_OUTPUT_HEAD_V1_RELEASE_SINCE_VERSION) {
        zwlr_output_head_v1_release(h);
    } else {
        zwlr_output_head_v1_destroy(h);
    }
    head_free(head);
}

static void head_make(void *data, struct zwlr_output_head_v1 *h, const char *s)
{
    (void)h;
    set_str(&((struct head *)data)->make, s);
}

static void head_model(void *data, struct zwlr_output_head_v1 *h, const char *s)
{
    (void)h;
    set_str(&((struct head *)data)->model, s);
}

static void head_serial(void *data, struct zwlr_output_head_v1 *h, const char *s)
{
    (void)h;
    set_str(&((struct head *)data)->serial, s);
}

static void head_adaptive_sync(void *data, struct zwlr_output_head_v1 *h, uint32_t state)
{
    (void)h;
    ((struct head *)data)->adaptive_sync = state == ZWLR_OUTPUT_HEAD_V1_ADAPTIVE_SYNC_STATE_ENABLED;
}

static const struct zwlr_output_head_v1_listener head_listener = {
    .name = head_name,
    .description = head_description,
    .physical_size = head_physical_size,
    .mode = head_mode,
    .enabled = head_enabled,
    .current_mode = head_current_mode,
    .position = head_position,
    .transform = head_transform,
    .scale = head_scale,
    .finished = head_finished,
    .make = head_make,
    .model = head_model,
    .serial_number = head_serial,
    .adaptive_sync = head_adaptive_sync,
};

static void manager_head(void *data, struct zwlr_output_manager_v1 *m, struct zwlr_output_head_v1 *h)
{
    (void)m;
    struct wl_state *st = data;
    struct head *head = xcalloc(1, sizeof(*head));
    head->obj = h;
    head->scale = 1.0;
    head->adaptive_sync = -1;
    wl_list_init(&head->modes);
    wl_list_insert(st->heads.prev, &head->link);
    zwlr_output_head_v1_add_listener(h, &head_listener, head);
    st->done = false;
}

static void manager_done(void *data, struct zwlr_output_manager_v1 *m, uint32_t serial)
{
    (void)m;
    struct wl_state *st = data;
    st->serial = serial;
    st->done = true;
    st->done_count++;
}

static void manager_finished(void *data, struct zwlr_output_manager_v1 *m)
{
    (void)m;
    ((struct wl_state *)data)->manager = NULL;
}

static const struct zwlr_output_manager_v1_listener manager_listener = {
    .head = manager_head,
    .done = manager_done,
    .finished = manager_finished,
};

static void registry_global(void *data, struct wl_registry *r, uint32_t name,
                            const char *iface, uint32_t version)
{
    struct wl_state *st = data;
    if (strcmp(iface, zwlr_output_manager_v1_interface.name) == 0) {
        st->manager_version = version < 4 ? version : 4;
        st->manager = wl_registry_bind(r, name, &zwlr_output_manager_v1_interface,
                                       st->manager_version);
        zwlr_output_manager_v1_add_listener(st->manager, &manager_listener, st);
    }
}

static void registry_global_remove(void *data, struct wl_registry *r, uint32_t name)
{
    (void)data;
    (void)r;
    (void)name;
}

static const struct wl_registry_listener registry_listener = {
    .global = registry_global,
    .global_remove = registry_global_remove,
};

static int wl_connect(struct wl_state *st)
{
    memset(st, 0, sizeof(*st));
    wl_list_init(&st->heads);
    st->display = wl_display_connect(NULL);
    if (!st->display) {
        fprintf(stderr, "sem conexão com o compositor Wayland\n");
        return 3;
    }
    st->registry = wl_display_get_registry(st->display);
    wl_registry_add_listener(st->registry, &registry_listener, st);
    if (wl_display_roundtrip(st->display) < 0) return 3;
    if (!st->manager) {
        fprintf(stderr, "o compositor não oferece o wlr-output-management\n");
        return 4;
    }
    while (!st->done) {
        if (wl_display_dispatch(st->display) < 0) return 3;
    }
    return 0;
}

static void dump_heads(struct wl_state *st, FILE *f)
{
    fprintf(f, "{\"backend\":\"wayland\",\"serial\":%u,\"manager_version\":%u,\"heads\":[",
            st->serial, st->manager_version);
    struct head *head;
    bool first = true;
    wl_list_for_each(head, &st->heads, link) {
        fputs(first ? "\n {" : ",\n {", f);
        first = false;
        fputs("\"name\":", f);
        json_str(f, head->name);
        fputs(",\"description\":", f);
        json_str(f, head->description);
        fputs(",\"make\":", f);
        json_str(f, head->make);
        fputs(",\"model\":", f);
        json_str(f, head->model);
        fputs(",\"serial\":", f);
        json_str(f, head->serial);
        fprintf(f, ",\"physical\":[%d,%d],\"enabled\":%s,\"x\":%d,\"y\":%d,"
                "\"transform\":%d,\"scale\":%.6f,\"adaptive_sync\":%d,\"current\":",
                head->phys_width, head->phys_height, head->enabled ? "true" : "false",
                head->x, head->y, head->transform, head->scale, head->adaptive_sync);
        if (head->current) {
            fprintf(f, "[%d,%d,%d]", head->current->width, head->current->height,
                    head->current->refresh);
        } else {
            fputs("null", f);
        }
        fputs(",\"modes\":[", f);
        struct mode *mode;
        bool mfirst = true;
        wl_list_for_each(mode, &head->modes, link) {
            fprintf(f, "%s[%d,%d,%d,%s]", mfirst ? "" : ",", mode->width, mode->height,
                    mode->refresh, mode->preferred ? "true" : "false");
            mfirst = false;
        }
        fputs("]}", f);
    }
    fputs("\n]}\n", f);
}

static int cmd_wl_dump(void)
{
    struct wl_state st;
    int rv = wl_connect(&st);
    if (rv) return rv;
    dump_heads(&st, stdout);
    return 0;
}

struct wanted {
    char name[128];
    int enabled;
    int32_t width, height, refresh, x, y, transform;
    double scale;
    int vrr;                    // -1: não mexer
    struct head *head;
};

static void config_succeeded(void *data, struct zwlr_output_configuration_v1 *c)
{
    (void)c;
    ((struct wl_state *)data)->result = 1;
}

static void config_failed(void *data, struct zwlr_output_configuration_v1 *c)
{
    (void)c;
    ((struct wl_state *)data)->result = 2;
}

static void config_cancelled(void *data, struct zwlr_output_configuration_v1 *c)
{
    (void)c;
    ((struct wl_state *)data)->result = 3;
}

static const struct zwlr_output_configuration_v1_listener config_listener = {
    .succeeded = config_succeeded,
    .failed = config_failed,
    .cancelled = config_cancelled,
};

// O modo anunciado mais próximo (mesmo tamanho, frequência a até 0,5 Hz;
// refresh 0 = o de maior frequência). NULL se o monitor não tem esse modo.
static struct mode *find_mode(struct head *head, int32_t w, int32_t h, int32_t refresh)
{
    struct mode *mode, *best = NULL;
    wl_list_for_each(mode, &head->modes, link) {
        if (mode->width != w || mode->height != h) continue;
        if (refresh <= 0) {
            if (!best || mode->refresh > best->refresh) best = mode;
            continue;
        }
        int32_t d = abs(mode->refresh - refresh);
        if (d <= 500 && (!best || d < abs(best->refresh - refresh))) best = mode;
    }
    return best;
}

static int parse_wanted(FILE *in, struct wanted **out, size_t *n_out)
{
    size_t n = 0, cap = 8;
    struct wanted *w = xcalloc(cap, sizeof(*w));
    char line[1024];
    while (fgets(line, sizeof(line), in)) {
        if (line[0] == '\n' || line[0] == '#') continue;
        if (n == cap) {
            cap *= 2;
            w = realloc(w, cap * sizeof(*w));
            if (!w) return 70;
        }
        struct wanted *x = &w[n];
        memset(x, 0, sizeof(*x));
        char vrr[8] = "-";
        int k = sscanf(line, "%127[^\t]\t%d\t%d\t%d\t%d\t%d\t%d\t%d\t%lf\t%7s",
                       x->name, &x->enabled, &x->width, &x->height, &x->refresh,
                       &x->x, &x->y, &x->transform, &x->scale, vrr);
        if (k < 9) {
            fprintf(stderr, "linha inválida: %s", line);
            free(w);
            return 2;
        }
        x->vrr = strcmp(vrr, "1") == 0 ? 1 : strcmp(vrr, "0") == 0 ? 0 : -1;
        if (x->transform < 0 || x->transform > 7 || x->scale <= 0 || x->scale > 10) {
            fprintf(stderr, "valores inválidos para %s\n", x->name);
            free(w);
            return 2;
        }
        n++;
    }
    *out = w;
    *n_out = n;
    return 0;
}

static int cmd_wl_apply(bool test_only)
{
    struct wanted *want = NULL;
    size_t n = 0;
    int rv = parse_wanted(stdin, &want, &n);
    if (rv) return rv;

    struct wl_state st;
    rv = wl_connect(&st);
    if (rv) return rv;

    for (size_t i = 0; i < n; i++) {
        struct head *head;
        wl_list_for_each(head, &st.heads, link) {
            if (head->name && strcmp(head->name, want[i].name) == 0) want[i].head = head;
        }
        if (!want[i].head) {
            fprintf(stderr, "monitor %s não está conectado\n", want[i].name);
            printf("failed\n");
            return 1;
        }
    }

    struct zwlr_output_configuration_v1 *config =
        zwlr_output_manager_v1_create_configuration(st.manager, st.serial);
    zwlr_output_configuration_v1_add_listener(config, &config_listener, &st);

    struct head *head;
    wl_list_for_each(head, &st.heads, link) {
        struct wanted *w = NULL;
        for (size_t i = 0; i < n; i++) {
            if (want[i].head == head) w = &want[i];
        }
        // Monitor que a configuração não cita: fica como está (o protocolo
        // exige que todos sejam configurados).
        bool enabled = w ? w->enabled : head->enabled;
        if (!enabled) {
            zwlr_output_configuration_v1_disable_head(config, head->obj);
            continue;
        }
        struct zwlr_output_configuration_head_v1 *ch =
            zwlr_output_configuration_v1_enable_head(config, head->obj);
        if (w) {
            struct mode *mode = find_mode(head, w->width, w->height, w->refresh);
            if (mode) {
                zwlr_output_configuration_head_v1_set_mode(ch, mode->obj);
            } else if (wl_list_empty(&head->modes)) {
                // Saídas virtuais (aninhado, headless) não anunciam modos.
                zwlr_output_configuration_head_v1_set_custom_mode(ch, w->width, w->height,
                                                                  w->refresh > 0 ? w->refresh : 0);
            } else {
                fprintf(stderr, "%s não anuncia o modo %dx%d@%d\n", head->name, w->width,
                        w->height, w->refresh);
                printf("failed\n");
                return 1;
            }
            zwlr_output_configuration_head_v1_set_position(ch, w->x, w->y);
            zwlr_output_configuration_head_v1_set_transform(ch, w->transform);
            zwlr_output_configuration_head_v1_set_scale(ch, wl_fixed_from_double(w->scale));
            if (w->vrr >= 0 && st.manager_version >= ZWLR_OUTPUT_CONFIGURATION_HEAD_V1_SET_ADAPTIVE_SYNC_SINCE_VERSION) {
                zwlr_output_configuration_head_v1_set_adaptive_sync(
                    ch, w->vrr ? ZWLR_OUTPUT_HEAD_V1_ADAPTIVE_SYNC_STATE_ENABLED
                               : ZWLR_OUTPUT_HEAD_V1_ADAPTIVE_SYNC_STATE_DISABLED);
            }
        } else {
            if (head->current) {
                zwlr_output_configuration_head_v1_set_mode(ch, head->current->obj);
            }
            zwlr_output_configuration_head_v1_set_position(ch, head->x, head->y);
            zwlr_output_configuration_head_v1_set_transform(ch, head->transform);
            zwlr_output_configuration_head_v1_set_scale(ch, wl_fixed_from_double(head->scale));
        }
    }

    if (test_only) {
        zwlr_output_configuration_v1_test(config);
    } else {
        zwlr_output_configuration_v1_apply(config);
    }
    while (st.result == 0) {
        if (wl_display_dispatch(st.display) < 0) {
            printf("failed\n");
            return 3;
        }
    }
    zwlr_output_configuration_v1_destroy(config);
    // O estado novo chega com o próximo "done": espera por ele, para quem
    // ler o estado logo depois já ver a configuração aplicada.
    if (st.result == 1 && !test_only) {
        int before = st.done_count;
        long long deadline = now_ms() + 2000;
        while (st.done_count == before && now_ms() < deadline) {
            wl_display_flush(st.display);
            struct pollfd p = {wl_display_get_fd(st.display), POLLIN, 0};
            if (poll(&p, 1, 200) > 0 && wl_display_dispatch(st.display) < 0) break;
        }
    }
    static const char *names[] = {"", "succeeded", "failed", "cancelled"};
    printf("%s\n", names[st.result]);
    wl_display_disconnect(st.display);
    free(want);
    return st.result == 1 ? 0 : st.result == 3 ? 2 : 1;
}

static int cmp_str(const void *a, const void *b)
{
    return strcmp(*(char *const *)a, *(char *const *)b);
}

// Assinatura do conjunto de monitores: nome, fabricante, modelo e serial
// de cada um, em ordem. Ligar e desligar um monitor não muda o conjunto.
static char *wl_signature(struct wl_state *st)
{
    size_t n = (size_t)wl_list_length(&st->heads), i = 0;
    char **parts = xcalloc(n ? n : 1, sizeof(char *));
    struct head *head;
    wl_list_for_each(head, &st->heads, link) {
        if (asprintf(&parts[i++], "%s|%s|%s|%s", head->name ? head->name : "",
                     head->make ? head->make : "", head->model ? head->model : "",
                     head->serial ? head->serial : "") < 0) exit(70);
    }
    qsort(parts, n, sizeof(char *), cmp_str);
    size_t len = 1;
    for (i = 0; i < n; i++) len += strlen(parts[i]) + 1;
    char *sig = xcalloc(len, 1);
    for (i = 0; i < n; i++) {
        if (i) strcat(sig, ";");
        strcat(sig, parts[i]);
        free(parts[i]);
    }
    free(parts);
    return sig;
}

static int cmd_wl_watch(bool run_now, char **argv)
{
    struct wl_state st;
    int rv = wl_connect(&st);
    if (rv) return rv;
    char *last = wl_signature(&st);
    fprintf(stderr, "big-wm-display-helper: vigiando (%s)\n", last);
    if (run_now) run_command(argv, last);

    long long deadline = -1;
    while (!quit) {
        while (wl_display_prepare_read(st.display) != 0) wl_display_dispatch_pending(st.display);
        wl_display_flush(st.display);
        int timeout = deadline < 0 ? -1 : (int)(deadline - now_ms());
        if (timeout < -1) timeout = 0;
        struct pollfd p = {wl_display_get_fd(st.display), POLLIN, 0};
        int r = poll(&p, 1, deadline < 0 ? -1 : (timeout < 0 ? 0 : timeout));
        if (r > 0) {
            if (wl_display_read_events(st.display) < 0) break;
        } else {
            wl_display_cancel_read(st.display);
        }
        if (r < 0 && errno != EINTR) break;
        if (wl_display_dispatch_pending(st.display) < 0) break;
        if (!st.manager) break;
        if (p.revents & (POLLHUP | POLLERR)) break;

        if (st.done) {
            char *sig = wl_signature(&st);
            if (strcmp(sig, last) != 0) {
                if (deadline < 0) deadline = now_ms() + DEBOUNCE_MS;
            } else {
                deadline = -1;
            }
            if (deadline >= 0 && now_ms() >= deadline) {
                fprintf(stderr, "big-wm-display-helper: monitores mudaram (%s)\n", sig);
                free(last);
                last = sig;
                sig = NULL;
                deadline = -1;
                run_command(argv, last);
            }
            free(sig);
        }
    }
    free(last);
    return 0;
}

/* ----------------------------------------------------------------- x11 -- */

static int x_io_error(Display *dpy)
{
    (void)dpy;
    _exit(0);
}

// EDID da saída (bytes), ou NULL.
static unsigned char *x_edid(Display *dpy, RROutput out, int *len)
{
    Atom edid = XInternAtom(dpy, RR_PROPERTY_RANDR_EDID, True);
    *len = 0;
    if (edid == None) return NULL;
    unsigned char *prop = NULL;
    int fmt;
    unsigned long n, after;
    Atom type;
    if (XRRGetOutputProperty(dpy, out, edid, 0, 256, False, False, AnyPropertyType, &type,
                             &fmt, &n, &after, &prop) != Success || !prop) return NULL;
    if (fmt != 8 || n == 0) {
        XFree(prop);
        return NULL;
    }
    *len = (int)n;
    return prop;
}

static char *x_signature(Display *dpy, Window root, FILE *verbose)
{
    XRRScreenResources *res = XRRGetScreenResourcesCurrent(dpy, root);
    if (!res) return strdup("");
    char **parts = xcalloc(res->noutput ? res->noutput : 1, sizeof(char *));
    int n = 0;
    for (int i = 0; i < res->noutput; i++) {
        XRROutputInfo *info = XRRGetOutputInfo(dpy, res, res->outputs[i]);
        if (!info) continue;
        if (info->connection == RR_Connected) {
            int len;
            unsigned char *edid = x_edid(dpy, res->outputs[i], &len);
            unsigned long h = 5381;
            for (int k = 0; k < len; k++) h = h * 33 + edid[k];
            if (asprintf(&parts[n++], "%s|%lx", info->name, len ? h : 0UL) < 0) exit(70);
            if (verbose) {
                fprintf(verbose, "%s\t", info->name);
                for (int k = 0; k < len; k++) fprintf(verbose, "%02x", edid[k]);
                fputc('\n', verbose);
            }
            if (edid) XFree(edid);
        }
        XRRFreeOutputInfo(info);
    }
    XRRFreeScreenResources(res);
    qsort(parts, (size_t)n, sizeof(char *), cmp_str);
    size_t total = 1;
    for (int i = 0; i < n; i++) total += strlen(parts[i]) + 1;
    char *sig = xcalloc(total, 1);
    for (int i = 0; i < n; i++) {
        if (i) strcat(sig, ";");
        strcat(sig, parts[i]);
        free(parts[i]);
    }
    free(parts);
    return sig;
}

static int x_open(Display **dpy, int *event_base)
{
    *dpy = XOpenDisplay(NULL);
    if (!*dpy) {
        fprintf(stderr, "sem conexão com o servidor X\n");
        return 3;
    }
    int error_base;
    if (!XRRQueryExtension(*dpy, event_base, &error_base)) {
        fprintf(stderr, "o servidor X não tem RandR\n");
        return 4;
    }
    // Sem anunciar a versão 1.2, o servidor não manda os eventos RRNotify
    // (saída conectada/desconectada).
    int major = 0, minor = 0;
    if (!XRRQueryVersion(*dpy, &major, &minor) || (major == 1 && minor < 2)) {
        fprintf(stderr, "o servidor X tem RandR %d.%d (precisa de 1.2)\n", major, minor);
        return 4;
    }
    return 0;
}

static int cmd_x11_outputs(void)
{
    Display *dpy;
    int ev;
    int rv = x_open(&dpy, &ev);
    if (rv) return rv;
    free(x_signature(dpy, DefaultRootWindow(dpy), stdout));
    XCloseDisplay(dpy);
    return 0;
}

static int cmd_x11_watch(bool run_now, char **argv)
{
    Display *dpy;
    int ev;
    int rv = x_open(&dpy, &ev);
    if (rv) return rv;
    XSetIOErrorHandler(x_io_error);
    Window root = DefaultRootWindow(dpy);
    XRRSelectInput(dpy, root, RROutputChangeNotifyMask | RRScreenChangeNotifyMask);
    char *last = x_signature(dpy, root, NULL);
    fprintf(stderr, "big-wm-display-helper: vigiando (%s)\n", last);
    if (run_now) run_command(argv, last);

    long long deadline = -1;
    int fd = ConnectionNumber(dpy);
    while (!quit) {
        XFlush(dpy);
        bool changed = false;
        while (XPending(dpy)) {
            XEvent e;
            XNextEvent(dpy, &e);
            XRRUpdateConfiguration(&e);
            if (e.type == ev + RRNotify || e.type == ev + RRScreenChangeNotify) changed = true;
        }
        // Confere depois de uma pausa: o estado "conectado" de uma saída pode
        // mudar depois do primeiro evento (e vários eventos vêm juntos).
        if (changed) deadline = now_ms() + DEBOUNCE_MS;
        if (deadline >= 0 && now_ms() >= deadline) {
            char *sig = x_signature(dpy, root, NULL);
            deadline = -1;
            if (strcmp(sig, last) != 0) {
                fprintf(stderr, "big-wm-display-helper: monitores mudaram (%s)\n", sig);
                free(last);
                last = sig;
                run_command(argv, last);
            } else {
                free(sig);
            }
            continue;
        }
        struct pollfd p = {fd, POLLIN, 0};
        int timeout = deadline < 0 ? -1 : (int)(deadline - now_ms());
        if (deadline >= 0 && timeout < 0) timeout = 0;
        if (poll(&p, 1, timeout) < 0 && errno != EINTR) break;
    }
    free(last);
    XCloseDisplay(dpy);
    return 0;
}

/* ---------------------------------------------------------------- main -- */

static int usage(void)
{
    fputs("uso: big-wm-display-helper wl-dump | wl-apply [--test] |\n"
          "     wl-watch [--run-now] -- COMANDO... | x11-watch [--run-now] -- COMANDO... |\n"
          "     wl-watch --print | x11-watch --print |\n"
          "     x11-outputs\n", stderr);
    return 2;
}

static char **command_after_dashes(int argc, char **argv, bool *run_now)
{
    *run_now = false;
    for (int i = 2; i < argc; i++) {
        if (strcmp(argv[i], "--run-now") == 0) *run_now = true;
        else if (strcmp(argv[i], "--print") == 0) print_mode = true;
        else if (strcmp(argv[i], "--") == 0 && i + 1 < argc) return &argv[i + 1];
        else return NULL;
    }
    return NULL;
}

int main(int argc, char **argv)
{
    if (argc < 2) return usage();
    struct sigaction sa = {0};
    sa.sa_handler = on_signal;
    sigaction(SIGTERM, &sa, NULL);
    sigaction(SIGINT, &sa, NULL);
    signal(SIGPIPE, SIG_IGN);

    const char *cmd = argv[1];
    if (strcmp(cmd, "wl-dump") == 0) return cmd_wl_dump();
    if (strcmp(cmd, "wl-apply") == 0) return cmd_wl_apply(argc > 2 && strcmp(argv[2], "--test") == 0);
    if (strcmp(cmd, "x11-outputs") == 0) return cmd_x11_outputs();
    bool run_now;
    if (strcmp(cmd, "wl-watch") == 0 || strcmp(cmd, "x11-watch") == 0) {
        char **command = command_after_dashes(argc, argv, &run_now);
        if (!command && !print_mode) return usage();
        if (print_mode) {
            // Vive só enquanto a janela que o abriu.
            prctl(PR_SET_PDEATHSIG, SIGTERM);
            if (getppid() == 1) return 0;
        }
        return cmd[0] == 'w' ? cmd_wl_watch(run_now, command) : cmd_x11_watch(run_now, command);
    }
    return usage();
}
