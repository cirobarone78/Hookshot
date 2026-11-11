"""requirements-lock.txt: the SHA-256 of every wheel the shipped Python may install for requirements.txt's pins.

The tools' Python that releases ship gets its packages from PyPI: scripts/linux/deps.sh installs requirements.txt into
the AppImage's Python, and scripts/release_parts.py package --python-packages installs nx2/prompt_requirements.txt's
into the Windows builder's Python part. Both install with pip's --require-hashes from requirements-lock.txt, so a wheel
that is not one of the files PyPI had for that version when the lock was written is refused, as every other download
the release makes is checked against its SHA-256.

The lock lists, for each pin (name==version), the wheels for the systems a release ships: Linux x86_64 (manylinux) and
Windows x64, every CPython version and the version-independent (py3, abi3) ones.

python -I scripts/python_lock.py            write requirements-lock.txt from PyPI (after a pin changes)
python -I scripts/python_lock.py --check    offline: every pin is in the lock, at its version, with a hash
"""
import argparse
import json
import os
import re
import sys
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REQUIREMENTS = os.path.join(ROOT, "requirements.txt")
LOCK = os.path.join(ROOT, "requirements-lock.txt")
PIN = re.compile(r"^([A-Za-z0-9][A-Za-z0-9._-]*)==([A-Za-z0-9.+!_-]+)$")
SHA = re.compile(r"^[0-9a-f]{64}$")


def norm(name):
    return re.sub(r"[-_.]+", "-", name).lower()


def pins(path=REQUIREMENTS):
    """name==version pins of a requirements file and the files it includes with -r, in order"""
    out = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.split("#")[0].strip()
            if not line:
                continue
            if line.startswith("-r "):
                out += pins(os.path.join(os.path.dirname(path), line[3:].strip()))
                continue
            m = PIN.match(line)
            if not m:
                raise SystemExit("%s: %r is not a name==version pin" % (os.path.relpath(path, ROOT), line))
            out.append((m.group(1), m.group(2)))
    return out


def read_lock(path=LOCK):
    """{normalized name: (name, version, [sha256...])} of a lock file"""
    out = {}
    with open(path, encoding="utf-8") as f:
        text = f.read().replace("\\\n", " ")
    for line in text.splitlines():
        line = line.split("#")[0].strip()
        if not line:
            continue
        words = line.split()
        m = PIN.match(words[0])
        if not m:
            raise SystemExit("%s: %r is not a pin" % (os.path.basename(path), words[0]))
        hashes = []
        for w in words[1:]:
            if not (w.startswith("--hash=sha256:") and SHA.match(w[14:])):
                raise SystemExit("%s: %s: %r is not --hash=sha256:<64 hex>" % (os.path.basename(path), words[0], w))
            hashes.append(w[14:])
        out[norm(m.group(1))] = (m.group(1), m.group(2), hashes)
    return out


def check(requirements=REQUIREMENTS, lock=LOCK):
    """the problems of a lock against the pins (empty: it fits)"""
    have = read_lock(lock)
    bad = []
    for name, version in pins(requirements):
        got = have.get(norm(name))
        if not got:
            bad.append("%s==%s is not in the lock" % (name, version))
        elif got[1] != version:
            bad.append("%s: pinned %s, locked %s" % (name, version, got[1]))
        elif not got[2]:
            bad.append("%s==%s has no hash" % (name, version))
    return bad


def shipped(filename):
    """a wheel a release's Python could take: Linux x86_64 (manylinux) or Windows x64, CPython or version-independent"""
    if not filename.endswith(".whl"):
        return False
    _, _, rest = filename[:-4].partition("-")
    tags = rest.split("-")[-3:]
    if len(tags) != 3:
        return False
    py, abi, plat = tags
    if not any(p.startswith(("cp3", "py3")) for p in py.split(".")):
        return False
    return any(p == "any" or p == "win_amd64" or (p.startswith("manylinux") and p.endswith("_x86_64"))
               for p in plat.split("."))


def write(requirements=REQUIREMENTS, lock=LOCK):
    lines = ["# Written by scripts/python_lock.py from requirements.txt's pins and PyPI: do not edit by hand.",
             "# The wheels of each pin for Linux x86_64 and Windows x64; installed with pip --require-hashes."]
    for name, version in pins(requirements):
        with urllib.request.urlopen("https://pypi.org/pypi/%s/%s/json" % (name, version), timeout=60) as r:
            meta = json.load(r)
        hashes = sorted({u["digests"]["sha256"] for u in meta["urls"] if shipped(u["filename"])})
        if not hashes:
            raise SystemExit("%s==%s: no wheel for Linux x86_64 or Windows x64 on PyPI" % (name, version))
        lines.append("%s==%s \\" % (name, version))
        lines += ["    --hash=sha256:%s%s" % (h, " \\" if i + 1 < len(hashes) else "") for i, h in enumerate(hashes)]
    with open(lock, "w", encoding="utf-8", newline="\n") as f:
        f.write("\n".join(lines) + "\n")
    print("%s: %d pins" % (os.path.relpath(lock, ROOT), len(pins(requirements))))


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--check", action="store_true")
    a = p.parse_args()
    if a.check:
        bad = check()
        for b in bad:
            print(b)
        return 1 if bad else 0
    write()
    return 0


if __name__ == "__main__":
    sys.exit(main())
