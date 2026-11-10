"""NVIDIA Streamline's SDK files for a local Windows build with NVIDIA DLSS Frame Generation (HOOKSHOT_SL_SDK,
gpu/vk/vk_dlssg.cpp).

NVIDIA's files are not part of Hookshot and are never committed or bundled: Streamline is under its own license (the SDK's
license.txt), DLSS Frame Generation's runtime under the NVIDIA RTX SDKs license (nvngx_dlss.license.txt) and Reflex's under
NVIDIA's (reflex.license.txt), each fetched beside the files; read them before using them. Since Streamline 2.7.32 its
binaries are only in its release zip, not in its repository, so this downloads the zip of one pinned release, checks its
SHA-256, and takes out of it, each file checked against its own SHA-256, into <sdk folder> in the SDK's own layout:
  - the licenses and the SDK's headers (include/): what the build reads;
  - the runtime the game loads from beside hookshot.exe (bin/x64/): sl.interposer.dll, sl.common.dll, sl.dlss_g.dll,
    sl.reflex.dll, sl.pcl.dll, nvngx_dlssg.dll and NvLowLatencyVk.dll.
The zip (276 MB) is deleted once its files are out, and a run that finds every file there and right downloads nothing.
For the Windows game only (a Linux PC can fetch it for a build with RX_TARGET=windows): Streamline has no Linux runtime.

Usage:  python -I scripts/sl_sdk.py [--accept-nvidia-license] [--game <game folder>] [--build-only] [<sdk folder>]
  <sdk folder>: default work/sl-sdk
  --game: the runtime copied beside the game's hookshot.exe too (<game folder>/bin when it has one, else the folder itself;
          nx2/make_game.py does the same for the folder it builds when HOOKSHOT_SL_SDK is set)
  --build-only: only what the build reads, not the runtime (a compile check)
  --accept-nvidia-license: NVIDIA's licenses accepted without the question (scripts, the Hookshot Builder, CI)
Then build with HOOKSHOT_SL_SDK=<sdk folder>.
"""
import argparse
import hashlib
import os
import shutil
import sys
import urllib.request
import zipfile

