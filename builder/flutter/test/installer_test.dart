import 'dart:convert';
import 'dart:io';

import 'package:archive/archive.dart';
import 'package:crypto/crypto.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:hookshot_builder/updater/installer.dart';
import 'package:hookshot_builder/updater/manifest.dart';

List<int> _zip(Map<String, dynamic> entries) {
  // value: String content, or ['link', target] for symlinks.
  final archive = Archive();
  entries.forEach((name, value) {
    if (value is String) {
      archive.addFile(ArchiveFile(name, value.length, utf8.encode(value))..mode = 33188);
    } else {
      final target = (value as List)[1] as String;
      final f = ArchiveFile(name, target.length, utf8.encode(target));
      f.mode = 41453; // 0o120755: symlink
      archive.addFile(f);
    }
  });
  return ZipEncoder().encode(archive);
}

String _sha(List<int> bytes) => sha256.convert(bytes).toString();

void main() {
  group('install', () {
    test('installs tree and file parts, keeps install atomic', () async {
      final tmp = await Directory.systemTemp.createTemp('hookshot-install-');
      try {
        final treeZip = _zip({'usr/share/hookshot/builder/linux/AppRun': '#!/bin/sh\n'});
        final fileZip = _zip({
          'hookspot.png': 'fake-png',
          'usr/lib/hookshot/cpm/x': 'headers',
        });
        Future<List<int>> get(String url) async {
          if (url == 'https://example.com/tree.zip') return treeZip;
          if (url == 'https://example.com/files.zip') return fileZip;
          throw StateError('unexpected url $url');
        }

        final manifest = Manifest('v9.9.9', [
          Part(_sha(treeZip), treeZip.length, '.', 'https://example.com/tree.zip', null),
          Part(_sha(fileZip), fileZip.length, 'file-part', 'https://example.com/files.zip',
              ['hookspot.png', 'usr/lib/hookshot/cpm/x']),
        ]);
        final notes = <String>[];
        final apprun =
            await install(manifest, null, null, get: get, note: notes.add, rootOverride: '${tmp.path}/builder');
        expect(File(apprun).existsSync(), isTrue);
        expect(
            File('${tmp.path}/builder/versions/v9.9.9/usr/share/hookshot/builder/linux/AppRun').existsSync(), isTrue);
        expect(File('${tmp.path}/builder/versions/v9.9.9/file-part/hookspot.png').readAsStringSync(), 'fake-png');
        // the installed list is written beside the parts
        expect(File('${tmp.path}/builder/versions/v9.9.9/hookshot-linux.txt').existsSync(), isTrue);
        // current points at the new version
        expect(File('${tmp.path}/builder/current').readAsStringSync().trim(), 'v9.9.9');
        expect(notes.any((n) => n.contains('Downloading')), isTrue);
      } finally {
        await tmp.delete(recursive: true);
      }
    });

    test('checksum mismatch aborts without installing', () async {
      final tmp = await Directory.systemTemp.createTemp('hookshot-install-bad-');
      try {
        Future<List<int>> get(String url) async => utf8.encode('wrong bytes');
        final manifest = Manifest('v9.9.9', [
          Part(_sha([1, 2, 3]), 11, 'p', 'https://example.com/p.zip', null)
        ]);
        await expectLater(
            install(manifest, null, null, get: get, rootOverride: '${tmp.path}/builder'), throwsStateError);
        expect(Directory('${tmp.path}/builder/versions/v9.9.9').existsSync(), isFalse);
      } finally {
        await tmp.delete(recursive: true);
      }
    });

    test('symlinks inside the staging tree work, escapes fail', () async {
      final tmp = await Directory.systemTemp.createTemp('hookshot-install-link-');
      try {
        final goodZip = _zip({
          'real.txt': 'data',
          'alias.txt': ['link', 'real.txt'],
          'usr/share/hookshot/builder/linux/AppRun': '#!/bin/sh\n',
        });
        Future<List<int>> get(String url) async => goodZip;
        final manifest =
            Manifest('v9.9.9', [Part(_sha(goodZip), goodZip.length, '.', 'https://example.com/p.zip', null)]);
        await install(manifest, null, null, get: get, rootOverride: '${tmp.path}/builder');
        expect(Link('${tmp.path}/builder/versions/v9.9.9/alias.txt').targetSync(), 'real.txt');

        final evilZip = _zip({
          'evil.txt': ['link', '../../outside.txt'],
          'usr/share/hookshot/builder/linux/AppRun': '#!/bin/sh\n',
        });
        Future<List<int>> getEvil(String url) async => evilZip;
        final evil = Manifest('v9.9.10', [Part(_sha(evilZip), evilZip.length, '.', 'https://example.com/e.zip', null)]);
        await expectLater(
            install(evil, null, null, get: getEvil, rootOverride: '${tmp.path}/builder'), throwsArgumentError);
        expect(Directory('${tmp.path}/builder/versions/v9.9.10').existsSync(), isFalse);
      } finally {
        await tmp.delete(recursive: true);
      }
    });
  });

  group('cancellation', () {
    test('fetchBytes ends a slow download with Cancelled', () async {
      final server = await HttpServer.bind('127.0.0.1', 0);
      addTearDown(server.close);
      server.listen((request) async {
        request.response.headers.contentLength = 8 << 20;
        for (var i = 0; i < 80; i++) {
          await Future<void>.delayed(const Duration(milliseconds: 100));
          try {
            request.response.add(List.filled(100 * 1024, 0));
            await request.response.flush();
          } catch (_) {
            return;
          }
        }
        await request.response.close();
      });
      final stop = StopFlag();
      final future = fetchBytes('http://127.0.0.1:${server.port}/part.zip', stop: stop);
      await Future<void>.delayed(const Duration(milliseconds: 350));
      stop.set();
      await expectLater(future, throwsA(isA<Cancelled>()));
    });

    test('install removes staged parts when cancelled', () async {
      final tmp = await Directory.systemTemp.createTemp('hookshot-install-cancel-');
      try {
        final treeZip = _zip({'usr/share/hookshot/builder/linux/AppRun': '#!/bin/sh\n'});
        final treeSha = _sha(treeZip);
        final stop = StopFlag();
        Future<List<int>> get(String url) async {
          for (var i = 0; i < 100; i++) {
            await Future<void>.delayed(const Duration(milliseconds: 20));
            if (stop.isSet) throw const Cancelled();
          }
          return treeZip;
        }

        final manifest = Manifest('v9.9.9', [Part(treeSha, treeZip.length, '.', 'https://example.com/tree.zip', null)]);
        final run = install(manifest, null, null, get: get, rootOverride: '${tmp.path}/builder', stop: stop);
        await Future<void>.delayed(const Duration(milliseconds: 150));
        stop.set();
        await expectLater(run, throwsA(isA<Cancelled>()));
        expect(Directory('${tmp.path}/builder/versions/v9.9.9').existsSync(), isFalse);
        expect(Directory('${tmp.path}/builder/versions/v9.9.9.part').existsSync(), isFalse);
      } finally {
        await tmp.delete(recursive: true);
      }
    });
  });
}
