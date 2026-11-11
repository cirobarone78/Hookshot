import 'package:flutter_test/flutter_test.dart';
import 'package:hookshot_builder/backend/build_events.dart';

void main() {
  group('parseBuilderLine', () {
    test('stage', () {
      expect(parseBuilderLine('@@stage compile Compiling'),
          isA<StageEvent>().having((e) => e.id, 'id', 'compile').having((e) => e.text, 'text', 'Compiling'));
    });
    test('progress', () {
      expect(parseBuilderLine('@@progress 0.5'), isA<ProgressEvent>().having((e) => e.fraction, 'fraction', 0.5));
    });
    test('plan', () {
      final e = parseBuilderLine('@@plan 3 468');
      expect(e, isA<PlanEvent>().having((e) => e.changed, 'changed', 3).having((e) => e.total, 'total', 468));
    });
    test('file', () {
      final e = parseBuilderLine('@@file code_021.c 82.2 new');
      expect(
          e,
          isA<FileEvent>()
              .having((e) => e.name, 'name', 'code_021.c')
              .having((e) => e.seconds, 'seconds', 82.2)
              .having((e) => e.kind, 'kind', 'new'));
    });
    test('eta / times / done / error', () {
      expect(parseBuilderLine('@@eta 1760'), isA<EtaEvent>());
      expect(parseBuilderLine('@@times 2400 1800 -1'), isA<TimesEvent>());
      expect(parseBuilderLine('@@done /tmp/Hookshot'),
          isA<DoneEvent>().having((e) => e.folder, 'folder', '/tmp/Hookshot'));
      expect(parseBuilderLine('@@error boom'), isA<ErrorEvent>().having((e) => e.text, 'text', 'boom'));
    });
    test('not prepared + damaged', () {
      expect(parseBuilderLine('the shaders were not prepared now (no usable Vulkan here)'), isA<NotPreparedEvent>());
      expect(parseBuilderLine('Your game dump is incomplete: 3 game files in it are damaged (a complete dump ...)'),
          isA<DamagedEvent>().having((e) => e.count, 'count', 3));
    });
    test('plain lines pass through', () {
      expect(parseBuilderLine('compiling vk_shader.cpp'), isA<LogEvent>());
    });
  });

  group('damagedCount', () {
    test('parses plural and singular', () {
      expect(damagedCount('Your game dump is incomplete: 3 game files in it are damaged (x)'), 3);
      expect(damagedCount('Your game dump is incomplete: 1 game file in it is damaged (x)'), 1);
    });
    test('ignores other lines', () {
      expect(damagedCount('@@stage read Reading your game files'), 0);
      expect(damagedCount(''), 0);
      expect(damagedCount('Your game dump is incomplete'), 0);
    });
  });

  group('reported', () {
    test('error and check lines', () {
      expect(reported('@@error boom happened'), 'boom happened');
      expect(reported('@@check ok This is the version Hookshot supports (build e0f3ccfa).'),
          'This is the version Hookshot supports (build e0f3ccfa).');
      expect(reported('@@check bad This is build abcdef01. Hookshot supports build e0f3ccfa.'),
          'This is build abcdef01. Hookshot supports build e0f3ccfa.');
    });
    test('other lines are not status', () {
      expect(reported('@@stage compile Compiling'), isNull);
      expect(reported('@@done /tmp/Hookshot'), isNull);
      expect(reported('compiled in 10s'), isNull);
    });
  });
}
