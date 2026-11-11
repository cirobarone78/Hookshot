/* The virtual amiibo a scan presents (host/nn_nfp.c), and the layouts the game's
   nn::nfp calls write. Pure C: no guest memory and no host calls, so a test can
   compile this header alone (tests/test_amiibo.py).

   The ids are the 8 bytes an amiibo's ID entry carries, as they appear in a
   dump: three character bytes, the variant, two numbering bytes (big-endian),
   the series and the format version. 0x01000000034b0902 is "Link - Ocarina of
   Time": character 01 00 00, series 09 (The Legend of Zelda), numbering 034b. */
#ifndef NFP_AMIIBO_H
#define NFP_AMIIBO_H

#include <stddef.h>
#include <stdint.h>
#include <string.h>

#define NFP_AMIIBO_ID_SIZE 8
#define NFP_APP_AREA_SIZE 0xD8
#define NFP_TAG_INFO_SIZE 0x58
#define NFP_REGISTER_INFO_SIZE 0x100
#define NFP_COMMON_INFO_SIZE 0x40
#define NFP_MODEL_INFO_SIZE 0x40

typedef struct NfpAmiibo {
    const char *key;       /* HOS_AMIIBO=, amiibo=, and the menu's name */
    const char *name;      /* the figure, for the log */
    const char *effect;    /* what the game does with it */
    uint8_t id[NFP_AMIIBO_ID_SIZE];
    int zelda;             /* a Zelda series figure: the game gives items */
} NfpAmiibo;

/* (The first profile is the default: the Ocarina of Time Link figure, which the
   game recognizes for the random item reward. The two 2026 figures' retail ids
   are not public yet; oot-young-link/oot-young-zelda use the series' next free
   numbering so their masks can be tried before the figures ship. A real figure's
   id, HOS_AMIIBO=0x..., presents exactly that one.) */
static const NfpAmiibo nfp_amiibos[] = {
    {"link-oot", "Link (Ocarina of Time)", "a random item Link has already found (Zelda series)",
     {0x01, 0x00, 0x00, 0x00, 0x03, 0x4b, 0x09, 0x02}, 1},
    {"zelda-botw", "Zelda (Breath of the Wild)", "a random item Link has already found (Zelda series)",
     {0x01, 0x01, 0x00, 0x00, 0x03, 0x56, 0x09, 0x02}, 1},
    {"young-link", "Young Link (Super Smash Bros.)", "a random item Link has already found (Zelda series)",
     {0x01, 0x00, 0x00, 0x00, 0x03, 0x7c, 0x00, 0x02}, 1},
    {"young-zelda", "Zelda (Super Smash Bros.)", "a random item Link has already found (Zelda series)",
     {0x01, 0x01, 0x00, 0x00, 0x00, 0x0e, 0x00, 0x02}, 1},
    {"oot-young-link", "Young Link (Ocarina of Time 2026)", "Mask 101, the blocky Young Link mask",
     {0x01, 0x00, 0x00, 0x00, 0x04, 0x00, 0x09, 0x02}, 1},
    {"oot-young-zelda", "Young Zelda (Ocarina of Time 2026)", "Mask 102, the blocky Young Zelda mask",
     {0x01, 0x01, 0x00, 0x00, 0x04, 0x01, 0x09, 0x02}, 1},
    {"mario", "Mario", "not supported by this game: it says the amiibo does not work",
     {0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x02}, 0},
};
static const int nfp_amiibo_count = (int)(sizeof nfp_amiibos / sizeof nfp_amiibos[0]);

static int nfp_ieq(const char *a, const char *b) {
    while (*a && *b) {
        int ca = (unsigned char)*a++, cb = (unsigned char)*b++;
        if (ca >= 'A' && ca <= 'Z') ca += 'a' - 'A';
        if (cb >= 'A' && cb <= 'Z') cb += 'a' - 'A';
        if (ca != cb) return 0;
    }
    return *a == *b;
}

static int nfp_hex_digit(char c) {
    if (c >= '0' && c <= '9') return c - '0';
    if (c >= 'a' && c <= 'f') return c - 'a' + 10;
    if (c >= 'A' && c <= 'F') return c - 'A' + 10;
    return -1;
}

/* 16 hex digits, with or without 0x: the id of a real or virtual figure */
static int nfp_parse_id(const char *text, uint8_t out[NFP_AMIIBO_ID_SIZE]) {
    if (!text) return 0;
    if (text[0] == '0' && (text[1] == 'x' || text[1] == 'X')) text += 2;
    if (strlen(text) != NFP_AMIIBO_ID_SIZE * 2) return 0;
    for (int i = 0; i < NFP_AMIIBO_ID_SIZE; i++) {
        const int hi = nfp_hex_digit(text[i * 2]), lo = nfp_hex_digit(text[i * 2 + 1]);
        if (hi < 0 || lo < 0) return 0;
        out[i] = (uint8_t)((hi << 4) | lo);
    }
    return text[NFP_AMIIBO_ID_SIZE * 2] == '\0';
}

