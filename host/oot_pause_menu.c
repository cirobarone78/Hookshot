/* (hookshot) "Recomp Options": a sixth button on the pause menu's Menu page, below Title Screen, that opens the
   Insert menu (gpu/vk/vk_menu.cpp). nx2/pause_layout.py adds its pane, Pa_Button_05, to the page's layout (PaSystemMenu_00, a
   copy of Pa_Button_04 below it), served by host/prompts.c; nx2/oot_pause_menu.py puts the calls below into the lifted code.

   - The button: when the game has made the page and its five buttons (f_80f99400), the sixth gets a button object as they do
     (f_80f99390, f_8045c6c0).
   - Its text: "Recomp Options" in the game's language ("Opções Recomp" in Portuguese and the like), given to its text
     boxes (the text and its shadow) as the game gives a box its message (f_80459520): the page's buttons take theirs from
     LayoutMsg/PlusMenu_00, which has none for a sixth.
   - Pressed: A while the cursor is on it (its state, noted at f_80ad5310) opens the Insert menu (F1, as the key opens it),
     and the game does not see that press (hos_pausebtn_buttons, from host/nn_hid.c).
   - Gone: when the page is destroyed (f_80aa2ad0, the base of its destructor) the button is forgotten, so its control is
     never read after it is freed. */
#include "hos.h"
#include <stdio.h>
#include <string.h>
#include <windows.h>   /* (VK_F1; host/posix's on Linux) */

const char *hos_game_language(void);   /* nn_applet.c */

static uint64_t mem;   /* our guest memory: the pane's name and the button's text */
enum { AT_B05 = 0, AT_TEXT = 32, AT_REF = 96, AT_END = 128 };
static volatile uint64_t our_page, our_part, our_button, our_control;   /* (the page, the sixth pane's part, its button object
                                                                            and the control whose state the game changes, while
                                                                            the page lives) */

static int ready(void) {
    if (mem) return 1;
    mem = hos_region_alloc(0x10000, 0x10000);
    if (!mem) return 0;
    memset(GP(mem), 0, AT_END);
    strcpy((char *)GP(mem + AT_B05), "Pa_Button_05");
    const char *lang = hos_game_language();
    const char *text = !strncmp(lang, "pt", 2) ? "Opções Recomp" : !strncmp(lang, "es", 2) ? "Opciones Recomp"
                     : !strncmp(lang, "fr", 2) ? "Options Recomp" : !strncmp(lang, "it", 2) ? "Opzioni Recomp"
                     : !strncmp(lang, "de", 2) ? "Recomp-Optionen" : "Recomp Options";
    snprintf((char *)GP(mem + AT_TEXT), AT_END - AT_TEXT, "%s", text);
    return 1;
}

/* a guest function called with up to five arguments: its x0 */
static uint64_t call(Ctx *c, uint64_t fn, uint64_t a0, uint64_t a1, uint64_t a2, uint64_t a3, uint64_t a4) {
    A64Fn f = a64_lookup(fn);
    if (!f) {
        hos_log("pause menu: no function at %#llx", (unsigned long long)fn);
        return 0;
    }
    c->x[0] = a0, c->x[1] = a1, c->x[2] = a2, c->x[3] = a3, c->x[4] = a4;
    f(c);
    return c->x[0];
}

