"""Self-update the packaged macOS builder from the project's latest GitHub release."""
import hashlib
import hmac
import json
import os
import posixpath
import re
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.request
import zipfile
from urllib.parse import urlsplit

API = "https://api.github.com/repos/NotRexed/Hookshot/releases/latest"
ASSET = "HookshotBuilder-macos-arm64.app.zip"
MAX_DOWNLOAD = 2 * 1024 * 1024 * 1024


def _get(url, limit):
    request = urllib.request.Request(url, headers={
        "Accept": "application/vnd.github+json",
        "User-Agent": "HookshotBuilder-macOS",
        "X-GitHub-Api-Version": "2022-11-28",
    })
    with urllib.request.urlopen(request, timeout=30) as response:
        data = response.read(limit + 1)
    if len(data) > limit:
        raise RuntimeError("The macOS builder download is larger than expected.")
    return data


def _download(url, destination, expected_digest=None, expected_size=None):
    expected_hash = None
    if expected_digest is not None:
        match = re.fullmatch(r"sha256:([0-9a-fA-F]{64})", expected_digest)
        if match is None:
            raise RuntimeError("GitHub returned an unsupported macOS builder checksum.")
        expected_hash = match.group(1).lower()
    if expected_size is not None and (type(expected_size) is not int or expected_size < 0 or
                                      expected_size > MAX_DOWNLOAD):
        raise RuntimeError("GitHub returned an invalid macOS builder size.")

    request = urllib.request.Request(url, headers={"User-Agent": "HookshotBuilder-macOS"})
    total = 0
    digest = hashlib.sha256()
    with urllib.request.urlopen(request, timeout=60) as response, open(destination, "wb") as output:
        while True:
            chunk = response.read(1024 * 1024)
            if not chunk:
                break
            total += len(chunk)
            if total > MAX_DOWNLOAD or expected_size is not None and total > expected_size:
                raise RuntimeError("The macOS builder download is larger than expected.")
            output.write(chunk)
            digest.update(chunk)
    if expected_size is not None and total != expected_size:
        raise RuntimeError("The macOS builder download is incomplete.")
    if expected_hash is not None and not hmac.compare_digest(digest.hexdigest(), expected_hash):
        raise RuntimeError("The macOS builder download failed its SHA-256 check.")


def latest_release():
    release = json.loads(_get(API, 4 * 1024 * 1024).decode("utf-8"))
    if release.get("draft") or release.get("prerelease"):
        raise RuntimeError("GitHub did not return a stable builder release.")
    asset = next((item for item in release.get("assets", []) if item.get("name") == ASSET), None)
    if not release.get("tag_name") or asset is None or not asset.get("browser_download_url"):
        raise RuntimeError("The latest release does not include the macOS builder.")
    asset_digest = asset.get("digest")
    if asset_digest is not None and (not isinstance(asset_digest, str) or
                                     not re.fullmatch(r"sha256:[0-9a-fA-F]{64}", asset_digest)):
        raise RuntimeError("GitHub returned an unsupported macOS builder checksum.")
    url = urlsplit(asset["browser_download_url"])
    if url.scheme != "https" or url.hostname != "github.com":
        raise RuntimeError("GitHub returned an unexpected macOS builder download link.")
    return release["tag_name"], asset["browser_download_url"], asset_digest, asset.get("size")


def _safe_extract(archive, destination):
    with zipfile.ZipFile(archive) as bundle:
        members = bundle.infolist()
        if not members or len(members) > 100000 or sum(item.file_size for item in members) > 3 * MAX_DOWNLOAD:
            raise RuntimeError("The macOS builder archive is empty or malformed.")
        seen = set()
        for member in members:
            name = member.filename.replace("\\", "/")
            parts = name.split("/")
            normalized = name.rstrip("/")
            if (name.startswith("/") or any(part in ("", ".", "..") for part in parts[:-1]) or
                    normalized in seen):
                raise RuntimeError("The macOS builder archive contains an unsafe path.")
            seen.add(normalized)
            if parts[0] != "HookshotBuilder.app" or len(parts) < 2:
                raise RuntimeError("The macOS builder archive has an unexpected layout.")
            mode = member.external_attr >> 16
            if mode and (mode & 0o170000) == 0o120000:
                target = bundle.read(member).decode("utf-8")
                resolved = posixpath.normpath(posixpath.join(posixpath.dirname(normalized), target))
                if target.startswith("/") or resolved != "HookshotBuilder.app" and not resolved.startswith("HookshotBuilder.app/"):
                    raise RuntimeError("The macOS builder archive contains an unsafe symbolic link.")
    subprocess.run(["/usr/bin/ditto", "-x", "-k", archive, destination], check=True)


_INSTALLER = r'''import os, shutil, subprocess, sys, time
app, staged, pid = sys.argv[1], sys.argv[2], int(sys.argv[3])
while True:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        break
    except PermissionError:
        break
    time.sleep(.25)
parent = os.path.dirname(app)
backup = app + ".hookshot-old"
if os.path.exists(backup):
    shutil.rmtree(backup)
os.replace(app, backup)
try:
    os.replace(staged, app)
except Exception:
    os.replace(backup, app)
    raise
shutil.rmtree(backup, ignore_errors=True)
subprocess.Popen(["/usr/bin/open", app], stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                 stderr=subprocess.DEVNULL, start_new_session=True)
shutil.rmtree(os.path.dirname(staged), ignore_errors=True)
'''


def start(app_path, expected_tag, pid):
    """Download and validate a replacement, then let a detached helper swap it in after this UI exits."""
    if not app_path:
        raise RuntimeError("Could not locate HookshotBuilder.app. Reinstall it before updating.")
    app_path = os.path.realpath(app_path.rstrip(os.sep))
    if not app_path.endswith(".app") or not os.path.isdir(app_path):
        raise RuntimeError("Could not locate HookshotBuilder.app. Reinstall it before updating.")
    parent = os.path.dirname(app_path)
    if not os.access(parent, os.W_OK | os.X_OK):
        raise RuntimeError("HookshotBuilder.app is in a protected folder. Move it to Applications in your user folder, then update.")

    tag, url, digest, size = latest_release()
    if expected_tag and tag != expected_tag:
        raise RuntimeError("GitHub offered %s, not %s. Try again in a few minutes." % (tag, expected_tag))
    work = tempfile.mkdtemp(prefix=".hookshot-update-", dir=parent)
    try:
        archive = os.path.join(work, ASSET)
        _download(url, archive, digest, size)
        _safe_extract(archive, work)
        staged = os.path.join(work, "HookshotBuilder.app")
        if not os.path.isfile(os.path.join(staged, "Contents", "Info.plist")):
            raise RuntimeError("The downloaded builder app is incomplete.")
        check = subprocess.run(["/usr/bin/codesign", "--verify", "--deep", "--strict", staged],
                               capture_output=True, text=True)
        if check.returncode:
            raise RuntimeError("The downloaded builder app failed its code-signature check: %s" %
                               (check.stderr.strip() or check.stdout.strip()))
        subprocess.Popen([os.path.realpath(sys.executable), "-c", _INSTALLER, app_path, staged, str(pid)],
                         stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                         start_new_session=True)
    except Exception:
        shutil.rmtree(work, ignore_errors=True)
        raise
