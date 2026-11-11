/* (hookshot) Journaled save data: the game's writes go to a working copy, and nn::fs::Commit makes them the save in one
   atomic step. host/save_journal.c has the layout, the steps and the recovery rule; host/nn_fs.c calls it. */
#ifndef HOS_SAVE_JOURNAL_H
#define HOS_SAVE_JOURNAL_H
#include <stddef.h>
#include <stdint.h>

#define SJ_PATH 1024
#define SJ_BACKUPS 3   /* (the committed saves before the current one kept in save-backup) */

typedef struct {
    char save[SJ_PATH];      /* <user>/save/<uid>: the committed save, the folder the emulators' layout has */
    char tx[SJ_PATH];        /* <user>/save-tx/<uid>: the working copy and the commits waiting */
    char work[SJ_PATH];      /* <tx>/work: the working copy, the save mount's root */
    char work_base[SJ_PATH]; /* <tx>/work.base: the fingerprint of the save the working copy was made over */
    char fresh[SJ_PATH];     /* <tx>/new: the next working copy, being made */
    char old[SJ_PATH];       /* <tx>/old: the committed save a commit replaced, on its way to save-backup */
    char backups[SJ_PATH];   /* <user>/save-backup/<uid>: the SJ_BACKUPS saves before the current one */
    char ready[SJ_PATH];     /* <tx>/ready-<n>: a finished commit not swapped in yet (the newest save), "" when none */
    unsigned ready_seq;      /* the highest ready-<n> made or found */
    int crash_at, step, dead;   /* (tests: the commit stops at its crash_at-th step, as a process killed there would) */
    void (*crash)(int step);    /* (and calls this there, when set: HOS_SAVE_CRASH_AT ends the process) */
    intptr_t lock;              /* (the session lock's file, while locked) */
    int locked;
} SaveJournal;

/* Where messages go (hos_log in the game; NULL: nowhere) */
extern void (*sj_log)(const char *fmt, ...);

/* The paths of user id folder uid (its name) under the data folder user. 0 when they do not fit */
int sj_paths(SaveJournal *j, const char *user, const char *uid);
/* The session lock, <tx>/lock, held until the process ends (or sj_unlock): 0 taken; 1 another process (a second Hookshot on
   the same data folder) holds it, and this one must leave the journal alone: no recovery, no working copy; -1 an error */
int sj_lock(SaveJournal *j);
void sj_unlock(SaveJournal *j);
/* Why the journal cannot be used for this save, or NULL: the save folder or the folder of saves is a link, or it is on
   another volume than save-tx and save-backup (a rename between them would be a copy) */
const char *sj_unsuitable(SaveJournal *j);
/* At start, before the save is used: finish or roll back a commit a crash interrupted, and set aside the working copy a
   run left (changes no Commit took: never loaded). Returns what it did, for the log */
const char *sj_recover(SaveJournal *j);
/* The newest save: a finished commit still waiting to be swapped in, else the committed save */
const char *sj_newest(const SaveJournal *j);
/* Without the journal's lock or recovery (a run with the journal off): the newest save, a commit waiting in save-tx
   made over the save as it is included. Changes nothing on disk */
const char *sj_peek_newest(SaveJournal *j);
/* A fresh working copy of the newest save (the committed save is made, empty, when there is none). 0 on success; -1 when
   it could not be made (a full disk, or a working copy left that cannot be set aside): the run writes the newest save in
   place; -2 when no save may be mounted at all (a rollback that failed left the save in <tx>/old) */
int sj_work_open(SaveJournal *j);
/* The working copy and what it held, gone (the last unmount) */
void sj_work_drop(SaveJournal *j);
/* Commit: the working copy becomes the save, by renames only. 0 on success (*changed: 0 when it held the save's bytes
   already, and nothing was written); 1 committed, but no next working copy could be made: the rest of the run writes the
   newest save in place; -1 nothing committed (the save as it was, the working copy still the mount). what: for the log */
int sj_commit(SaveJournal *j, int *changed, char *what, size_t cap);

#endif
