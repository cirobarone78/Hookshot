// Linux builder update lists and version comparison.
// Pure port of builder/linux/linux_update.py's parse_list, release_key,
// track_of, newest_release, update_target and choose_mode. Network takes an
// injected getter so tests run offline.
import 'dart:io';

import '../config.dart' as cfg;

const tracks = ['release', 'rc', 'nightly'];
const listName = 'hookshot-linux.txt';
String get latestList => 'https://github.com/${cfg.repository()}/releases/latest/download/$listName';
String get latestApi => 'https://api.github.com/repos/${cfg.repository()}/releases/latest';
String get releasesApi => 'https://api.github.com/repos/${cfg.repository()}/releases?per_page=100';
const sysrootPart = 'usr/lib/hookshot/sysroot';

class Part {
  final String sha;
  final int size;
  final String dest;
  final String url;
  final List<String>? files; // null: whole tree
  const Part(this.sha, this.size, this.dest, this.url, this.files);

  bool sameAs(Part? other) =>
      other != null && other.sha == sha && other.dest == dest && _listsEqual(other.files, files);
}

bool _listsEqual(List<String>? a, List<String>? b) {
  if (a == null || b == null) return a == null && b == null;
  if (a.length != b.length) return false;
  for (var i = 0; i < a.length; i++) {
    if (a[i] != b[i]) return false;
  }
  return true;
}

class Manifest {
  final String tag;
  final List<Part> parts;
  const Manifest(this.tag, this.parts);

  Part? bySha(String sha) {
    for (final p in parts) {
      if (p.sha == sha) return p;
    }
    return null;
  }
}

bool _safeName(String name) {
  if (name.isEmpty || name.startsWith('/') || name.split('/').contains('..')) {
    throw FormatException('the zip has a path outside its folder: $name');
  }
  return true;
}

/// Parse a hookshot-linux.txt list. [local]: file:// links allowed (else https only).
Manifest parseList(String text, {bool local = true}) {
  var tag = '';
  final parts = <Part>[];
  Part? cur;
  List<String>? files;
  for (final raw in text.split('\n')) {
    final line = raw.trim();
    if (line.isEmpty || line.startsWith('#')) continue;
    if (line.startsWith('tag ')) {
      tag = line.substring(4).trim();
    } else if (line.startsWith('part ')) {
      final bits = line.split(' ');
      if (bits.length != 5) throw const FormatException('a part line needs sha, size, directory and url');
      if (!RegExp(r'^[0-9a-f]{64}$').hasMatch(bits[1])) {
        throw FormatException('a part line has a bad checksum: ${bits[1]}');
      }
      final url = bits[4];
      final ok = local ? (url.startsWith('https://') || url.startsWith('file://')) : url.startsWith('https://');
      if (!ok) throw FormatException('a part line has a bad link: $url');
      if (bits[3] != '.') _safeName(bits[3]);
      cur = Part(bits[1], int.parse(bits[2]), bits[3], url, <String>[]);
      parts.add(cur);
      files = cur.files as List<String>;
    } else if (line == 'tree') {
      if (cur == null) throw const FormatException('tree with no part');
      parts[parts.length - 1] = Part(cur.sha, cur.size, cur.dest, cur.url, null);
      cur = parts[parts.length - 1];
      files = null;
    } else if (line.startsWith('file ')) {
      if (cur == null || files == null) throw const FormatException('file with no part');
      final name = line.substring(5).trim();
      _safeName(name);
      files.add(name);
    } else {
      throw FormatException('unknown list line: $line');
    }
  }
  if (tag.isEmpty || parts.isEmpty) throw const FormatException('the setup list has no release');
  if (!RegExp(r'^[0-9A-Za-z._+-]{1,128}$').hasMatch(tag) || tag == '.' || tag == '..') {
    throw FormatException('the setup list\'s tag is not a version name: $tag');
  }
  return Manifest(tag, parts);
}

/// A version to compare, or null when the tag names no release. Port of release_key().
/// Returns (numbers, isRelease, pre, hasSuffix) encoded as a comparable record.
({List<int> numbers, bool isRelease, List<(int, int, String)> pre, bool suffix})? releaseKey(String? tag) {
  final v = (tag ?? '').trim();
  final m = RegExp(
          r'^(?=v|\d+\.)v?(\d+(?:\.\d+)*)(?:-(?!\d+-g|dirty$)([0-9A-Za-z]+(?:\.[0-9A-Za-z]+)*))?(-\d+-g[0-9a-f]+)?(-dirty)?$')
      .firstMatch(v);
  if (m == null) return null;
  final numbers = m.group(1)!.split('.').map(int.parse).toList();
  final preRaw = m.group(2);
  final pre = <(int, int, String)>[];
  if (preRaw != null) {
    for (final p in preRaw.split('.')) {
      if (p.isEmpty) continue;
      final n = int.tryParse(p);
      pre.add(n != null ? (0, n, '') : (1, 0, p));
    }
  }
  return (
    numbers: numbers,
    isRelease: preRaw == null,
    pre: pre,
    suffix: (m.group(3) ?? m.group(4)) != null,
  );
}

