/* nn::nfp: amiibo. The game asks the NFC library for a device, starts a scan,
   mounts the tag and reads its UID, model, common and registration data. On a
   PC there is no NFC reader, so this is a virtual tag: a profile from
   host/nfp_amiibo.h appears a moment after a scan starts, and its data is
   returned in the SDK's own structures. What the game does with the figure is
   its own: in this title the Zelda series figures are meant to give a random
   item and the two Ocarina of Time 2026 figures Mask 101/102, and another
   series gets its "this amiibo does not work" message. This file only presents
   the tag; the effect itself is the game's.

   HOS_AMIIBO=<profile> (or amiibo=<profile> in hookshot_options.ini) chooses the
   figure: link-oot (the default), zelda-botw, young-link, young-zelda,
   oot-young-link, oot-young-zelda, mario, none, or a 16-hex-digit id such as
   0x01000000034b0902. HOS_AMIIBO_ID is the same switch. HOS_AMIIBO_RANDOM_UID=1
   gives each scan a different UID, which gets around a game's once-a-day rule.

   The structures are the SDK's (nn/nfp/nfp_Types.h): TagInfo 0x58, RegisterInfo
   0x100, CommonInfo 0x40, ModelInfo 0x40. The functions are the free functions
   of nn::nfp (not the nfp:user service), so the game's lifted SDK calls land
   here. */
#include "hos.h"
#include "hos_paths.h"
#include "nfp_amiibo.h"
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>

/* nn_os_sync.c: the event object a guest SystemEventType points at */
void hos_system_event_init(uint64_t key, int autoclear);
void hos_system_event_signal(uint64_t key);

enum {
    NFP_STATE_NONE = 0,
    NFP_STATE_INIT = 1,
};
enum {
    NFP_DEV_INIT = 0,
    NFP_DEV_SEARCH = 1,
    NFP_DEV_ACTIVE = 2,
    NFP_DEV_DEACTIVE = 3,
    NFP_DEV_MOUNT = 4,
};

static int nfp_state = NFP_STATE_INIT;   /* (a game that skips Initialize, or whose SDK calls it another way, still finds the library ready) */
static int nfp_device_state = NFP_DEV_INIT;
static const NfpAmiibo *nfp_tag;          /* NULL: no tag (HOS_AMIIBO=none) */
static char nfp_loaded_text[128];
static NfpAmiibo nfp_custom;              /* HOS_AMIIBO=0x... */
static uint8_t nfp_uid[10];
static int nfp_uid_len;
static uint64_t nfp_activate_event, nfp_deactivate_event;
static unsigned nfp_scan_id, nfp_mount_logged;

/* A real tag is not on the reader the instant a scan starts: the game draws its
   "touch the amiibo" prompt, then the figure arrives. Presenting the tag inside
   StartDetection made the whole read finish before the prompt existed, and the
   prompt then waited forever. The tag now appears a moment after the scan. */
enum { NFP_TAG_DELAY_NS = 300000000 };
static int nfp_scan_pending;
static int64_t nfp_scan_at;

/* The last data returned by each read, so the log shows what the game receives
   once per figure instead of once per poll. */
static uint8_t nfp_last_tag_info[NFP_TAG_INFO_SIZE], nfp_last_model_info[NFP_MODEL_INFO_SIZE];
static uint8_t nfp_last_register_info[NFP_REGISTER_INFO_SIZE], nfp_last_common_info[NFP_COMMON_INFO_SIZE];
static int nfp_last_tag_valid, nfp_last_model_valid, nfp_last_register_valid, nfp_last_common_valid;

/* The game's application area: one game's 0xD8 bytes on the tag. */
static int nfp_area_exists;
static uint32_t nfp_area_id;
static uint8_t nfp_area[NFP_APP_AREA_SIZE];
static size_t nfp_area_size;
static int nfp_area_open;

/* The option: HOS_AMIIBO, HOS_AMIIBO_ID, then hookshot_options.ini's amiibo=.
   The ini is the Insert menu's file (host/nn_applet.c reads its numeric rows the
   same way); an all-digit value is the menu's profile index. */