static const NfpAmiibo *nfp_profile_by_key(const char *key) {
    if (!key) return NULL;
    for (int i = 0; i < nfp_amiibo_count; i++)
        if (nfp_ieq(key, nfp_amiibos[i].key) || nfp_ieq(key, nfp_amiibos[i].name)) return &nfp_amiibos[i];
    return NULL;
}

static const NfpAmiibo *nfp_profile_by_index(int index) {
    return index >= 0 && index < nfp_amiibo_count ? &nfp_amiibos[index] : NULL;
}

/* the game's ModelInfo, from the id (nn::nfp::ModelInfo, 0x40 bytes) */
static void nfp_model_info_from_id(const uint8_t id[NFP_AMIIBO_ID_SIZE], uint8_t out[NFP_MODEL_INFO_SIZE]) {
    memset(out, 0, NFP_MODEL_INFO_SIZE);
    out[0] = id[0], out[1] = id[1], out[2] = id[2];   /* character id */
    out[3] = id[6];                                   /* series id */
    out[4] = id[5], out[5] = id[4];                   /* numbering id, the uint16_t in memory (little-endian) */
    out[6] = id[3];                                   /* nfp type */
}

/* the game's TagInfo, from a tag UID (nn::nfp::TagInfo, 0x58 bytes). An NTAG215
   amiibo is NFC-A / TYPE2; the game reads the UID and may check the two. */
static void nfp_tag_info_from_uid(const uint8_t *uid, int uid_len, uint8_t out[NFP_TAG_INFO_SIZE]) {
    memset(out, 0, NFP_TAG_INFO_SIZE);
    if (uid_len < 0) uid_len = 0;
    if (uid_len > 10) uid_len = 10;
    if (uid && uid_len > 0) memcpy(out, uid, (size_t)uid_len);
    out[10] = (uint8_t)uid_len;
    out[32] = 1;   /* protocol: NfcProtocol_TypeA */
    out[36] = 2;   /* type: TagType_Type2 */
}

/* the game's CommonInfo (nn::nfp::CommonInfo, 0x40 bytes) */
static void nfp_common_info(uint8_t out[NFP_COMMON_INFO_SIZE], int year, int month, int day) {
    memset(out, 0, NFP_COMMON_INFO_SIZE);
    out[0] = (uint8_t)year, out[1] = (uint8_t)(year >> 8);
    out[2] = (uint8_t)month, out[3] = (uint8_t)day;
    out[4] = 0, out[5] = 0;   /* write counter */
    out[6] = 1;               /* NFP version */
    out[8] = NFP_APP_AREA_SIZE & 0xFF, out[9] = (NFP_APP_AREA_SIZE >> 8) & 0xFF,
    out[10] = (NFP_APP_AREA_SIZE >> 16) & 0xFF, out[11] = (NFP_APP_AREA_SIZE >> 24) & 0xFF;
}

/* the game's RegisterInfo (nn::nfp::RegisterInfo, 0x100 bytes). The Mii is left
   empty; the nickname is what the game shows. */
static void nfp_register_info(uint8_t out[NFP_REGISTER_INFO_SIZE], const char *nickname, int year, int month, int day) {
    memset(out, 0, NFP_REGISTER_INFO_SIZE);
    out[0x58] = (uint8_t)year, out[0x59] = (uint8_t)(year >> 8);
    out[0x5A] = (uint8_t)month, out[0x5B] = (uint8_t)day;
    if (nickname) {
        size_t n = strlen(nickname);
        if (n > 40) n = 40;
        memcpy(out + 0x5C, nickname, n);
    }
    out[0x85] = 0;   /* FontRegion_JpUsEu */
}

/* A stable UID for a profile: the game remembers which figures were scanned by
   their UID. Seven bytes, as an NTAG215 has. */
static void nfp_uid_from_id(const uint8_t id[NFP_AMIIBO_ID_SIZE], uint8_t uid[10], int *len) {
    uint32_t h = 2166136261u;
    for (int i = 0; i < NFP_AMIIBO_ID_SIZE; i++) h = (h ^ id[i]) * 16777619u;
    for (int i = 0; i < 7; i++) {
        uid[i] = (uint8_t)(h >> (i * 4));
        h = h * 1664525u + 1013904223u;
    }
    for (int i = 7; i < 10; i++) uid[i] = 0;
    *len = 7;
}

/* A custom id's effect, for the log: the game decides, but its Zelda figures
   give items and the rest are refused. */
static const char *nfp_effect_from_id(const uint8_t id[NFP_AMIIBO_ID_SIZE]) {
    if (id[6] == 0x09 || (id[0] == 0x01 && (id[1] == 0x00 || id[1] == 0x01)))
        return "a random item Link has already found (Zelda series)";
    return "not supported by this game: it says the amiibo does not work";
}

#endif
