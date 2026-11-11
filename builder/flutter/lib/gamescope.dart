// gamescope launch settings: the Linux-only Play option and its compositor flags.
import 'dart:io';

import 'config.dart' as cfg;

class GamescopeSettings {
  bool enabled;
  int? width;
  int? height;
  int? refresh;
  bool hdr;
  bool fullscreen;
  bool realTime;
  bool forceGrabCursor;
  bool gameMode;
  String extra;

  GamescopeSettings({
    this.enabled = false,
    this.width,
    this.height,
    this.refresh,
    this.hdr = false,
    this.fullscreen = false,
    this.realTime = false,
    this.forceGrabCursor = false,
    this.gameMode = false,
    this.extra = '',
  });

  /// A short line for the button beside "Launch in gamescope".
  String get summary {
    final parts = <String>[
      if (width != null || height != null) '${width ?? 'auto'}×${height ?? 'auto'}',
      if (refresh != null) '$refresh Hz',
      if (fullscreen) 'fullscreen',
      if (hdr) 'HDR',
      if (realTime) 'real-time',
      if (forceGrabCursor) 'grab cursor',
      if (gameMode) 'gamemoderun',
      if (extra.trim().isNotEmpty) extra.trim(),
    ];
    return parts.isEmpty ? 'gamescope defaults' : parts.join(' · ');
  }

  /// The arguments after gamescope's name, ending with `-- exe`. Empty when
  /// gamescope is off. [extra] is split on whitespace: it is passed to
  /// gamescope as separate arguments, never through a shell.
  List<String> command(String exe) {
    if (!enabled) return const [];
    final args = <String>[];
    if (width != null) args.addAll(['-W', '$width']);
    if (height != null) args.addAll(['-H', '$height']);
    if (refresh != null) args.addAll(['-r', '$refresh']);
    if (fullscreen) args.add('-f');
    if (hdr) args.add('--hdr-enabled');
    if (forceGrabCursor) args.add('--force-grab-cursor');
    if (realTime) args.add('--rt');
    for (final part in extra.split(RegExp(r'\s+'))) {
      if (part.isEmpty || part == '--') continue;
      args.add(part);
    }
    args.addAll(['--', exe]);
    return args;
  }

  Map<String, String> get _map => {
        'gamescope': enabled ? '1' : '0',
        'gamescope_width': width?.toString() ?? '',
        'gamescope_height': height?.toString() ?? '',
        'gamescope_refresh': refresh?.toString() ?? '',
        'gamescope_hdr': hdr ? '1' : '0',
        'gamescope_fullscreen': fullscreen ? '1' : '0',
        'gamescope_rt': realTime ? '1' : '0',
        'gamescope_grab_cursor': forceGrabCursor ? '1' : '0',
        'gamescope_gamemoderun': gameMode ? '1' : '0',
        'gamescope_extra': extra.trim(),
      };

  void save() {
    final config = cfg.loadConfig();
    config.addAll(_map);
    cfg.saveConfig(config);
  }

  static GamescopeSettings load([Map<String, String>? config]) {
    final c = config ?? cfg.loadConfig();
    int? number(String key, int min, int max) {
      final value = int.tryParse(c[key] ?? '');
      return value != null && value >= min && value <= max ? value : null;
    }

    return GamescopeSettings(
      enabled: c['gamescope'] == '1' && Platform.isLinux,
      width: number('gamescope_width', 320, 16384),
      height: number('gamescope_height', 200, 16384),
      refresh: number('gamescope_refresh', 1, 1000),
      hdr: c['gamescope_hdr'] == '1',
      fullscreen: c['gamescope_fullscreen'] == '1',
      realTime: c['gamescope_rt'] == '1',
      forceGrabCursor: c['gamescope_grab_cursor'] == '1',
      gameMode: c['gamescope_gamemoderun'] == '1',
      extra: c['gamescope_extra'] ?? '',
    );
  }
}