static int nfp_ini_text(const char *key, char *out, size_t cap) {
    char path[MAX_PATH];
    const DWORD n = hos_game_path_a(path, MAX_PATH);
    char *slash = n ? (strrchr(path, 92) ? strrchr(path, 92) : strrchr(path, 47)) : NULL;
    if (!slash) return 0;
    snprintf(slash + 1, (size_t)(path + MAX_PATH - slash - 1), "hookshot_options.ini");
    FILE *f = fopen(path, "r");
    if (!f) return 0;
    char line[128];
    const size_t len = strlen(key);
    int found = 0;
    while (fgets(line, sizeof line, f)) {
        if (strncmp(line, key, len) || line[len] != '=') continue;
        char *v = line + len + 1;
        size_t j = 0;
        while (v[j] && v[j] != '\r' && v[j] != '\n' && j + 1 < cap) out[j] = v[j], j++;
        out[j] = '\0';
        found = 1;
    }
    fclose(f);
    return found;
}

static void nfp_load(void) {
    char text[128] = "";
    const char *e = getenv("HOS_AMIIBO");
    if (!e || !*e) e = getenv("HOS_AMIIBO_ID");
    if (e && *e) snprintf(text, sizeof text, "%s", e);
    else if (!nfp_ini_text("amiibo", text, sizeof text)) snprintf(text, sizeof text, "link-oot");
    if (!strcmp(text, nfp_loaded_text)) return;
    snprintf(nfp_loaded_text, sizeof nfp_loaded_text, "%s", text);
    nfp_uid_len = 0;   /* a new figure gets its own UID */

    if (!*text || nfp_ieq(text, "none") || nfp_ieq(text, "off") || !strcmp(text, "7")) {
        nfp_tag = NULL;
        hos_log("nfp: no virtual amiibo (HOS_AMIIBO=none)");
        return;
    }
    if (nfp_parse_id(text, nfp_custom.id)) {
        nfp_custom.key = "custom";
        nfp_custom.name = "a custom amiibo";
        nfp_custom.effect = nfp_effect_from_id(nfp_custom.id);
        nfp_custom.zelda = nfp_custom.effect[0] == 'a';
        nfp_tag = &nfp_custom;
        hos_log("nfp: virtual amiibo %s (%02x%02x%02x%02x%02x%02x%02x%02x): %s",
                nfp_tag->name, nfp_tag->id[0], nfp_tag->id[1], nfp_tag->id[2], nfp_tag->id[3], nfp_tag->id[4],
                nfp_tag->id[5], nfp_tag->id[6], nfp_tag->id[7], nfp_tag->effect);
        return;
    }
    if (text[0] >= '0' && text[0] <= '9') {
        nfp_tag = nfp_profile_by_index(atoi(text));
    } else {
        nfp_tag = nfp_profile_by_key(text);
    }
    if (!nfp_tag) {
        hos_log("nfp: HOS_AMIIBO=%s is not a profile (link-oot, zelda-botw, young-link, young-zelda, "
                "oot-young-link, oot-young-zelda, mario, none, or 0x<16 hex digits>): using link-oot", text);
        nfp_tag = nfp_profile_by_index(0);
    }
    hos_log("nfp: virtual amiibo %s (%02x%02x%02x%02x%02x%02x%02x%02x): %s", nfp_tag->name, nfp_tag->id[0],
            nfp_tag->id[1], nfp_tag->id[2], nfp_tag->id[3], nfp_tag->id[4], nfp_tag->id[5], nfp_tag->id[6],
            nfp_tag->id[7], nfp_tag->effect);
}

static void nfp_make_uid(void) {
    if (!nfp_tag) {
        nfp_uid_len = 0;
        memset(nfp_uid, 0, sizeof nfp_uid);
        return;
    }
    nfp_uid_from_id(nfp_tag->id, nfp_uid, &nfp_uid_len);
    if (getenv("HOS_AMIIBO_RANDOM_UID") && atoi(getenv("HOS_AMIIBO_RANDOM_UID")) != 0) {
        /* (the same shape: 7 bytes, so the game sees a different figure each scan; a
           new figure also has no application area yet) */
        for (int i = 0; i < 7; i++) nfp_uid[i] = (uint8_t)(nfp_uid[i] ^ (uint8_t)(rand() >> (i * 3)));
        nfp_area_exists = 0;
        nfp_area_size = 0;
        nfp_area_open = 0;
    }
}

static void nfp_date(int *year, int *month, int *day) {
    const time_t now = time(NULL);
    const struct tm *tm = localtime(&now);
    *year = tm ? tm->tm_year + 1900 : 2026;
    *month = tm ? tm->tm_mon + 1 : 11;
    *day = tm ? tm->tm_mday : 9;
}

