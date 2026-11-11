// Per-installation version pinning and local save/settings backups.
import 'dart:io';

import 'package:path/path.dart' as p;

import '../config.dart' as cfg;

const _policyFile = 'hookshot_update_policy.txt';
final _safeTag = RegExp(r'^[A-Za-z0-9][A-Za-z0-9._+-]{0,127}$');

String _policyPath(String folder) => p.join(folder, 'user', _policyFile);

String? pinnedVersion(String folder) {
  try {
    final values = <String, String>{};
    for (final line in File(_policyPath(folder)).readAsLinesSync()) {
      final split = line.indexOf('=');
      if (split > 0) values[line.substring(0, split).trim()] = line.substring(split + 1).trim();
    }
    final tag = values['version'];
    return values['mode'] == 'pinned' && tag != null && _safeTag.hasMatch(tag) ? tag : null;
  } catch (_) {
    return null;
  }
}

void setPinnedVersion(String folder, String? tag) {
  final path = _policyPath(folder);
  final file = File(path);
  if (tag == null) {
    if (file.existsSync()) file.deleteSync();
    return;
  }
  if (!_safeTag.hasMatch(tag)) throw const FormatException('Invalid version tag.');
  file.parent.createSync(recursive: true);
  final temp = File('$path.tmp');
  temp.writeAsStringSync('mode=pinned\nversion=$tag\n', flush: true);
  if (file.existsSync()) file.deleteSync();
  temp.renameSync(path);
}

/// Back up saves and settings before a version switch. Returns null when there
/// is nothing to preserve. Symlinks are rejected rather than followed outside
/// the game folder; a failed backup prevents the switch.
String? backupBeforeSwitch(String folder, {String? backupRoot}) {
  final sources = <(String, String)>[];
  final localUser = p.join(folder, 'user');
  final localSave = p.join(localUser, 'save');
  if (Directory(localSave).existsSync()) sources.add((localSave, 'game/user/save'));
  final profiles = p.join(localUser, 'profiles.txt');
  if (File(profiles).existsSync()) sources.add((profiles, 'game/user/profiles.txt'));
  final policy = p.join(localUser, _policyFile);
  if (File(policy).existsSync()) sources.add((policy, 'game/user/$_policyFile'));

  final xdg = Platform.environment['XDG_DATA_HOME'];
  final home = Platform.environment['HOME'] ?? Platform.environment['USERPROFILE'];
  final sharedUser = xdg != null && xdg.isNotEmpty
      ? p.join(xdg, 'hookshot')
      : (home == null ? '' : p.join(home, '.local', 'share', 'hookshot'));
  final sharedSave = sharedUser.isEmpty ? '' : p.join(sharedUser, 'save');
  if (sharedSave.isNotEmpty &&
      Directory(sharedSave).existsSync() &&
      p.normalize(sharedSave) != p.normalize(localSave)) {
    sources.add((sharedSave, 'shared-user/save'));
    final sharedProfiles = p.join(sharedUser, 'profiles.txt');
    if (File(sharedProfiles).existsSync()) sources.add((sharedProfiles, 'shared-user/profiles.txt'));
  }

  for (final name in ['hookshot_options.ini', 'hookshot_env.txt']) {
    final source = p.join(folder, name);
    if (File(source).existsSync()) sources.add((source, 'game/$name'));
  }
  if (sources.isEmpty) return null;

  final root = backupRoot ?? cfg.builderHome();
  final backups = Directory(p.join(root, 'version-backups'))..createSync(recursive: true);
  final stamp = DateTime.now().toUtc().toIso8601String().replaceAll(RegExp(r'[^0-9A-Za-z]'), '-');
  var destination = p.join(backups.path, '${p.basename(folder)}-$stamp');
  var suffix = 2;
  while (FileSystemEntity.typeSync(destination, followLinks: false) != FileSystemEntityType.notFound) {
    destination = p.join(backups.path, '${p.basename(folder)}-$stamp-$suffix');
    suffix++;
  }
  Directory(destination).createSync();
  for (final (source, relative) in sources) {
    final type = FileSystemEntity.typeSync(source, followLinks: false);
    if (type == FileSystemEntityType.link) {
      throw FileSystemException('Cannot back up a linked save/settings path safely.', source);
    }
    final target = p.join(destination, relative);
    if (type == FileSystemEntityType.file) {
      Directory(p.dirname(target)).createSync(recursive: true);
      File(source).copySync(target);
    } else if (type == FileSystemEntityType.directory) {
      _copyTree(source, target);
    }
  }
  return destination;
}

void _copyTree(String source, String target) {
  Directory(target).createSync(recursive: true);
  for (final entry in Directory(source).listSync(followLinks: false)) {
    final type = FileSystemEntity.typeSync(entry.path, followLinks: false);
    if (type == FileSystemEntityType.link) {
      throw FileSystemException('Cannot back up a linked save/settings path safely.', entry.path);
    }
    final dest = p.join(target, p.basename(entry.path));
    if (type == FileSystemEntityType.directory) {
      _copyTree(entry.path, dest);
    } else if (type == FileSystemEntityType.file) {
      File(entry.path).copySync(dest);
    }
  }
}
