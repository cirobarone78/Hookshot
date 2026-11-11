---
title: Is Hookshot a virus?
description: The maintainer's explanation of Windows Defender alerts, signing status, and links to the source code.
---

**The maintainer identifies the reported Windows Defender detections as false positives.**
The evidence and discussion are collected in [issue #1003](https://github.com/NotRexed/Hookshot/issues/1003).
This documentation has not independently audited the release binaries.

## Why does Defender flag it?

Windows Defender can flag or quarantine `HookshotBuilder.exe` as `Trojan:Script/Wacatac.H!ml`.
The maintainer explains that `!ml` denotes a machine-learning detection and that new, unsigned executables can
trigger it. The thread also contains reports of other detection names.

A detection name alone does not establish whether a particular download is safe. Use the
[official releases](https://github.com/NotRexed/Hookshot/releases) and review the
[linked reports](https://github.com/NotRexed/Hookshot/issues/1003).

## Is it signed?

As checked on **November 10, 2026**, the maintainer says they have applied for code signing through SignPath
and the builder is not yet signed. Follow [#1003](https://github.com/NotRexed/Hookshot/issues/1003)
for updates.

## Can I inspect it or build it myself?

Yes. Hookshot is open source. You can [review the code](https://github.com/NotRexed/Hookshot)
and follow the [development guide](https://github.com/NotRexed/Hookshot/blob/main/docs/development.md) to build from source if you prefer that
to the provided binaries. Source availability makes review possible; it is not itself a security audit.