static int nfp_write(uint64_t addr, const void *data, size_t size) {
    void *p = hos_guest_range(addr, size);
    if (!p) {
        hos_log("nfp: a %u-byte result at %#llx is outside guest memory", (unsigned)size, (unsigned long long)addr);
        return 0;
    }
    memcpy(p, data, size);
    HOS_WRITTEN(p, size);
    return 1;
}

static int nfp_read(uint64_t addr, void *data, size_t size) {
    const void *p = hos_guest_range(addr, size);
    if (!p) return 0;
    memcpy(data, p, size);
    return 1;
}

static void nfp_scan(void);

/* Called from the state queries: the tag is found NFP_TAG_DELAY_NS after the scan
   started, as if the player had just touched the figure to the reader. */
static void nfp_poll_scan(void) {
    if (!nfp_scan_pending || hos_now_ns() - nfp_scan_at < NFP_TAG_DELAY_NS) return;
    nfp_scan_pending = 0;
    nfp_scan();
}

static void nfp_scan(void) {
    nfp_scan_id++;
    if (!nfp_tag) {
        nfp_device_state = NFP_DEV_SEARCH;
        return;
    }
    nfp_make_uid();
    nfp_device_state = NFP_DEV_ACTIVE;
    if (nfp_activate_event) hos_system_event_signal(nfp_activate_event);
    hos_log("nfp: %s scanned (uid %02x%02x%02x%02x%02x%02x%02x): %s", nfp_tag->name, nfp_uid[0], nfp_uid[1],
            nfp_uid[2], nfp_uid[3], nfp_uid[4], nfp_uid[5], nfp_uid[6], nfp_tag->effect);
}

/* ---- nn::nfp ------------------------------------------------------------------------------------------------- */

HLE(_ZN2nn3nfp10InitializeEv) {
    nfp_load();
    nfp_state = NFP_STATE_INIT;
    nfp_device_state = NFP_DEV_INIT;
    nfp_scan_pending = 0;
    hos_log("nfp: initialized");
}

HLE(_ZN2nn3nfp8FinalizeEv) {
    nfp_state = NFP_STATE_NONE;
    nfp_device_state = NFP_DEV_INIT;
    nfp_scan_pending = 0;
    nfp_activate_event = nfp_deactivate_event = 0;
    nfp_area_open = 0;
}

HLE(_ZN2nn3nfp8GetStateEv) {
    static int last_state = -1;
    if (last_state != nfp_state) {
        last_state = nfp_state;
        hos_log("nfp: GetState: %d", nfp_state);
    }
    RET(nfp_state);
}

HLE(_ZN2nn3nfp14GetDeviceStateERKNS0_12DeviceHandleE) {
    static int last_state = -1;
    nfp_poll_scan();
    if (last_state != nfp_device_state) {
        last_state = nfp_device_state;
        hos_log("nfp: GetDeviceState: %d", nfp_device_state);
    }
    RET(nfp_device_state);
}

HLE(_ZN2nn3nfp9GetNpadIdEPNS_3hid10NpadIdTypeERKNS0_12DeviceHandleE) {
    const uint32_t player1 = 0;   /* NpadIdType_Player1 */
    nfp_write(ARG(0), &player1, sizeof player1);
    RET(0);
}

/* SDK 22's NpadIdType is a typedef to uint32_t, so the game imports the output as
   unsigned int* (EPj) rather than the enum's old mangled name. Without this the
   generic stub returned without writing, and the game could not map the NFC
   device to a controller. */
HLE(_ZN2nn3nfp9GetNpadIdEPjRKNS0_12DeviceHandleE) {
    const uint32_t player1 = 0;   /* NpadIdType_Player1 */
    nfp_write(ARG(0), &player1, sizeof player1);
    RET(0);
}

/* DeviceHandle is 8 bytes (an id and 4 reserved bytes): one device, id 0. */
HLE(_ZN2nn3nfp11ListDevicesEPNS0_12DeviceHandleEPii) {
    uint8_t handle[8] = {0};
    int count = 0;
    static int logged;
    if (!logged) {
        logged = 1;
        hos_log("nfp: ListDevices -> one device");
    }
    if ((int)ARG(2) <= 0) {
        nfp_write(ARG(1), &count, sizeof count);
        RET(0);
    }
    if (nfp_write(ARG(0), handle, sizeof handle)) count = 1;
    nfp_write(ARG(1), &count, sizeof count);
    RET(0);
}

