import 'package:flutter_test/flutter_test.dart';
import 'package:hookshot_builder/gamescope.dart';

void main() {
  group('gamescope options', () {
    test('builds the Steam-style command line and stops at --', () {
      final settings = GamescopeSettings(
        enabled: true,
        width: 3840,
        height: 2160,
        refresh: 164,
        fullscreen: true,
        hdr: true,
        forceGrabCursor: true,
        realTime: true,
        extra: '--adaptive-sync --mangoapp',
      );
      expect(settings.command('/games/bin/hookshot'), [
        '-W',
        '3840',
        '-H',
        '2160',
        '-r',
        '164',
        '-f',
        '--hdr-enabled',
        '--force-grab-cursor',
        '--rt',
        '--adaptive-sync',
        '--mangoapp',
        '--',
        '/games/bin/hookshot',
      ]);
    });

    test('off or unset fields leave gamescope defaults alone', () {
      expect(GamescopeSettings().command('/g'), isEmpty);
      expect(GamescopeSettings(enabled: true).command('/g'), ['--', '/g']);
    });

    test('reads and range-checks the saved keys', () {
      final settings = GamescopeSettings.load({
        'gamescope': '1',
        'gamescope_width': '3840',
        'gamescope_height': '0',
        'gamescope_refresh': '164',
        'gamescope_hdr': '1',
        'gamescope_gamemoderun': '1',
      });
      expect(settings.enabled, isTrue);
      expect(settings.width, 3840);
      expect(settings.height, isNull);
      expect(settings.refresh, 164);
      expect(settings.hdr, isTrue);
      expect(settings.gameMode, isTrue);
    });
  });
}
