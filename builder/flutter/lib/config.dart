// Builder configuration and environment: builder.ini, tool paths, constants.
// Mirrors builder/linux/hookshot_builder.py's load_config/save_config, ROOT
// resolution, and nx2/make_game.py's LANGUAGES.
import 'dart:io';

import 'package:path/path.dart' as p;

const appId = 'io.github.NotRexed.Hookshot';
const builderVersion = '1.0.0'; // (the desktop app's own version; the tools/game version is separate)
const defaultRepository = 'NotRexed/Hookshot';
const tracks = ['release', 'rc', 'nightly'];
const trackNames = {'release': 'Release', 'rc': 'Release candidate', 'nightly': 'Nightly'};

/// (code, human name), as nx2/make_game.py LANGUAGES.
const languages = [
  ('en-US', 'English (US)'),
  ('en-GB', 'English (UK)'),
  ('fr', 'French (France)'),
  ('fr-CA', 'French (Canada)'),
  ('de', 'German'),
  ('it', 'Italian'),
  ('es', 'Spanish (Spain)'),
  ('es-419', 'Spanish (Latin America)'),
  ('pt-BR', 'Portuguese (Brazil)'),
  ('nl', 'Dutch'),
  ('pl', 'Polish'),
  ('ru', 'Russian'),
  ('ja', 'Japanese'),
  ('ko', 'Korean'),
  ('zh-Hans', 'Chinese (Simplified)'),
  ('zh-Hant', 'Chinese (Traditional)'),
];

const dlssLicense = '''
NVIDIA DLSS is NVIDIA's, not Hookshot's. With it ticked, the build downloads NVIDIA's DLSS SDK (release v310.9.16) from github.com/NVIDIA/DLSS, under NVIDIA's own license, the NVIDIA RTX SDKs license:

https://github.com/NVIDIA/DLSS/blob/9981c6350dc58c58e75131689e19aa547db65571/LICENSE.txt

Its files stay on this PC (in the builder's ngx-sdk folder, and libnvidia-ngx-dlss.so in the game folder's ngx folder). Hookshot never includes or shares them: never share a game folder built with them.

Do you accept NVIDIA's license?''';

String get _home => Platform.environment['HOME'] ?? Platform.environment['USERPROFILE'] ?? '~';

/// Per-user Hookshot Builder data. Create an empty portable.txt beside the
/// executable to keep settings, downloads and backups beside the app instead.
String builderHome() {
  final override = Platform.environment['HOOKSHOT_BUILDER_HOME'];
  String? base = override != null && override.isNotEmpty ? override : null;
  if (base == null) {
    try {
      final exeDir = File(Platform.resolvedExecutable).parent.path;
      if (File(p.join(exeDir, 'portable.txt')).existsSync()) base = p.join(exeDir, 'data');
    } catch (_) {}
  }
  if (Platform.isWindows) {
    final local = Platform.environment['LOCALAPPDATA'];
    final root = base ?? (local != null && local.isNotEmpty ? local : p.join(_home, 'AppData', 'Local'));
    return p.join(root, 'HookshotBuilder');
  }
  final data = base ?? Platform.environment['XDG_DATA_HOME'] ?? p.join(_home, '.local', 'share');
  return p.join(data, 'hookshot', 'builder');
}

String configPath() {
  if (Platform.isWindows) return p.join(builderHome(), 'builder.ini');
  // (the same file the Tk builder and hookshot-launch read on Linux)
  final xdg = Platform.environment['XDG_CONFIG_HOME'];
  final base = xdg != null && xdg.isNotEmpty ? xdg : p.join(_home, '.config');
  return p.join(base, 'hookshot', 'builder.ini');
}

/// The tools root: HOOKSHOT_TOOLS when packaged, else this repository checkout.
String toolsRoot() {
  final tools = Platform.environment['HOOKSHOT_TOOLS'];
  if (tools != null && tools.isNotEmpty) return tools;
  // Walk up from the running binary until nx2/make_game.py is found
  // (debug bundle, test runner and packaged layouts all differ).
  var dir = Directory(File(Platform.script.toFilePath()).parent.path);
  for (var i = 0; i < 10; i++) {
    if (File('${dir.path}/nx2/make_game.py').existsSync()) return dir.path;
    final parent = dir.parent;
    if (parent.path == dir.path) break;
    dir = parent;
  }
  return Directory.current.path;
}