HLE(_ZN2nn3nfp14StartDetectionERKNS0_12DeviceHandleE) {
    nfp_load();
    hos_log("nfp: StartDetection");
    nfp_device_state = NFP_DEV_SEARCH;
    nfp_scan_pending = 1;
    nfp_scan_at = hos_now_ns();
    RET(0);
}

HLE(_ZN2nn3nfp13StopDetectionERKNS0_12DeviceHandleE) {
    hos_log("nfp: StopDetection");
    /* Back to Initialized: a mounted tag that is not unmounted is put down too,
       and the reader is ready for the next scan. The game starts its next
       operation with StartDetection as soon as it sees this state. */
    nfp_scan_pending = 0;
    nfp_device_state = NFP_DEV_INIT;
    if (nfp_deactivate_event) hos_system_event_signal(nfp_deactivate_event);
    RET(0);
}

HLE(_ZN2nn3nfp5MountERKNS0_12DeviceHandleENS0_9ModelTypeE) {
    nfp_poll_scan();
    if (nfp_mount_logged != nfp_scan_id) {
        nfp_mount_logged = nfp_scan_id;
        hos_log("nfp: Mount: model %u, target all%s", (unsigned)ARG(1), nfp_tag ? "" : " (no tag)");
    }
    nfp_device_state = NFP_DEV_MOUNT;
    RET(0);
}

HLE(_ZN2nn3nfp5MountERKNS0_12DeviceHandleENS0_9ModelTypeENS0_11MountTargetE) {
    nfp_poll_scan();
    if (nfp_mount_logged != nfp_scan_id) {
        nfp_mount_logged = nfp_scan_id;
        hos_log("nfp: Mount: model %u, target %u%s", (unsigned)ARG(1), (unsigned)ARG(2), nfp_tag ? "" : " (no tag)");
    }
    nfp_device_state = NFP_DEV_MOUNT;
    RET(0);
}

HLE(_ZN2nn3nfp7UnmountERKNS0_12DeviceHandleE) {
    hos_log("nfp: Unmount");
    nfp_device_state = NFP_DEV_ACTIVE;
    nfp_area_open = 0;
    if (nfp_deactivate_event) hos_system_event_signal(nfp_deactivate_event);
    RET(0);
}

HLE(_ZN2nn3nfp19OpenApplicationAreaERKNS0_12DeviceHandleEj) {
    const uint32_t access = (uint32_t)ARG(1);
    const int existed = nfp_area_exists && nfp_area_id == access;
    static uint32_t logged_access;
    static int logged;
    if (!logged || logged_access != access) {
        logged = 1;
        logged_access = access;
        hos_log("nfp: OpenApplicationArea: access %08x (%s)", access, existed ? "existing" : "new");
    }
    if (!nfp_area_exists || nfp_area_id != access) {
        /* (a tag that has never held this game's area: an empty one, as a first
           scan has. The game writes it with SetApplicationArea and Flush.) */
        nfp_area_exists = 1;
        nfp_area_id = access;
        nfp_area_size = 0;
        memset(nfp_area, 0, sizeof nfp_area);
    }
    nfp_area_open = 1;
    RET(0);
}

HLE(_ZN2nn3nfp18GetApplicationAreaEPvPyRKNS0_12DeviceHandleEy) {
    size_t want = (size_t)ARG(3);
    if (!nfp_area_open) {
        const size_t zero = 0;
        nfp_write(ARG(1), &zero, sizeof zero);
        RET(0);
    }
    if (want > nfp_area_size) want = nfp_area_size;
    if (want > NFP_APP_AREA_SIZE) want = NFP_APP_AREA_SIZE;
    if (want) nfp_write(ARG(0), nfp_area, want);
    nfp_write(ARG(1), &want, sizeof want);
    RET(0);
}

HLE(_ZN2nn3nfp18SetApplicationAreaERKNS0_12DeviceHandleEPKvy) {
    size_t size = (size_t)ARG(2);
    if (size > NFP_APP_AREA_SIZE) size = NFP_APP_AREA_SIZE;
    if (size && !nfp_read(ARG(1), nfp_area, size)) RET(0);
    nfp_area_size = size;
    nfp_area_exists = 1;
    nfp_area_open = 1;
    RET(0);
}

/* Some SDK builds spell the area size `unsigned long` (Pm/Em) rather than
   `unsigned long long` (Py/Ey). Both are 64-bit and the ABI is the same, but the
   mangled names differ: without these the import falls to the generic stub,
   which returns 0 and writes no size. */
