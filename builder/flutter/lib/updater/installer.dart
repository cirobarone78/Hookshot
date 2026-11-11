// Downloading, verifying and installing Linux builder update parts.
// Port of builder/linux/linux_update.py's fetch_bytes, latest_tag,
// fetch_manifest, startup_manifest, _place, _unpack, _finish_tree and install.
// Symlink and sysroot-link handling mirrors part_links.py.
import 'dart:convert';
import 'dart:io';

import 'package:archive/archive.dart';
import 'package:crypto/crypto.dart';
import 'package:path/path.dart' as p;

import '../config.dart' as cfg;
import 'manifest.dart';

/// Cooperative cancellation for update downloads. Port of the threading.Event
/// linux_update.fetch_bytes/install take as `stop`.
class StopFlag {
  bool _set = false;
  final _listeners = <void Function()>[];
  void set() {
    if (_set) return;
    _set = true;
    for (final listener in List<void Function()>.from(_listeners)) {
      listener();
    }
    _listeners.clear();
  }

  bool get isSet => _set;

  void addListener(void Function() listener) {
    if (_set) {
      listener();
    } else {
      _listeners.add(listener);
    }
  }

  void removeListener(void Function() listener) => _listeners.remove(listener);

  /// Sleep [d], waking early when set. Throws [Cancelled] when set.
  Future<void> wait(Duration d) async {
    final end = DateTime.now().add(d);
    while (DateTime.now().isBefore(end)) {
      if (_set) throw const Cancelled();
      await Future<void>.delayed(const Duration(milliseconds: 100));
    }
    if (_set) throw const Cancelled();
  }
}

/// The player stopped the update. Not retried; staged parts are removed.
class Cancelled implements Exception {
  final String message;
  const Cancelled([this.message = 'The update was cancelled.']);
  @override
  String toString() => message;
}

void _stopped(StopFlag? stop) {
  if (stop != null && stop.isSet) throw const Cancelled();
}

String dataRoot() {
  return cfg.builderHome();
}

String _https(String url) {
  if (!url.startsWith('https://')) throw ArgumentError('not an https link: $url');
  return url;
}

/// GET bytes. Follows redirects only to other https links, retries 5xx/429.
Future<List<int>> fetchBytes(String url, {int timeoutSeconds = 60, StopFlag? stop}) async {
  var delay = 2;
  Object? last;
  final client = HttpClient();
  try {
    for (var attempt = 0; attempt < 4; attempt++) {
      try {
        _stopped(stop);
        return await _get(client, _https(url), timeoutSeconds, stop);
      } on Cancelled {
        rethrow;
      } on HttpException catch (e) {
        last = e;
        if (!e.message.startsWith('5') && !e.message.startsWith('429')) break;
      } catch (e) {
        if (stop?.isSet == true) throw const Cancelled();
        last = e;
      }
      if (attempt < 3) {
        if (stop == null) {
          await Future<void>.delayed(Duration(seconds: delay));
        } else {
          await stop.wait(Duration(seconds: delay));
        }
        delay = (delay * 2).clamp(2, 20);
      }
    }
    final got = await _apiDownload(client, url, stop).catchError((Object e) {
      if (e is Cancelled) throw e;
      return null;
    });
    if (got != null) return got;
  } finally {
    client.close();
  }
  throw StateError(last?.toString() ?? 'the download failed');
}