VERSION = "2.14.16"
ZIP = "streamline-sdk-v%s.zip" % VERSION
URL = "https://github.com/NVIDIA-RTX/Streamline/releases/download/v%s/%s" % (VERSION, ZIP)
ZIP_SHA256 = "32041e51db0cab709a271b72a352281b690c2abbd669a827809401a5dd23956b"
RELEASE_URL = "https://github.com/NVIDIA-RTX/Streamline/releases/tag/v%s" % VERSION
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# (path in the zip and in the SDK folder, its SHA-256): what the build reads, and the licenses
BUILD = [
    ("license.txt", "7b6f23e7d6f3ad6292f9308d2b42cdc3d82ae4e9b2abb55f230279d83bedd43d"),
    ("bin/x64/nvngx_dlss.license.txt", "3027f23ca5a46dd9cb8183fbd522983a86f64d7daac5982912bf9f214671f294"),
    ("bin/x64/reflex.license.txt", "ebf83c07fb3b2939908c3795d887afde3161c89a28ba391724efc784ce1bdabe"),
    ("include/sl.h", "e1e81a7428d15b30db37587e9469bd68a56d630d820a4accec0aee3b17e157dd"),
    ("include/sl_appidentity.h", "1337385ac9867d66fa6beb34c750e79aaf25a74a156a47e83f24937299dade87"),
    ("include/sl_consts.h", "17de74afda2cb96204ff380464bed926f660d92015fe0304dff4e329509c88b9"),
    ("include/sl_core_api.h", "328dc3a2c1dee579c200ca97e2d5b1ec38c893be4ba2745ef5ad506af7172e81"),
    ("include/sl_core_types.h", "f420cb052ce14489fc9fa0d933c3ed81a010deb01fa13b1aa8d45da1c5ba3234"),
    ("include/sl_deepdvc.h", "c6086ffe6b1e00588368fdb91e4ab9dd9617624e0e4344cd503a2ca73e46d1a4"),
    ("include/sl_device_wrappers.h", "af7741305b1a468c3a83efaa2005ecd53d2ffd7aadb8ec6868c9dcb4a8a8e3a1"),
    ("include/sl_directsr.h", "65d4e68b2a0f0425ea4d381379172197b81352a50a5e399a8e8f51953e765c71"),
    ("include/sl_dlss.h", "d2c8c61fa71794c8ba424cebce5b3079ebfab8e47ed98b4b00cf8b257ecfd6b5"),
    ("include/sl_dlss_d.h", "6e51cf9815301c597d0657970a668147e34a20db5a76d0af254ec11248f5c4fe"),
    ("include/sl_dlss_g.h", "1fc18cbe004e280df1f787276d08a1b28b8a8c4c65856fbaa659f56dff6a915d"),
    ("include/sl_helpers.h", "48629edbf25dfdb6444c91235fc278f0f9a5878243fae83204c5906ce9eacd8a"),
    ("include/sl_helpers_vk.h", "82604567d239d00ac0ac2270cec744f6f11266e1d9d5187a95d4954f76d8c41c"),
    ("include/sl_hooks.h", "cfeff70a52e1cc012cf4c955a15cc9d0b290f7e084dcb3c0168a9af06ff8f122"),
    ("include/sl_matrix_helpers.h", "a65758d85abba1e12845d266d7d5e36aaefa952383cdf093f3143cd6d8653341"),
    ("include/sl_nis.h", "f45be3cf149200e1eae081cd144c95726a7a290a89822a5d52b9f538e52484aa"),
    ("include/sl_nvperf.h", "025f9f1c8482e75a90f8b8efccdc9cfc53a9fc8b05ba3acc6c3783708b66bd69"),
    ("include/sl_pcl.h", "f43c5135fc8d5349ccd345e424f8cf1f61953a9f17e9897204b0741a3ab7b0fb"),
    ("include/sl_reflex.h", "3b623a1189e04a686384d224a58c4ad9974c4e6e3204077676f6ec529475164c"),
    ("include/sl_result.h", "2a0f6c12863bdc00b38910a5ec85d1f083c5671ee817a920afe626ac2a9100f7"),
    ("include/sl_security.h", "a36b1c20394402bee7ce738089a5a1305ff6e9dd9dd517566154ce834f7c32b4"),
    ("include/sl_struct.h", "28deda67ea1a74371dd4f33ff4842b7db03b2db007001da6db06f6982297928d"),
    ("include/sl_template.h", "af2d4a61361f2603872dcb6edc86cc9e18912762a5c03e6a782ff39a8c3b871b"),
    ("include/sl_version.h", "2a43f565b45a07d4a4259dc61038ec93a7fb8ce7cb3509ea1fbeeb217f9a1ce8"),
]
# the runtime gpu/vk/vk_dlssg.cpp loads from beside hookshot.exe: Streamline's interposer and the plugins it asks for (DLSS
# Frame Generation, Reflex, PCL: sl.common is every plugin's), DLSS Frame Generation's own network and Reflex's Vulkan library
RUNTIME = [
    ("bin/x64/sl.interposer.dll", "b1d7395aebd7b9722841d64dcf7433680020b6a8e421f851c16d5ba0c2182edf"),
    ("bin/x64/sl.common.dll", "38eea3b4209afc455636ea372b5933d65fcc13becec6c84d101dcfc4d8648f75"),
    ("bin/x64/sl.dlss_g.dll", "3ed9538df724993bea8a050195a6a78b9c8c8a566d5b05ade477aab3c390e90f"),
    ("bin/x64/sl.reflex.dll", "443577e869352436ff7ec8f4d9c90418d3e95368436ce219261e0f4f07a38122"),
    ("bin/x64/sl.pcl.dll", "5698c38e722318681f215c9fe68e45b9bedd51378acc699d8eee26e961e57770"),
    ("bin/x64/nvngx_dlssg.dll", "8d59d49b36410dd6b62fef2503a5871d347415bd85d943fa0848563a95dd50c7"),
    ("bin/x64/NvLowLatencyVk.dll", "2a77dc3e1c724b7eea5755be0ae7423752e79a2459fae72181a9f00e3507e5d6"),
]

NOTICE = """\
NVIDIA DLSS Frame Generation: this downloads NVIDIA Streamline's SDK (release v%s, %s) from
github.com/NVIDIA-RTX/Streamline:
  %s
NVIDIA's files are NVIDIA's, not Hookshot's, and are under NVIDIA's licenses: Streamline's (license.txt), the NVIDIA RTX SDKs
license for DLSS Frame Generation (bin/x64/nvngx_dlss.license.txt) and NVIDIA's for Reflex (bin/x64/reflex.license.txt),
saved beside the files. Using them means accepting them. Hookshot never includes or redistributes them: they stay on this
PC, in the SDK folder and beside the game's hookshot.exe. Never share a game folder built with them.""" % (VERSION, ZIP, RELEASE_URL)


def files(runtime=True):
    """[(path in the zip and in the SDK folder, SHA-256)]; runtime=False: what the build reads only (and the licenses)"""
    return BUILD + (RUNTIME if runtime else [])


def runtime_names():
    """The runtime's file names, as they go beside hookshot.exe"""
    return [p.rsplit("/", 1)[1] for p, _ in RUNTIME]


def runtime(sdk):
    """The runtime's files in this SDK folder"""
    return [os.path.join(sdk, *p.split("/")) for p, _ in RUNTIME]


def headers(sdk):
    """This SDK folder has the headers the build reads (what nx2/build.py looks for)"""
    return os.path.isfile(os.path.join(sdk, "include", "sl.h"))


def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


TIMEOUT = 60   # (seconds without an answer, or between two reads, before the download gives up: a stalled one ends the build)


