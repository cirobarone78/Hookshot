import 'package:flutter_test/flutter_test.dart';
import 'package:hookshot_builder/config.dart' as cfg;
import 'package:hookshot_builder/updater/manifest.dart';

const _sha = 'e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855';

String _list() => '''
# a builder list
tag v2.1.0

part $_sha 12 tools https://example.com/a.zip
tree
part $_sha 34 sysroot https://example.com/b.zip
file bin/app
file lib/x.so
''';

void main() {
  group('parseList', () {
    test('parses tag, tree and file parts', () {
      final m = parseList(_list());
      expect(m.tag, 'v2.1.0');
      expect(m.parts.length, 2);
      expect(m.parts[0].files, isNull);
      expect(m.parts[1].files, ['bin/app', 'lib/x.so']);
      expect(m.bySha(_sha), isNotNull);
    });
    test('rejects hostile tags, dests and file names', () {
      expect(() => parseList('tag ..\npart $_sha 1 d https://example.com/a\ntree\n'), throwsFormatException);
      expect(() => parseList('tag /tmp/x\npart $_sha 1 d https://example.com/a\ntree\n'), throwsFormatException);
      expect(() => parseList('tag v1\npart $_sha 1 /abs https://example.com/a\ntree\n'), throwsFormatException);
    });
    test('rejects bad checksums, links and escapes', () {
      expect(() => parseList('tag v1\npart xyz 1 d https://e.com/a\ntree\n'), throwsFormatException);
      expect(() => parseList('tag v1\npart $_sha 1 d http://e.com/a\ntree\n'), throwsFormatException);
      expect(() => parseList('tag v1\npart $_sha 1 d https://e.com/a\nfile ../x\n'), throwsFormatException);
      expect(() => parseList('nothing here\n'), throwsFormatException);
    });
    test('sameAs compares sha, dest and files', () {
      final m = parseList(_list());
      expect(m.parts[1].sameAs(m.parts[1]), isTrue);
      expect(m.parts[0].sameAs(m.parts[1]), isFalse);
    });
  });

  group('versions', () {
    test('trackOf', () {
      expect(trackOf('v2.1.0'), 'release');
      expect(trackOf('v2.1.0-rc.1'), 'rc');
      expect(trackOf('v2.1.0-rc.1-3-gabcdef0'), 'nightly');
      expect(trackOf('dev'), 'release');
    });
    test('newestRelease', () {
      expect(newestRelease(['v2.0.5', 'v2.1.0-rc.1', 'v2.1.0', 'v2.0.9']), 'v2.1.0');
      expect(newestRelease(['v2.1.0-rc.1', 'v2.1.0-rc.2']), 'v2.1.0-rc.2');
      expect(newestRelease(['dev', null]), isNull);
    });
    test('updateTarget', () {
      expect(updateTarget('v2.1.0', 'v2.0.5'), 'v2.1.0');
      expect(updateTarget('v2.0.5', 'v2.1.0'), 'v2.1.0');
      expect(updateTarget(null, 'v2.0.5'), 'v2.0.5');
      expect(updateTarget('v2.1.0-rc.1-3-gabc', 'v2.1.0'), 'v2.1.0-rc.1-3-gabc');
    });
    test('chooseMode ignores an empty tools version', () {
      expect(chooseMode(null, '', 'v2.1.0', false, false), 'build');
    });
    test('repository override is validated', () {
      expect(cfg.repository(override: 'fork-name/Hookshot', root: '/missing'), 'fork-name/Hookshot');
      expect(cfg.repository(override: '../outside', root: '/missing'), cfg.defaultRepository);
      expect(listUrl('v2.2.0', 'fork-name/Hookshot'),
          'https://github.com/fork-name/Hookshot/releases/download/v2.2.0/hookshot-linux.txt');
    });
    test('chooseMode', () {
      expect(chooseMode('v2.0.5', 'v2.0.5', 'v2.1.0', false, true), 'update-game');
      expect(chooseMode('v2.1.0', 'v2.1.0', 'v2.1.0', false, true), 'up-to-date');
      expect(chooseMode(null, 'v2.0.5', 'v2.1.0', false, false), 'update-builder');
      expect(chooseMode(null, 'v2.1.0', 'v2.1.0', false, false), 'build');
      expect(chooseMode('v2.1.0', 'v2.1.0', null, false, true), 'up-to-date');
    });
  });
}