HLE(_ZN2nn3nfp18GetApplicationAreaEPvPmRKNS0_12DeviceHandleEm) {
    imp__ZN2nn3nfp18GetApplicationAreaEPvPyRKNS0_12DeviceHandleEy(c);
}
HLE(_ZN2nn3nfp18SetApplicationAreaERKNS0_12DeviceHandleEPKvm) {
    imp__ZN2nn3nfp18SetApplicationAreaERKNS0_12DeviceHandleEPKvy(c);
}

/* ApplicationAreaCreateInfo: accessId (u32), initialDataSize (u32), pInitialData */
static void nfp_create_area(uint64_t info) {
    uint8_t raw[16];
    if (!nfp_read(info, raw, sizeof raw)) return;
    const uint32_t access = (uint32_t)raw[0] | ((uint32_t)raw[1] << 8) | ((uint32_t)raw[2] << 16) |
                            ((uint32_t)raw[3] << 24);
    size_t size = (size_t)raw[4] | ((size_t)raw[5] << 8) | ((size_t)raw[6] << 16) | ((size_t)raw[7] << 24);
    uint64_t data = 0;
    memcpy(&data, raw + 8, sizeof data);
    if (size > NFP_APP_AREA_SIZE) size = NFP_APP_AREA_SIZE;
    memset(nfp_area, 0, sizeof nfp_area);
    if (size && data) nfp_read(data, nfp_area, size);
    nfp_area_exists = 1;
    nfp_area_id = access;
    nfp_area_size = size;
    nfp_area_open = 1;
}

HLE(_ZN2nn3nfp21CreateApplicationAreaERKNS0_12DeviceHandleERKNS0_25ApplicationAreaCreateInfoE) {
    nfp_create_area(ARG(1));
    RET(0);
}

HLE(_ZN2nn3nfp23RecreateApplicationAreaERKNS0_12DeviceHandleERKNS0_25ApplicationAreaCreateInfoE) {
    nfp_create_area(ARG(1));
    RET(0);
}

HLE(_ZN2nn3nfp5FlushERKNS0_12DeviceHandleE) { RET(0); }
HLE(_ZN2nn3nfp7RestoreERKNS0_12DeviceHandleE) { RET(0); }

HLE(_ZN2nn3nfp10GetTagInfoEPNS0_7TagInfoERKNS0_12DeviceHandleE) {
    uint8_t info[NFP_TAG_INFO_SIZE];
    nfp_poll_scan();
    nfp_load();
    if (nfp_uid_len == 0) nfp_make_uid();
    nfp_tag_info_from_uid(nfp_uid, nfp_uid_len, info);
    if (!nfp_last_tag_valid || memcmp(info, nfp_last_tag_info, sizeof info)) {
        uint32_t protocol = 0, type = 0;
        memcpy(nfp_last_tag_info, info, sizeof info);
        nfp_last_tag_valid = 1;
        memcpy(&protocol, info + 32, sizeof protocol);
        memcpy(&type, info + 36, sizeof type);
        hos_log("nfp: GetTagInfo: length %u, uid %02x%02x%02x%02x%02x%02x%02x%02x%02x%02x, protocol %u, type %u",
                info[10], info[0], info[1], info[2], info[3], info[4], info[5], info[6], info[7], info[8], info[9],
                protocol, type);
    }
    nfp_write(ARG(0), info, sizeof info);
    RET(0);
}

HLE(_ZN2nn3nfp15GetRegisterInfoEPNS0_12RegisterInfoERKNS0_12DeviceHandleE) {
    uint8_t info[NFP_REGISTER_INFO_SIZE];
    int year, month, day;
    nfp_load();
    nfp_date(&year, &month, &day);
    nfp_register_info(info, nfp_tag ? nfp_tag->name : "Hookshot", year, month, day);
    if (!nfp_last_register_valid || memcmp(info, nfp_last_register_info, sizeof info)) {
        uint16_t wrote_year = 0;
        memcpy(nfp_last_register_info, info, sizeof info);
        nfp_last_register_valid = 1;
        memcpy(&wrote_year, info + 0x58, sizeof wrote_year);
        hos_log("nfp: GetRegisterInfo: nickname \"%.40s\", date %04u-%02u-%02u, font %u, mii %02x%02x%02x%02x",
                (const char *)info + 0x5C, wrote_year, info[0x5A], info[0x5B], info[0x85], info[0], info[1], info[2],
                info[3]);
    }
    nfp_write(ARG(0), info, sizeof info);
    RET(0);
}