Future<List<int>> _get(HttpClient client, String url, int timeoutSeconds, [StopFlag? stop]) async {
  var current = url;
  for (var hops = 0; hops < 10; hops++) {
    _stopped(stop);
    final request = await client.getUrl(Uri.parse(current));
    void abort() => request.abort(const Cancelled());
    stop?.addListener(abort);
    try {
      _stopped(stop);
      request.headers.set('User-Agent', 'Hookshot');
      request.headers.set('Accept', 'application/vnd.github+json');
      final response = await request.close().timeout(Duration(seconds: timeoutSeconds));
      if (response.statusCode >= 300 && response.statusCode < 400) {
        final next = response.headers.value('location');
        await response.drain<void>();
        if (next == null) throw HttpException('${response.statusCode}');
        current = _https(Uri.parse(current).resolve(next).toString());
        continue;
      }
      if (response.statusCode >= 500 || response.statusCode == 429) {
        await response.drain<void>();
        throw HttpException('${response.statusCode}');
      }
      if (response.statusCode != 200) {
        await response.drain<void>();
        throw HttpException('${response.statusCode}');
      }
      // A chunk at a time, stop looked at before each: one read of a part is many of them.
      final bytes = <int>[];
      await for (final chunk in response.timeout(Duration(seconds: timeoutSeconds))) {
        _stopped(stop);
        bytes.addAll(chunk);
        if (bytes.length > (4 << 30)) throw const HttpException('the download is larger than expected');
      }
      return bytes;
    } finally {
      stop?.removeListener(abort);
    }
  }
  throw const HttpException('too many redirects');
}

/// A failed GitHub release link retried through the API (deps.sh does this for 504s).
Future<List<int>?> _apiDownload(HttpClient client, String url, StopFlag? stop) async {
  const prefix = 'https://github.com/';
  const mark = '/releases/download/';
  if (!url.startsWith(prefix) || !url.contains(mark)) return null;
  final rest = url.substring(prefix.length);
  final i = rest.indexOf(mark);
  final repo = rest.substring(0, i);
  final tail = rest.substring(i + mark.length);
  final j = tail.indexOf('/');
  if (j < 0) return null;
  final tag = tail.substring(0, j);
  final name = tail.substring(j + 1);
  if (repo.isEmpty || tag.isEmpty || name.isEmpty || name.contains('/')) return null;
  try {
    final info = await _get(client, 'https://api.github.com/repos/$repo/releases/tags/$tag', 30, stop);
    final body = json.decode(utf8.decode(info)) as Map<String, dynamic>;
    for (final asset in (body['assets'] as List)) {
      if (asset['name'] == name) {
        final request = await client.getUrl(Uri.parse(asset['url'] as String));
        void abort() => request.abort(const Cancelled());
        stop?.addListener(abort);
        try {
          _stopped(stop);
          request.headers.set('User-Agent', 'Hookshot');
          request.headers.set('Accept', 'application/octet-stream');
          final response = await request.close().timeout(const Duration(seconds: 120));
          if (response.statusCode != 200) {
            await response.drain<void>();
            return null;
          }
          final bytes = <int>[];
          await for (final chunk in response.timeout(const Duration(seconds: 120))) {
            _stopped(stop);
            bytes.addAll(chunk);
            if (bytes.length > (4 << 30)) throw const HttpException('the download is larger than expected');
          }
          return bytes;
        } finally {
          stop?.removeListener(abort);
        }
      }
    }
  } on Cancelled {
    rethrow;
  } catch (_) {
    return null;
  }
  return null;
}

/// The newest build of [track], or null when GitHub did not answer.
Future<String?> latestTag(Future<List<int>> Function(String url) get, {String track = 'release'}) async {
  if (track == 'nightly') {
    try {
      final text = utf8.decode(await get(listUrl('nightly')));
      return parseList(text, local: false).tag;
    } catch (_) {
      return null;
    }
  }
  if (track == 'rc') {
    try {
      final body = json.decode(utf8.decode(await get(releasesApi))) as List;
      final tags = [
        for (final r in body)
          if ((r['draft'] as bool?) != true) r['tag_name'] as String?
      ];
      final newest = newestRelease(tags);
      if (newest != null) return newest;
    } catch (_) {}
  }
  try {
    final body = json.decode(utf8.decode(await get(latestApi))) as Map<String, dynamic>;
    final tag = body['tag_name'] as String?;
    if (tag != null && tag.isNotEmpty) return tag;
  } catch (_) {}
  try {
    final text = utf8.decode(await get(latestList));
    return parseList(text, local: false).tag;
  } catch (_) {
    return null;
  }
}

