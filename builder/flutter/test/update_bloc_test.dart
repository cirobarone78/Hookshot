import 'dart:convert';
import 'dart:io';

import 'package:archive/archive.dart';
import 'package:crypto/crypto.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:hookshot_builder/blocs/update_bloc.dart';
import 'package:hookshot_builder/updater/installer.dart';

List<int> _zip(Map<String, String> entries) {
  final archive = Archive();
  entries.forEach((name, content) {
    archive.addFile(ArchiveFile(name, content.length, utf8.encode(content))..mode = 33188);
  });
  return ZipEncoder().encode(archive);
}

void main() {
  group('UpdateBloc cancellation', () {
    test('cancelling a download stops the update and stages nothing', () async {
      final tmp = await Directory.systemTemp.createTemp('hookshot-bloc-cancel-');
      try {
        final treeZip = _zip({'usr/share/hookshot/builder/linux/AppRun': '#!/bin/sh\n'});
        final treeSha = sha256.convert(treeZip).toString();
        final list = 'tag v9.9.9\npart $treeSha ${treeZip.length} . https://example.com/tree.zip\ntree\n';
        Future<List<int>> get(String url, {StopFlag? stop}) async {
          if (url.endsWith('hookshot-linux.txt')) return utf8.encode(list);
          for (var i = 0; i < 200; i++) {
            await Future<void>.delayed(const Duration(milliseconds: 20));
            if (stop != null && stop.isSet) throw const Cancelled();
          }
          return treeZip;
        }

        final bloc = UpdateBloc(
          fetcher: get,
          runningRoot: () => tmp.path,
          installRoot: '${tmp.path}/builder',
        );
        addTearDown(bloc.close);
        final done = expectLater(
            bloc.stream, emitsThrough(isA<UpdateFailed>().having((s) => s.error, 'error', contains('cancelled'))));
        bloc.add(const BeginUpdate(folder: '', toolsTag: 'v9.9.0', latest: 'v9.9.9'));
        await Future<void>.delayed(const Duration(milliseconds: 400));
        bloc.add(const CancelUpdate());
        await done;
        expect(Directory('${tmp.path}/builder/versions/v9.9.9').existsSync(), isFalse);
        expect(Directory('${tmp.path}/builder/versions/v9.9.9.part').existsSync(), isFalse);
      } finally {
        await tmp.delete(recursive: true);
      }
    });
  });
}
