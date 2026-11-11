// The launcher's profiles, as nx2/profiles.py keeps them: one game user per profile, save/<id>.
import 'dart:convert';
import 'dart:io';

import 'package:path/path.dart' as p;

import 'config.dart' as cfg;

class ProfileException implements Exception {
  final String message;
  const ProfileException(this.message);
  @override
  String toString() => message;
}

class GameProfile {
  final String id;
  final String name;
  final bool isDefault;
  const GameProfile({required this.id, required this.name, required this.isDefault});
}

class SaveEntry {
  final String id;
  final String path;
  final String? user;
  final String label;
  const SaveEntry({required this.id, required this.path, required this.user, required this.label});
}

class Profiles {
  final String user;
  final bool supported;
  final List<GameProfile> list;
  final String selected;
  const Profiles({required this.user, required this.supported, required this.list, required this.selected});

  GameProfile? byId(String? id) {
    for (final profile in list) {
      if (profile.id == id) return profile;
    }
    return null;
  }

  /// The folder "Open save folder" shows, without making an empty save folder
  /// (the game would read that as a save that exists).
  String? folderToShow(String id) {
    for (final path in [p.join(user, 'save', id), p.join(user, 'save'), user]) {
      if (Directory(path).existsSync()) return path;
    }
    return null;
  }

  static Profiles fromJson(Map<String, dynamic> json) => Profiles(
        user: json['user'] as String,
        supported: json['supported'] as bool? ?? false,
        list: [
          for (final raw in (json['profiles'] as List? ?? const []))
            GameProfile(
              id: (raw as Map)['id'] as String,
              name: raw['name'] as String,
              isDefault: raw['default'] as bool? ?? false,
            )
        ],
        selected: json['selected'] as String? ?? '',
      );
}

/// Runs nx2/profiles.py (the engine the Tk launcher used too) and reads its one JSON object.
class ProfilesService {
  final Future<ProcessResult> Function(List<String> args) run;

  ProfilesService({Future<ProcessResult> Function(List<String> args)? run}) : run = run ?? _runPython;

  static Future<ProcessResult> _runPython(List<String> args) {
    final script = p.join(cfg.nxRoot(), 'profiles.py');
    if (!File(script).existsSync()) {
      throw ProfileException('The profile helper is missing: $script');
    }
    return Process.run(cfg.builderPython(), args,
        workingDirectory: cfg.toolsRoot(), stdoutEncoding: utf8, stderrEncoding: utf8);
  }

  Future<Map<String, dynamic>> _call(List<String> args) async {
    final script = p.join(cfg.nxRoot(), 'profiles.py');
    if (!File(script).existsSync()) {
      throw ProfileException('The profile helper is missing: $script');
    }
    final result = await run(['-I', '-B', script, ...args]);
    final text = (result.stdout as String).trim();
    Map<String, dynamic> json;
    try {
      json = jsonDecode(text) as Map<String, dynamic>;
    } catch (_) {
      final error = (result.stderr as String).trim();
      throw ProfileException(error.isEmpty ? 'The profile helper did not answer.' : error);
    }
    if (result.exitCode != 0 || json['error'] != null) {
      throw ProfileException(json['error'] as String? ?? 'The profile helper failed.');
    }
    return json;
  }

  Future<Profiles> load(String folder) async => Profiles.fromJson(await _call(['list', folder]));

  Future<Profiles> add(String folder, String name) async => Profiles.fromJson(await _call(['add', folder, name]));

  Future<Profiles> rename(String folder, String id, String name) async =>
      Profiles.fromJson(await _call(['rename', folder, id, name]));

  Future<Profiles> remove(String folder, String id) async => Profiles.fromJson(await _call(['remove', folder, id]));

  Future<String> export(String folder, String id, String parent) async {
    final json = await _call(['export', folder, id, parent]);
    return json['path'] as String;
  }

  /// The saves in a folder, one per emulator user (scripts/oot_saves.py saves).
  Future<List<SaveEntry>> saves(String source) async {
    final script = p.join(cfg.toolsRoot(), 'scripts', 'oot_saves.py');
    if (!File(script).existsSync()) throw ProfileException('The save importer is missing: $script');
    final result = await run(['-I', '-B', script, 'saves', '--from', source]);
    final text = (result.stdout as String).trim();
    if (result.exitCode != 0) {
      final error = (result.stderr as String).trim();
      throw ProfileException(error.isEmpty ? 'No Ocarina of Time saves were found.' : error);
    }
    final rows = jsonDecode(text) as List;
    return [
      for (final raw in rows)
        SaveEntry(
          id: (raw as Map)['id'] as String,
          path: raw['path'] as String,
          user: raw['user'] as String?,
          label: raw['label'] as String,
        )
    ];
  }

  /// Import a save from an emulator or a folder through scripts/oot_saves.py,
  /// with --hookshot the chosen profile's save folder (a new profile's is made).
  Future<String> importSave(String folder, Profiles profiles, String id, String source, {String? sourceProfile}) async {
    final save = p.join(profiles.user, 'save', id);
    final script = p.join(cfg.toolsRoot(), 'scripts', 'oot_saves.py');
    if (!File(script).existsSync()) throw ProfileException('The save importer is missing: $script');
    final backups = p.join(cfg.builderHome(), 'oot-save-backups');
    final result = await run([
      '-I',
      '-B',
      script,
      'import',
      '--from',
      source,
      '--hookshot',
      save,
      '--backup-dir',
      backups,
      if (sourceProfile != null) '--profile=$sourceProfile',
    ]);
    final out = '${result.stdout}${result.stderr}'.trim();
    if (result.exitCode != 0) {
      throw ProfileException(out.isEmpty ? 'The save could not be imported.' : out);
    }
    return out;
  }
}