HLE(_ZN2nn3nfp13GetCommonInfoEPNS0_10CommonInfoERKNS0_12DeviceHandleE) {
    uint8_t info[NFP_COMMON_INFO_SIZE];
    int year, month, day;
    nfp_date(&year, &month, &day);
    nfp_common_info(info, year, month, day);
    if (!nfp_last_common_valid || memcmp(info, nfp_last_common_info, sizeof info)) {
        uint16_t wrote_year = 0, counter = 0;
        uint32_t area = 0;
        memcpy(nfp_last_common_info, info, sizeof info);
        nfp_last_common_valid = 1;
        memcpy(&wrote_year, info, sizeof wrote_year);
        memcpy(&counter, info + 4, sizeof counter);
        memcpy(&area, info + 8, sizeof area);
        hos_log("nfp: GetCommonInfo: date %04u-%02u-%02u, counter %u, version %u, area %u", wrote_year, info[2],
                info[3], counter, info[6], area);
    }
    nfp_write(ARG(0), info, sizeof info);
    RET(0);
}

HLE(_ZN2nn3nfp12GetModelInfoEPNS0_9ModelInfoERKNS0_12DeviceHandleE) {
    uint8_t info[NFP_MODEL_INFO_SIZE];
    nfp_poll_scan();
    nfp_load();
    if (nfp_tag) nfp_model_info_from_id(nfp_tag->id, info);
    else memset(info, 0, sizeof info);
    if (!nfp_last_model_valid || memcmp(info, nfp_last_model_info, sizeof info)) {
        uint16_t numbering = 0;
        memcpy(nfp_last_model_info, info, sizeof info);
        nfp_last_model_valid = 1;
        memcpy(&numbering, info + 4, sizeof numbering);
        hos_log("nfp: GetModelInfo: character %02x%02x%02x, series %02x, numbering %04x, type %02x", info[0],
                info[1], info[2], info[3], numbering, info[6]);
    }
    nfp_write(ARG(0), info, sizeof info);
    RET(0);
}

/* Event registration: the guest's SystemEventType is created here and signalled
   when a tag appears or goes away. The game waits on it with nn::os. */
HLE(_ZN2nn3nfp19AttachActivateEventEPNS_2os15SystemEventTypeERKNS0_12DeviceHandleE) {
    nfp_activate_event = ARG(0);
    hos_log("nfp: AttachActivateEvent %#llx (state %d)", (unsigned long long)nfp_activate_event, nfp_device_state);
    if (nfp_activate_event) {
        hos_system_event_init(nfp_activate_event, 1);
        /* (the virtual tag is always there: a late attach must not miss the event) */
        if (nfp_tag || nfp_device_state == NFP_DEV_ACTIVE || nfp_device_state == NFP_DEV_MOUNT)
            hos_system_event_signal(nfp_activate_event);
    }
    RET(0);
}

HLE(_ZN2nn3nfp21AttachDeactivateEventEPNS_2os15SystemEventTypeERKNS0_12DeviceHandleE) {
    nfp_deactivate_event = ARG(0);
    hos_log("nfp: AttachDeactivateEvent %#llx (state %d)", (unsigned long long)nfp_deactivate_event, nfp_device_state);
    if (nfp_deactivate_event) {
        hos_system_event_init(nfp_deactivate_event, 1);
        if (nfp_device_state == NFP_DEV_DEACTIVE) hos_system_event_signal(nfp_deactivate_event);
    }
    RET(0);
}

HLE(_ZN2nn3nfp29AttachAvailabilityChangeEventEPNS_2os15SystemEventTypeE) {
    hos_log("nfp: AttachAvailabilityChangeEvent %#llx", (unsigned long long)ARG(0));
    if (!ARG(0)) return;
    hos_system_event_init(ARG(0), 1);
    hos_system_event_signal(ARG(0));
}

/* amiibo Settings: the game does not open it for a scan, but a figure's owner
   settings may be read. The tag is reported as registered, with its profile. */
HLE(_ZN2nn3nfp29StartNicknameAndOwnerSettingsEPNS0_12DeviceHandleEPbPNS0_12RegisterInfoERKNS0_24AmiiboSettingsStartParamERKNS0_7TagInfoE) {
    uint8_t handle[8] = {0}, info[NFP_REGISTER_INFO_SIZE];
    int year, month, day;
    nfp_load();
    nfp_date(&year, &month, &day);
    nfp_register_info(info, nfp_tag ? nfp_tag->name : "Hookshot", year, month, day);
    nfp_write(ARG(0), handle, sizeof handle);
    const uint8_t registered = 1;
    nfp_write(ARG(1), &registered, sizeof registered);
    nfp_write(ARG(2), info, sizeof info);
    RET(0);
}