/// Stable release tags which carry a Builder setup list for this platform.
/// GitHub returns releases newest first, which is the order the picker uses.
Future<List<String>> releaseTags(Future<List<int>> Function(String url) get) async {
  final body = json.decode(utf8.decode(await get(releasesApi))) as List;
  final wanted = Platform.isWindows ? 'hookshot-setup.txt' : 'hookshot-linux.txt';
  final tags = <String>[];
  for (final raw in body) {
    final release = raw as Map<String, dynamic>;
    if (release['draft'] == true || release['prerelease'] == true) continue;
    final tag = release['tag_name'] as String?;
    if (tag == null || !RegExp(r'^v\d+\.\d+\.\d+$').hasMatch(tag)) continue;
    final assets = (release['assets'] as List? ?? const [])
        .whereType<Map<String, dynamic>>()
        .map((asset) => asset['name'])
        .whereType<String>()
        .toSet();
    if (assets.contains(wanted)) tags.add(tag);
  }
  return tags;
}

Manifest fetchManifestSync(String Function(String url) readFile, {String? tag}) {
  final override = Platform.environment['HOOKSHOT_LINUX_LIST'];
  if (override != null && override.isNotEmpty) return parseList(readFile(override));
  throw StateError('network fetch required');
}

Future<Manifest> fetchManifest(Future<List<int>> Function(String url) get, {String? tag, StopFlag? stop}) async {
  final override = Platform.environment['HOOKSHOT_LINUX_LIST'];
  if (override != null && override.isNotEmpty) {
    return parseList(await File(override).readAsString());
  }
  final bytes = await get(listUrl(tag));
  return parseList(utf8.decode(bytes), local: false);
}

Manifest? readManifest(String? root) {
  if (root == null) return null;
  try {
    return parseList(File('$root/$listName').readAsStringSync());
  } catch (_) {
    return null;
  }
}

/// The list begin_update installs: the latest release, except when these tools
/// ship a list of their own that is that same release and no older than it.
Future<Manifest> startupManifest(String? root, Future<List<int>> Function(String url) get,
    {String? tag, StopFlag? stop}) async {
  final latest = await fetchManifest(get, tag: tag, stop: stop);
  if (tag == null && Platform.environment['HOOKSHOT_LINUX_LIST'] == null) {
    final own = readManifest(root);
    if (own != null && own.tag == toolsTag(root ?? '') && updateTarget(latest.tag, own.tag) == own.tag) {
      return own;
    }
  }
  return latest;
}

// ---- placing parts ----

void _safeName(String name) {
  if (name.isEmpty || name.startsWith('/') || name.split('/').contains('..')) {
    throw ArgumentError('the zip has a path outside its folder: $name');
  }
}

void _checkPartDirectory(String path, String root) {
  // (abspath normalizes: Dart's .absolute keeps /./ segments, so normalize first)
  final abs = p.normalize(Directory(path).absolute.path);
  final real = Directory(abs).resolveSymbolicLinksSync();
  if (real != abs) throw ArgumentError('the update would write through a symbolic link: $path');
}

bool _isAbsoluteLink(String target) => target.startsWith('/');

/// Rebase a sysroot-absolute link onto an existing target in the same sysroot.
String relativeSysrootLink(String root, String link, String target) {
  if (!target.startsWith('/') || target.startsWith('//')) {
    throw ArgumentError('not a rooted Linux sysroot link: $link -> $target');
  }
  final absRoot = Directory(root).absolute.path;
  final destination = File('$absRoot/${target.substring(1)}').absolute.path;
  if (!_commonPrefixIs(destination, absRoot)) throw ArgumentError('a sysroot link leaves its root: $link -> $target');
  final realRoot = Directory(absRoot).resolveSymbolicLinksSync();
  final realDestination = _resolve(destination);
  if (!_commonPrefixIs(realDestination, realRoot)) {
    throw ArgumentError('a sysroot link resolves outside its root: $link -> $target');
  }
  if (!File(destination).existsSync() && !Directory(destination).existsSync() && !Link(destination).existsSync()) {
    throw StateError('a sysroot link target is missing: $link -> $target');
  }
  return _relative(destination, Directory(link).parent.path);
}