/// nx2/make_game.py and friends live here.
String nxRoot() => '${toolsRoot()}/nx2';

final _repositoryPattern = RegExp(r'^[A-Za-z0-9-]+/[A-Za-z0-9._-]+$');

/// Repository releases come from. Packaged releases carry repository.txt;
/// source builds can override it with HOOKSHOT_REPOSITORY.
String repository({String? override, String? root}) {
  final env = override ?? Platform.environment['HOOKSHOT_REPOSITORY'];
  if (env != null && _repositoryPattern.hasMatch(env.trim())) return env.trim();
  final base = root ?? toolsRoot();
  for (final path in ['$base/repository.txt', '$base/tools/repository.txt']) {
    try {
      final candidate = File(path).readAsLinesSync().first.trim();
      if (_repositoryPattern.hasMatch(candidate)) return candidate;
    } catch (_) {}
  }
  return defaultRepository;
}

/// The Python running make_game.py: the packaged one when present, else the checkout's deps one, else PATH.
String builderPython() {
  if (Platform.isWindows) {
    final local = Platform.environment['LOCALAPPDATA'] ?? '';
    for (final path in [
      '${toolsRoot()}/python/python.exe', // (the packaged builder's own Python)
      '${toolsRoot()}/tools/python/python.exe',
      if (local.isNotEmpty) '$local/Programs/Python/Python313/python.exe',
      if (local.isNotEmpty) '$local/Programs/Python/Python312/python.exe',
      if (local.isNotEmpty) '$local/Programs/Python/Python311/python.exe',
      if (local.isNotEmpty) '$local/Programs/Python/Python310/python.exe',
    ]) {
      if (File(path).existsSync()) return path;
    }
    // (the launcher may point at the right Python when python.exe is only
    // Windows' Store alias)
    try {
      final py = Process.runSync('py', ['-3', '-c', 'import sys; print(sys.executable)']);
      final found = (py.stdout as String).trim();
      if (py.exitCode == 0 && found.isNotEmpty && File(found).existsSync()) return found;
    } catch (_) {}
    return 'python.exe';
  }
  final packaged = '${toolsRoot()}/usr/python/bin/python3';
  if (File(packaged).existsSync()) return packaged;
  final deps = '${toolsRoot()}/build-linux/deps/python/bin/python3';
  if (File(deps).existsSync()) return deps;
  return 'python3';
}

Map<String, String> loadConfig() {
  final cfg = <String, String>{};
  try {
    for (final raw in File(configPath()).readAsLinesSync()) {
      final line = raw.trim();
      if (line.isEmpty) continue;
      final i = line.indexOf('=');
      if (i > 0) cfg[line.substring(0, i)] = line.substring(i + 1);
    }
  } catch (_) {}
  return cfg;
}

void saveConfig(Map<String, String> cfg) {
  final path = configPath();
  Directory(File(path).parent.path).createSync(recursive: true);
  File(path).writeAsStringSync(cfg.entries.map((e) => '${e.key}=${e.value}\n').join());
}

/// Free GB under [folder] (nearest existing ancestor), null when unknown.
double? freeGb(String folder) {
  try {
    if (Platform.isWindows) {
      const script =
          r'''$path=$env:HOOKSHOT_FREE_PATH; while(-not [IO.Directory]::Exists($path)) { $parent=[IO.Directory]::GetParent($path); if($null -eq $parent) { break }; $path=$parent.FullName }; $root=[IO.Path]::GetPathRoot($path); [long]([IO.DriveInfo]::new($root).AvailableFreeSpace)''';
      final result = Process.runSync('powershell.exe', [
        '-NoProfile',
        '-NonInteractive',
        '-Command',
        script,
      ], environment: {
        ...Platform.environment,
        'HOOKSHOT_FREE_PATH': folder.isEmpty ? _home : folder
      });
      if (result.exitCode != 0) return null;
      return int.parse((result.stdout as String).trim()) / (1 << 30);
    }
    var path = folder.isEmpty ? '/' : folder;
    while (path != '/' && !Directory(path).existsSync()) {
      final parent = Directory(path).parent.path;
      if (parent == path) break;
      path = parent;
    }
    final result = Process.runSync('df', ['-k', '--output=avail', path]);
    if (result.exitCode != 0) return null;
    final lines = (result.stdout as String).trim().split('\n');
    if (lines.length < 2) return null;
    return int.parse(lines.last.trim()) / (1 << 20);
  } catch (_) {
    return null;
  }
}