HLE(_ZN2nn3nfp29StartNicknameAndOwnerSettingsEPNS0_12DeviceHandleEPbPNS0_12RegisterInfoERKNS0_24AmiiboSettingsStartParamERKNS0_7TagInfoERKS4_) {
    uint8_t handle[8] = {0}, info[NFP_REGISTER_INFO_SIZE];
    int year, month, day;
    nfp_load();
    nfp_date(&year, &month, &day);
    nfp_register_info(info, nfp_tag ? nfp_tag->name : "Hookshot", year, month, day);
    nfp_write(ARG(0), handle, sizeof handle);
    const uint8_t registered = 1;
    nfp_write(ARG(1), &registered, sizeof registered);
    nfp_write(ARG(2), info, sizeof info);
    RET(0);
}

HLE(_ZN2nn3nfp19StartGameDataEraserEPNS0_12DeviceHandleERKNS0_24AmiiboSettingsStartParamERKNS0_7TagInfoE) {
    uint8_t handle[8] = {0};
    nfp_write(ARG(0), handle, sizeof handle);
    nfp_area_exists = 0;
    nfp_area_size = 0;
    nfp_area_open = 0;
    RET(0);
}

HLE(_ZN2nn3nfp13StartRestorerEPNS0_12DeviceHandleERKNS0_24AmiiboSettingsStartParamERKNS0_7TagInfoE) {
    uint8_t handle[8] = {0};
    nfp_write(ARG(0), handle, sizeof handle);
    RET(0);
}

/* SDK 22 keeps the same functions under nn::nfp::sdk (the Switch 2 SDK moved
   several service libraries a level down). Both names are answered here, so a
   game built against either imports the virtual tag. */