String _resolve(String path) {
  try {
    return File(path).resolveSymbolicLinksSync();
  } catch (_) {
    return Directory(path).absolute.path;
  }
}

bool _commonPrefixIs(String path, String prefix) {
  // (lexically normalized first: Python's abspath resolves . and .., and a
  // naive prefix check lets "root/./../outside" through)
  final a = p.split(p.normalize(path));
  final b = p.split(p.normalize(prefix));
  if (a.length < b.length) return false;
  for (var i = 0; i < b.length; i++) {
    if (a[i] != b[i]) return false;
  }
  return true;
}

String _relative(String target, String from) {
  final t = target.split('/').where((s) => s.isNotEmpty).toList();
  final f = from.split('/').where((s) => s.isNotEmpty).toList();
  var i = 0;
  while (i < t.length && i < f.length && t[i] == f[i]) {
    i++;
  }
  return [...List.filled(f.length - i, '..'), ...t.sublist(i)].join('/');
}

void _symlinkChecked(String root, String linkTo, String target) {
  final parts = linkTo.split('/');
  var ups = 0;
  while (ups < parts.length && parts[ups] == '..') {
    ups++;
  }
  if (parts.sublist(ups).contains('..')) {
    throw ArgumentError('an update symlink climbs after a name: $target -> $linkTo');
  }
  final absRoot = Directory(root).absolute.path;
  final destination = File('${Directory(target).parent.path}/$linkTo').absolute.path;
  if (_isAbsoluteLink(linkTo) ||
      !_commonPrefixIs(destination, absRoot) ||
      !_commonPrefixIs(_resolve(destination), Directory(absRoot).resolveSymbolicLinksSync())) {
    throw ArgumentError('an update symlink leaves its staging folder: $target -> $linkTo');
  }
  Link(target).createSync(linkTo);
}

void _clone(String src, String dst, String root, List<(String, String)>? rootedLinks) {
  final type = FileSystemEntity.typeSync(src, followLinks: false);
  if (type == FileSystemEntityType.link) {
    final linkTo = Link(src).targetSync();
    if (rootedLinks != null && _isAbsoluteLink(linkTo)) {
      rootedLinks.add((dst, linkTo));
    } else {
      _symlinkChecked(root, linkTo, dst);
    }
    return;
  }
  try {
    Link(dst).createSync(src);
    return;
  } catch (_) {
    File(src).copySync(dst);
  }
}

void _cloneTree(String src, String dst, String root, {bool rebaseSysroot = false}) {
  final rootedLinks = rebaseSysroot ? <(String, String)>[] : null;
  for (final entity in Directory(src).listSync(recursive: true, followLinks: false)) {
    final rel = _relative(entity.path, src);
    final out = '$dst/$rel';
    if (entity is Directory) {
      if (FileSystemEntity.isLinkSync(entity.path)) {
        _clone(entity.path, out, root, rootedLinks);
      } else {
        Directory(out).createSync(recursive: true);
      }
    } else if (entity is File) {
      Directory(File(out).parent.path).createSync(recursive: true);
      _clone(entity.path, out, root, rootedLinks);
    }
  }
  if (rootedLinks != null) _finishSysrootLinks(dst, rootedLinks);
}

void _finishSysrootLinks(String dest, List<(String, String)> rootedLinks) {
  var pending = rootedLinks;
  while (pending.isNotEmpty) {
    final next = <(String, String)>[];
    for (final (target, linkTo) in pending) {
      try {
        final relative = relativeSysrootLink(dest, target, linkTo);
        _checkPartDirectory(Directory(target).parent.path, dest);
        Link(target).createSync(relative);
      } on StateError {
        next.add((target, linkTo));
      }
    }
    if (next.length == pending.length) {
      throw ArgumentError('sysroot links have missing or circular targets: '
          '${pending.map((e) => '${e.$1} -> ${e.$2}').join(', ')}');
    }
    pending = next;
  }
}