def missing(sdk, runtime=True):
    """The files of the table not in the SDK folder, or not the files expected (SHA-256)"""
    return [(p, d) for p, d in files(runtime)
            if not (os.path.isfile(os.path.join(sdk, *p.split("/"))) and sha256(os.path.join(sdk, *p.split("/"))) == d)]


def extract_one(z, path, digest, dst):
    """One file out of the zip into dst, through dst.part: moved in only when its SHA-256 is the expected one, otherwise
    deleted and ValueError says which"""
    try:
        info = z.getinfo(path)
    except KeyError:
        raise ValueError("sl-sdk: %s is not in %s" % (path, ZIP)) from None
    os.makedirs(os.path.dirname(dst) or ".", exist_ok=True)
    tmp = dst + ".part"
    try:
        h = hashlib.sha256()
        with z.open(info) as r, open(tmp, "wb") as f:
            for block in iter(lambda: r.read(1 << 20), b""):
                h.update(block)
                f.write(block)
        if h.hexdigest() != digest:
            raise ValueError("sl-sdk: %s is not the file expected (SHA-256): not used" % path)
        os.replace(tmp, dst)
    finally:
        if os.path.exists(tmp):
            os.remove(tmp)


def fetch(sdk, opener=urllib.request.urlopen, say=print, runtime=True):
    """Every file of the table into the SDK folder (runtime=False: not the runtime): only when one is missing or not the file
    expected is the zip downloaded, checked, the files taken out of it, and the zip deleted. True when anything was fetched"""
    todo = missing(sdk, runtime)
    if not todo:
        return False
    os.makedirs(sdk, exist_ok=True)
    archive = os.path.join(sdk, ZIP)
    tmp = archive + ".part"
    try:
        say("sl-sdk: downloading %s (276 MB)" % ZIP)
        with opener(URL, timeout=TIMEOUT) as r, open(tmp, "wb") as f:
            shutil.copyfileobj(r, f, 1 << 20)
        if sha256(tmp) != ZIP_SHA256:
            raise ValueError("sl-sdk: %s is not the file expected (SHA-256): not used" % ZIP)
        os.replace(tmp, archive)
        with zipfile.ZipFile(archive) as z:
            for path, digest in todo:
                extract_one(z, path, digest, os.path.join(sdk, *path.split("/")))
                say("sl-sdk: %s" % path)
    finally:
        for left in (tmp, archive):
            if os.path.exists(left):
                os.remove(left)
    return True


def install_runtime(sdk, folder):
    """The SDK folder's runtime copied into folder (made when missing), beside hookshot.exe: the files placed"""
    os.makedirs(folder, exist_ok=True)
    placed = []
    for src in runtime(sdk):
        dst = os.path.join(folder, os.path.basename(src))
        if not (os.path.isfile(dst) and os.path.getsize(dst) == os.path.getsize(src) and sha256(dst) == sha256(src)):
            shutil.copyfile(src, dst + ".part")
            os.replace(dst + ".part", dst)
        placed.append(dst)
    return placed


def beside_exe(game):
    """Where hookshot.exe is in a game folder: bin when the folder has the builder's launcher layout, else the folder"""
    return os.path.join(game, "bin") if os.path.isdir(os.path.join(game, "bin")) else game


def accepted(flag, ask=input, interactive=None):
    """NVIDIA's licenses, accepted: the flag, or a typed yes when there is someone to ask"""
    if flag:
        return True
    if not (sys.stdin.isatty() if interactive is None else interactive):
        return False
    try:
        return ask("Do you accept NVIDIA's licenses? Type yes to go on: ").strip().lower() in ("y", "yes")
    except EOFError:
        return False


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    p.add_argument("sdk", nargs="?")
    p.add_argument("--game", help="a game folder: the runtime beside its hookshot.exe")
    p.add_argument("--accept-nvidia-license", action="store_true")
    p.add_argument("--build-only", action="store_true", help="not the runtime: only what the build reads")
    a = p.parse_args(argv)
    if a.build_only and a.game:
        p.error("--build-only fetches no runtime for --game")
    sdk = os.path.abspath(a.sdk or os.path.join(ROOT, "work", "sl-sdk"))
    print(NOTICE, flush=True)
    if not accepted(a.accept_nvidia_license):
        print("sl-sdk: NVIDIA's licenses were not accepted (--accept-nvidia-license, or yes when asked): nothing downloaded",
              file=sys.stderr, flush=True)
        return 2
    try:
        fetch(sdk, runtime=not a.build_only)
    except (OSError, ValueError, zipfile.BadZipFile) as e:
        print("sl-sdk: %s" % e, file=sys.stderr, flush=True)
        return 1
    print("sl-sdk: Streamline's headers%s in %s (NVIDIA's licenses: %s)" % ("" if a.build_only else " and runtime", sdk,
                                                                          os.path.join(sdk, "license.txt")), flush=True)
    if a.game:
        for dst in install_runtime(sdk, beside_exe(a.game)):
            print("sl-sdk: %s" % dst, flush=True)
    print("sl-sdk: build with HOOKSHOT_SL_SDK=%s" % sdk, flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