HLE(_ZN2nn3nfp3sdk10InitializeEv) { imp__ZN2nn3nfp10InitializeEv(c); }
HLE(_ZN2nn3nfp3sdk8FinalizeEv) { imp__ZN2nn3nfp8FinalizeEv(c); }
HLE(_ZN2nn3nfp3sdk8GetStateEv) { imp__ZN2nn3nfp8GetStateEv(c); }
HLE(_ZN2nn3nfp3sdk14GetDeviceStateERKNS0_12DeviceHandleE) { imp__ZN2nn3nfp14GetDeviceStateERKNS0_12DeviceHandleE(c); }
HLE(_ZN2nn3nfp3sdk9GetNpadIdEPNS_3hid10NpadIdTypeERKNS0_12DeviceHandleE) { imp__ZN2nn3nfp9GetNpadIdEPNS_3hid10NpadIdTypeERKNS0_12DeviceHandleE(c); }
HLE(_ZN2nn3nfp3sdk9GetNpadIdEPjRKNS0_12DeviceHandleE) { imp__ZN2nn3nfp9GetNpadIdEPjRKNS0_12DeviceHandleE(c); }
HLE(_ZN2nn3nfp3sdk11ListDevicesEPNS0_12DeviceHandleEPii) { imp__ZN2nn3nfp11ListDevicesEPNS0_12DeviceHandleEPii(c); }
HLE(_ZN2nn3nfp3sdk14StartDetectionERKNS0_12DeviceHandleE) { imp__ZN2nn3nfp14StartDetectionERKNS0_12DeviceHandleE(c); }
HLE(_ZN2nn3nfp3sdk13StopDetectionERKNS0_12DeviceHandleE) { imp__ZN2nn3nfp13StopDetectionERKNS0_12DeviceHandleE(c); }
HLE(_ZN2nn3nfp3sdk5MountERKNS0_12DeviceHandleENS0_9ModelTypeE) { imp__ZN2nn3nfp5MountERKNS0_12DeviceHandleENS0_9ModelTypeE(c); }
HLE(_ZN2nn3nfp3sdk5MountERKNS0_12DeviceHandleENS0_9ModelTypeENS0_11MountTargetE) { imp__ZN2nn3nfp5MountERKNS0_12DeviceHandleENS0_9ModelTypeENS0_11MountTargetE(c); }
HLE(_ZN2nn3nfp3sdk7UnmountERKNS0_12DeviceHandleE) { imp__ZN2nn3nfp7UnmountERKNS0_12DeviceHandleE(c); }
HLE(_ZN2nn3nfp3sdk19OpenApplicationAreaERKNS0_12DeviceHandleEj) { imp__ZN2nn3nfp19OpenApplicationAreaERKNS0_12DeviceHandleEj(c); }
HLE(_ZN2nn3nfp3sdk18GetApplicationAreaEPvPyRKNS0_12DeviceHandleEy) { imp__ZN2nn3nfp18GetApplicationAreaEPvPyRKNS0_12DeviceHandleEy(c); }
HLE(_ZN2nn3nfp3sdk18SetApplicationAreaERKNS0_12DeviceHandleEPKvy) { imp__ZN2nn3nfp18SetApplicationAreaERKNS0_12DeviceHandleEPKvy(c); }
HLE(_ZN2nn3nfp3sdk18GetApplicationAreaEPvPmRKNS0_12DeviceHandleEm) { imp__ZN2nn3nfp18GetApplicationAreaEPvPmRKNS0_12DeviceHandleEm(c); }
HLE(_ZN2nn3nfp3sdk18SetApplicationAreaERKNS0_12DeviceHandleEPKvm) { imp__ZN2nn3nfp18SetApplicationAreaERKNS0_12DeviceHandleEPKvm(c); }
HLE(_ZN2nn3nfp3sdk23RecreateApplicationAreaERKNS0_12DeviceHandleERKNS0_25ApplicationAreaCreateInfoE) { imp__ZN2nn3nfp23RecreateApplicationAreaERKNS0_12DeviceHandleERKNS0_25ApplicationAreaCreateInfoE(c); }
HLE(_ZN2nn3nfp3sdk5FlushERKNS0_12DeviceHandleE) { imp__ZN2nn3nfp5FlushERKNS0_12DeviceHandleE(c); }
HLE(_ZN2nn3nfp3sdk7RestoreERKNS0_12DeviceHandleE) { imp__ZN2nn3nfp7RestoreERKNS0_12DeviceHandleE(c); }
HLE(_ZN2nn3nfp3sdk21CreateApplicationAreaERKNS0_12DeviceHandleERKNS0_25ApplicationAreaCreateInfoE) { imp__ZN2nn3nfp21CreateApplicationAreaERKNS0_12DeviceHandleERKNS0_25ApplicationAreaCreateInfoE(c); }
HLE(_ZN2nn3nfp3sdk10GetTagInfoEPNS0_7TagInfoERKNS0_12DeviceHandleE) { imp__ZN2nn3nfp10GetTagInfoEPNS0_7TagInfoERKNS0_12DeviceHandleE(c); }
HLE(_ZN2nn3nfp3sdk15GetRegisterInfoEPNS0_12RegisterInfoERKNS0_12DeviceHandleE) { imp__ZN2nn3nfp15GetRegisterInfoEPNS0_12RegisterInfoERKNS0_12DeviceHandleE(c); }
HLE(_ZN2nn3nfp3sdk13GetCommonInfoEPNS0_10CommonInfoERKNS0_12DeviceHandleE) { imp__ZN2nn3nfp13GetCommonInfoEPNS0_10CommonInfoERKNS0_12DeviceHandleE(c); }
HLE(_ZN2nn3nfp3sdk12GetModelInfoEPNS0_9ModelInfoERKNS0_12DeviceHandleE) { imp__ZN2nn3nfp12GetModelInfoEPNS0_9ModelInfoERKNS0_12DeviceHandleE(c); }
HLE(_ZN2nn3nfp3sdk19AttachActivateEventEPNS_2os15SystemEventTypeERKNS0_12DeviceHandleE) { imp__ZN2nn3nfp19AttachActivateEventEPNS_2os15SystemEventTypeERKNS0_12DeviceHandleE(c); }
HLE(_ZN2nn3nfp3sdk21AttachDeactivateEventEPNS_2os15SystemEventTypeERKNS0_12DeviceHandleE) { imp__ZN2nn3nfp21AttachDeactivateEventEPNS_2os15SystemEventTypeERKNS0_12DeviceHandleE(c); }
HLE(_ZN2nn3nfp3sdk29AttachAvailabilityChangeEventEPNS_2os15SystemEventTypeE) { imp__ZN2nn3nfp29AttachAvailabilityChangeEventEPNS_2os15SystemEventTypeE(c); }
