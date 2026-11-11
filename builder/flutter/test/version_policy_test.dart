import 'dart:io';

import 'package:flutter_test/flutter_test.dart';
import 'package:hookshot_builder/updater/version_policy.dart';

void main() {
  group('version policy', () {
    test('pin file is per game folder and rejects unsafe tags', () async {
      final root = await Directory.systemTemp.createTemp('hookshot-pin-');
      addTearDown(() => root.delete(recursive: true));
      final game = Directory('${root.path}/game')..createSync();

      expect(pinnedVersion(game.path), isNull);
      setPinnedVersion(game.path, 'v2.2.0');
      expect(pinnedVersion(game.path), 'v2.2.0');
      expect(() => setPinnedVersion(game.path, '../outside'), throwsFormatException);
      setPinnedVersion(game.path, null);
      expect(pinnedVersion(game.path), isNull);
    });

    test('version switch backup preserves saves and settings without altering the game', () async {
      final root = await Directory.systemTemp.createTemp('hookshot-version-backup-');
      addTearDown(() => root.delete(recursive: true));
      final game = Directory('${root.path}/game')..createSync();
      final save = Directory('${game.path}/user/save/slot_0')..createSync(recursive: true);
      File('${save.path}/slot.sav').writeAsStringSync('authored save');
      File('${game.path}/hookshot_options.ini').writeAsStringSync('authored settings');
      File('${game.path}/hookshot_env.txt').writeAsStringSync('authored environment');

      final backup = backupBeforeSwitch(game.path, backupRoot: '${root.path}/builder')!;
      expect(File('$backup/game/user/save/slot_0/slot.sav').readAsStringSync(), 'authored save');
      expect(File('$backup/game/hookshot_options.ini').readAsStringSync(), 'authored settings');
      expect(File('$backup/game/hookshot_env.txt').readAsStringSync(), 'authored environment');
      expect(File('${save.path}/slot.sav').readAsStringSync(), 'authored save');
    });
  });
}