void _unpack(List<int> data, String dest, List<String>? files, bool rebaseSysroot, String root) {
  Directory(dest).createSync(recursive: true);
  final rootedLinks = <(String, String)>[];
  final archive = ZipDecoder().decodeBytes(data);
  for (final file in archive.files) {
    final name = file.name;
    _safeName(name);
    if (name.isEmpty || name.endsWith('/')) continue;
    if (files != null && !files.contains(name)) {
      throw ArgumentError('the zip has ${file.name}, which this part does not list');
    }
    final target = '$dest/$name';
    final parent = Directory(target).parent.path;
    Directory(parent).createSync(recursive: true);
    _checkPartDirectory(parent, dest);
    // (archive's mode is already the unix mode, not externalAttributes: no shift)
    final mode = file.mode;
    if (file.isSymbolicLink || (mode & 0xF000) == 0xA000) {
      final linkTo = utf8.decode(file.content as List<int>);
      if (_isAbsoluteLink(linkTo)) {
        if (!rebaseSysroot) throw ArgumentError('a zip symlink has an absolute target: $name -> $linkTo');
        rootedLinks.add((target, linkTo));
      } else {
        _symlinkChecked(root, linkTo, target);
      }
    } else {
      File(target).writeAsBytesSync(file.content as List<int>, flush: true);
      final perms = mode & 0x1FF;
      if (perms != 0) {
        Process.runSync('chmod', [perms.toRadixString(8), target]);
      } else if ((mode & 0x111) != 0) {
        Process.runSync('chmod', ['755', target]);
      }
    }
  }
  if (rootedLinks.isNotEmpty) {
    if (!rebaseSysroot) throw ArgumentError('absolute links outside the sysroot part');
    _finishSysrootLinks(dest, rootedLinks);
  }
}

void _checkLinksInside(String dest) {
  final real = Directory(dest).resolveSymbolicLinksSync();
  for (final entity in Directory(dest).listSync(recursive: true, followLinks: false)) {
    if (FileSystemEntity.isLinkSync(entity.path) &&
        !_commonPrefixIs(Directory(entity.path).resolveSymbolicLinksSync(), real)) {
      throw ArgumentError('an update symlink leaves its staging folder: ${entity.path}');
    }
  }
}

Future<void> _place(Part part, String? sourceRoot, Manifest? source, String destRoot,
    Future<List<int>> Function(String url) get, void Function(String) note) async {
  final parent = Directory(destRoot).parent.path;
  final staging = Directory(destRoot).uri.pathSegments.where((s) => s.isNotEmpty).last;
  final stagingRoot = '${Directory(parent).resolveSymbolicLinksSync()}/$staging';
  final dest = '$stagingRoot/${_safeName2(part.dest)}';
  Directory(dest).parent.createSync(recursive: true);
  _checkPartDirectory(Directory(dest).parent.path, destRoot);
  final old = source?.bySha(part.sha);
  final src = (old != null && old.sameAs(part) && sourceRoot != null) ? '$sourceRoot/${part.dest}' : '';
  final ready = src.isNotEmpty &&
      Directory(src).existsSync() &&
      (part.files == null ||
          part.files!.every((name) => File('$src/$name').existsSync() || Link('$src/$name').existsSync()));
  final rebaseSysroot = part.dest == sysrootPart;
  if (ready) {
    note('Keeping ${part.dest} (unchanged)');
    if (part.files == null) {
      _cloneTree(src, dest, stagingRoot, rebaseSysroot: rebaseSysroot);
    } else {
      Directory(dest).createSync(recursive: true);
      final rootedLinks = rebaseSysroot ? <(String, String)>[] : null;
      for (final name in part.files!) {
        _clone('$src/$name', '$dest/$name', stagingRoot, rootedLinks);
      }
      if (rootedLinks != null) _finishSysrootLinks(dest, rootedLinks);
    }
    return;
  }
  note('Downloading ${part.dest} (${part.size >> 20} MB)');
  final data = await get(part.url);
  if (data.length != part.size || sha256.convert(data).toString() != part.sha) {
    throw StateError('${part.dest} did not download correctly (its checksum differs)');
  }
  _unpack(data, dest, part.files, rebaseSysroot, stagingRoot);
}