int _compareReleaseKey(({List<int> numbers, bool isRelease, List<(int, int, String)> pre, bool suffix}) a,
    ({List<int> numbers, bool isRelease, List<(int, int, String)> pre, bool suffix}) b) {
  for (var i = 0; i < a.numbers.length && i < b.numbers.length; i++) {
    if (a.numbers[i] != b.numbers[i]) return a.numbers[i].compareTo(b.numbers[i]);
  }
  if (a.numbers.length != b.numbers.length) return a.numbers.length.compareTo(b.numbers.length);
  if (a.isRelease != b.isRelease) return a.isRelease ? 1 : -1;
  for (var i = 0; i < a.pre.length && i < b.pre.length; i++) {
    final x = a.pre[i], y = b.pre[i];
    if (x.$1 != y.$1) return x.$1.compareTo(y.$1);
    if (x.$2 != y.$2) return x.$2.compareTo(y.$2);
    if (x.$3 != y.$3) return x.$3.compareTo(y.$3);
  }
  if (a.pre.length != b.pre.length) return a.pre.length.compareTo(b.pre.length);
  if (a.suffix != b.suffix) return a.suffix ? 1 : -1;
  return 0;
}

/// nightly for git-describe builds, rc for release candidates, else release.
String trackOf(String? version) {
  final v = (version ?? '').trim();
  if (RegExp(r'-\d+-g[0-9a-f]+(-dirty)?$').hasMatch(v)) return 'nightly';
  final key = releaseKey(v);
  return (key != null && !key.isRelease) ? 'rc' : 'release';
}

String releaseOf(String tag) => trackOf(tag) == 'nightly' ? 'nightly' : tag;

String listUrl([String? tag, String? repository]) {
  final repo = repository ?? cfg.repository();
  if (tag == null || tag.isEmpty) return 'https://github.com/$repo/releases/latest/download/$listName';
  return 'https://github.com/$repo/releases/download/${releaseOf(tag)}/$listName';
}

/// Newest of release/rc tags in semver order, else null.
String? newestRelease(Iterable<String?> tags) {
  String? best;
  for (final t in tags) {
    if (t == null || !RegExp(r'^v\d+\.\d+\.\d+(-rc\.\d+)?$').hasMatch(t)) continue;
    if (best == null || _compareReleaseKey(releaseKey(t)!, releaseKey(best)!) > 0) best = t;
  }
  return best;
}

/// The newest version this builder knows of. Port of update_target().
String? updateTarget(String? latest, String? tools, {bool switchTrack = false}) {
  if (latest == null || latest.isEmpty || tools == null || tools.isEmpty) {
    return (latest?.isNotEmpty ?? false) ? latest : tools;
  }
  if (switchTrack || trackOf(latest) == 'nightly') return latest;
  final have = releaseKey(tools);
  final out = releaseKey(latest);
  if (have == null || out == null) return tools;
  return _compareReleaseKey(out, have) > 0 ? latest : tools;
}

/// What the builder's button does. Port of choose_mode().
String chooseMode(String? game, String? tools, String? latest, bool sourcePicked, bool kept,
    {bool switchTrack = false}) {
  final target = updateTarget(latest, tools, switchTrack: switchTrack);
  if (kept && game != null && target != null && game != target && !sourcePicked) return 'update-game';
  if (game != null && !sourcePicked) return 'up-to-date';
  // (a source checkout names no version: no update offered, as in the Tk builder —
  // begin_update could not install into it anyway)
  if (latest != null && latest.isNotEmpty && tools != null && tools.isNotEmpty && target != tools) {
    return 'update-builder';
  }
  return 'build';
}

/// The release these tools are, from a packaged VERSION/version.txt. Else "".
String toolsTag(String root) {
  for (final rel in ['usr/share/hookshot/VERSION', 'usr/share/hookshot/version.txt', 'VERSION', 'version.txt']) {
    try {
      final line = File('$root/$rel').readAsStringSync().split('\n').first.trim();
      if (line.isNotEmpty) return line;
    } catch (_) {}
  }
  return '';
}

/// The AppDir running now (AppImage mount or installed version), else null.
String? runningRoot() {
  final appdir = Platform.environment['APPDIR'];
  if (appdir != null && File('$appdir/AppRun').existsSync()) return appdir;
  final tools = Platform.environment['HOOKSHOT_TOOLS'];
  if (tools != null) {
    // <root>/usr/share/hookshot -> walk up three to <root>.
    final root = Directory(tools).parent.parent.parent.path;
    if (File('$root/AppRun').existsSync()) return root;
  }
  return null;
}

/// The release a folder was built with, when it still has the game files.
({String? version, bool kept}) gameVersion(String? folder) {
  if (folder == null || folder.isEmpty) return (version: null, kept: false);
  final kept = Directory('$folder/.hookshot_exefs').existsSync() && Directory('$folder/romfs').existsSync();
  String? version;
  try {
    for (final line in File('$folder/hookshot_version.txt').readAsLinesSync()) {
      if (line.startsWith('version=')) {
        version = line.substring('version='.length).trim();
        if (version.isEmpty) version = null;
        break;
      }
    }
  } catch (_) {}
  return (version: version, kept: kept);
}

/// bin/hookshot under the launcher, or hookshot in a pre-launcher folder.
String? gameExe(String? folder) {
  if (folder == null || folder.isEmpty) return null;
  final nested = '$folder/bin/hookshot';
  if (File(nested).existsSync() && File('$folder/image.bin').existsSync()) return nested;
  final flat = '$folder/hookshot';
  if (File(flat).existsSync() && File('$folder/image.bin').existsSync()) return flat;
  return null;
}

bool gameReady(String? folder) => gameExe(folder) != null;