/* the page made (f_80f99400(screen, heap)): the sixth button's object */
void hos_pausebtn_build(Ctx *c, A64Fn game) {
    const uint64_t screen = c->x[0], heap = c->x[1];
    game(c);
    our_page = our_part = our_button = our_control = 0;
    if (!ready()) return;
    const uint64_t panel = recomp_load64(c, screen + 800);
    const uint64_t page = panel ? recomp_load64(c, panel + 0x20) : 0;
    if (!page) return;
    const uint64_t part = call(c, 0x8045c3e0ULL, page, mem + AT_B05, 0, 0, 0);   /* (f_8045c3e0: a part by name) */
    if (!part) {
        static int said;
        if (!said++) hos_log("pause menu: the page has no Pa_Button_05 (its layout as the game has it): no Recomp options");
        return;
    }
    const uint64_t button = call(c, 0x8005ebe0ULL, 0x68, heap, 8, 0, 0);
    if (!button) return;
    call(c, 0x80f99390ULL, button, part, 0, 0, 0);
    call(c, 0x8045c6c0ULL, button, heap, 0, 0, 0);
    our_page = screen, our_part = part, our_button = button;
    /* its text (the page's own buttons take theirs from LayoutMsg/PlusMenu_00, which has none for a sixth) */
    const uint64_t ref = mem + AT_REF;
    recomp_store64(c, ref, mem + AT_TEXT);
    recomp_store32(c, ref + 8, strlen((const char *)GP(mem + AT_TEXT)));
    recomp_store64(c, ref + 16, ~0ull);
    /* (on each of its text boxes, the text and its shadow: its panes (f_8045b1f0(tree, i)) of the text box kind (+0xa8's
       0x3c00000 bits 0x800000), given the text as f_80a87d30 gives a box its message: f_80459520(pane, &text, 0)) */
    const uint64_t tree = call(c, 0x8045c040ULL, part + 0x40, 0, 0, 0, 0);
    const unsigned panes = tree ? (unsigned)recomp_load16(c, tree + 0x13c) : 0;
    int n = 0;
    for (unsigned i = 0; i < panes && i < 64; i++) {
        const uint64_t p = call(c, 0x8045b1f0ULL, tree, i, 0, 0, 0);
        if (!p || ((uint32_t)recomp_load32(c, p + 0xa8) & 0x3c00000u) != 0x800000u) continue;
        call(c, 0x80459520ULL, p, ref, 0, 0, 0);
        n++;
    }
    hos_log("pause menu: Recomp options button (part %#llx, button %#llx; its text on %d of %u panes)", (unsigned long long)part,
            (unsigned long long)button, n, panes);
}

/* f_80ad5310(control, state): a button's control's state about to change (0 off, 1 and 3 on: the cursor is on it, 4 and 5
   decided; kept at its +0x38). The sixth button's is only noted here: which object it is, for hos_pausebtn_buttons */
int hos_pausebtn_state(Ctx *c) {
    const uint64_t control = c->x[0];
    if (!our_part || !control || recomp_load64(c, control + 0x20) != our_part) return 0;
    our_control = control;
    return 0;
}

/* f_80aa2ad0(object): the base of the page's destructor (shared with other screens): the page going, its button and control
   forgotten, so hos_pausebtn_buttons never reads them after */
void hos_pausebtn_gone(Ctx *c) {
    if (c->x[0] && c->x[0] == our_page) our_page = our_part = our_button = our_control = 0;
}

/* the controller's buttons as the game reads them (host/nn_hid.c npad_states; a: the A button's bit): A pressed while the
   cursor is on the sixth button opens the Insert menu (F1, as the key opens it), and the game does not see that press. A
   decision of the button is never made: the page's script has no end for it, and the menu could then not be left */
uint64_t hos_pausebtn_buttons(uint64_t buttons, uint64_t a) {
    static int ours, was;   /* (this press of A is ours; A was down at the last read) */
    const int down = (buttons & a) != 0, pressed = down && !was;
    was = down;
    if (!down) ours = 0;
    else if (pressed) {
        const uint64_t control = our_control;
        const unsigned state = control ? (unsigned)recomp_load8(NULL, control + 0x38) : 0;   /* (no Ctx here: not used) */
        int rx_option(int id, int otherwise);   /* rx_backend.c: 1 the Insert menu is open */
        if ((state == 1 || state == 3) && !rx_option(1, 0)) {
            ours = 1;
            void hos_vk_note_key_press(unsigned key);   /* rx_backend.c: the Insert menu's F1 */
            hos_vk_note_key_press(VK_F1);
            hos_log("pause menu: Recomp options: the Insert menu");
        }
    }
    return ours ? buttons & ~a : buttons;
}