String _safeName2(String name) {
  _safeName(name);
  return name;
}

String _finishTree(String dest) {
  _checkLinksInside(dest);
  for (final name in ['AppRun', 'hookshot.png', 'hookshot-builder.desktop']) {
    if (FileSystemEntity.isLinkSync('$dest/$name')) {
      throw ArgumentError('the update has a link where $name goes');
    }
  }
  final tools = '$dest/usr/share/hookshot';
  final apprun = '$dest/AppRun';
  File('$tools/builder/linux/AppRun').copySync(apprun);
  Process.runSync('chmod', ['755', apprun]);
  final icon = '$tools/assets/hookshot.png';
  if (File(icon).existsSync()) File(icon).copySync('$dest/hookshot.png');
  final desktop = '$tools/builder/linux/hookshot-builder.desktop';
  if (File(desktop).existsSync()) File(desktop).copySync('$dest/hookshot-builder.desktop');
  return apprun;
}

/// versions/`tag` from the list. Unchanged parts come from [sourceRoot].
/// [rootOverride] replaces dataRoot() in tests.
Future<String> install(Manifest manifest, String? sourceRoot, Manifest? source,
    {Future<List<int>> Function(String url)? get,
    void Function(String)? note,
    String? rootOverride,
    StopFlag? stop}) async {
  final getFn = get ?? ((String url) => fetchBytes(url, stop: stop));
  final noteFn = note ?? (_) {};
  final root = rootOverride ?? dataRoot();
  final versions = '$root/versions';
  final dest = '$versions/${manifest.tag}';
  final partial = '$dest.part';
  if (FileSystemEntity.isLinkSync(partial)) {
    throw ArgumentError('the update staging folder is a symbolic link: $partial');
  }
  if (Directory(partial).existsSync()) Directory(partial).deleteSync(recursive: true);
  Directory(versions).createSync(recursive: true);
  try {
    for (final part in manifest.parts) {
      _stopped(stop);
      await _place(part, sourceRoot, source, partial, getFn, noteFn);
    }
    final list = StringBuffer('tag ${manifest.tag}\n');
    for (final part in manifest.parts) {
      list.write('part ${part.sha} ${part.size} ${part.dest} ${part.url}\n');
      if (part.files == null) {
        list.write('tree\n');
      } else {
        for (final name in part.files!) {
          list.write('file $name\n');
        }
      }
    }
    File('$partial/$listName').writeAsStringSync(list.toString(), flush: true);
    _finishTree(partial);
    _stopped(stop); // the last moment: from here the new version takes the old one's place
  } catch (_) {
    if (Directory(partial).existsSync()) Directory(partial).deleteSync(recursive: true);
    rethrow;
  }
  if (Directory(dest).existsSync()) Directory(dest).deleteSync(recursive: true);
  Directory(partial).renameSync(dest);
  final current = '$root/current';
  File('$current.new').writeAsStringSync('${manifest.tag}\n', flush: true);
  File('$current.new').renameSync(current);
  for (final name in Directory(versions).listSync()) {
    if (name.path != dest) {
      try {
        Directory(name.path).deleteSync(recursive: true);
      } catch (_) {}
    }
  }
  final apprun = '$dest/AppRun';
  return apprun;
}

String installedApprun() {
  final root = dataRoot();
  try {
    final tag = File('$root/current').readAsStringSync().trim();
    final path = '$root/versions/$tag/AppRun';
    if (tag.isNotEmpty && File(path).existsSync()) return path;
  } catch (_) {}
  return '';
}
