"""The test rig's made-up releases and its scratch install: python -I rig.py <rig folder> <port>
www/: what a local web server hands out (each release's setup list and its parts, as scripts/make_setup_parts.py lays them out).
base/: a HookshotBuilder folder (HOOKSHOT_SETUP_BASE) with v2.1.0 installed and in use. game/, game-dev/: a game folder holding
v2.1.0 and a dev build beside it. The versions' python.exe is fakepy.exe (it plays make_game.py's part)."""
import hashlib
import os
import shutil
import sys
import zipfile

rig, port = sys.argv[1], sys.argv[2]
fake = os.path.join(rig, "fakepy.exe")
www, base = os.path.join(rig, "www"), os.path.join(rig, "base")
for d in (www, base, os.path.join(rig, "game"), os.path.join(rig, "game-dev")):
    shutil.rmtree(d, ignore_errors=True)
os.makedirs(www)


def sha(path):
    return hashlib.sha256(open(path, "rb").read()).hexdigest()


def zipped(name, files):
    """files: {path in the zip: bytes or a file to copy}"""
    tmp = os.path.join(www, name + ".tmp")
    with zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED) as z:
        for arc, src in files.items():
            if isinstance(src, bytes):
                z.writestr(arc, src)
            else:
                z.write(src, arc)
    return tmp


# (one python part for every version, as a release keeps a part that did not change: its checksum is in v2.1.0's parts.txt)
tmp = zipped("python", {"python/python.exe": fake, "python/readme.txt": b"the test rig's stand-in for Python\n"})
python_sha = sha(tmp)
python_zip = f"HookshotBuilder-python-{python_sha[:12]}.zip"
os.replace(tmp, os.path.join(www, python_zip))


def release(tag, python_part=True):
    tmp = zipped("app-" + tag, {
        "HookshotBuilder/HookshotBuilder.exe": fake,   # (only its being there is checked)
        "HookshotBuilder/tools/version.txt": (tag + "\n").encode(),
        "HookshotBuilder/tools/nx2/make_game.py": b"# the test rig's stand-in: fakepy.exe plays this part\n",
    })
    app_sha = sha(tmp)
    app = os.path.join(www, f"app-{tag}.zip")
    os.replace(tmp, app)
    lines = [f"tag {tag}", f"part {app_sha} {os.path.getsize(app)} . - - http://127.0.0.1:{port}/app-{tag}.zip"]
    if python_part:
        lines.append(f"part {python_sha} {os.path.getsize(os.path.join(www, python_zip))} HookshotBuilder/tools - - http://127.0.0.1:{port}/{python_zip}")
    lines.append("run HookshotBuilder/HookshotBuilder.exe")
    open(os.path.join(www, f"list-{tag}.txt"), "w", newline="\n").write("\n".join(lines) + "\n")


for tag in ("v2.2.0-rc.1", "v2.2.0", "v2.0.14"):
    release(tag)

# the scratch install: v2.1.0, the version in use
tools = os.path.join(base, "versions", "v2.1.0", "HookshotBuilder", "tools")
os.makedirs(os.path.join(tools, "nx2"))
os.makedirs(os.path.join(tools, "python"))
shutil.copy(fake, os.path.join(tools, "python", "python.exe"))
open(os.path.join(tools, "python", "readme.txt"), "w").write("the test rig's stand-in for Python\n")
open(os.path.join(tools, "nx2", "make_game.py"), "w").write("# stand-in\n")
open(os.path.join(tools, "version.txt"), "w").write("v2.1.0\n")
shutil.copy(fake, os.path.join(base, "versions", "v2.1.0", "HookshotBuilder", "HookshotBuilder.exe"))
open(os.path.join(base, "versions", "v2.1.0", "installed.txt"), "w").write("v2.1.0")
open(os.path.join(base, "versions", "v2.1.0", "parts.txt"), "w", newline="\n").write(python_sha + "\n")
open(os.path.join(base, "versions", "current.txt"), "w").write("v2.1.0")

# the game folder (it keeps its game files: it can be built as another release) and a dev build beside it
game = os.path.join(rig, "game")
for d in (".hookshot_exefs", "romfs", "bin"):
    os.makedirs(os.path.join(game, d))
open(os.path.join(game, "hookshot_version.txt"), "w").write("version=v2.1.0\n")
open(os.path.join(game, "bin", "hookshot.exe"), "w").close()
dev = os.path.join(rig, "game-dev")
os.makedirs(os.path.join(dev, "bin"))
open(os.path.join(dev, "bin", "hookshot.exe"), "w").close()
open(os.path.join(dev, "hookshot_build.txt"), "w").write("name=pre-2.1.1 53ac43d\nchannel=dev\n")
print("rig made:", sorted(os.listdir(www)))
