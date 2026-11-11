import 'package:fluent_ui/fluent_ui.dart';
import 'package:flutter_bloc/flutter_bloc.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:hookshot_builder/blocs/builder_bloc.dart';
import 'package:hookshot_builder/pages/files_page.dart';
import 'package:hookshot_builder/pages/progress_page.dart';
import 'package:hookshot_builder/pages/ready_page.dart';
import 'package:hookshot_builder/theme.dart';

class _FixedBuilderBloc extends BuilderBloc {
  final BuilderState fixedState;
  _FixedBuilderBloc(this.fixedState) : super();

  @override
  BuilderState get state => fixedState;

  @override
  Stream<BuilderState> get stream => const Stream<BuilderState>.empty();

  @override
  void add(BuilderEvent event) {}
}

BuilderForm _form({String kind = 'nup'}) => BuilderForm(
      kind: kind,
      nup: '/games/example.nup',
      romfs: '/games/romfs',
      exefs: '/games/exefs',
      out: '/games/Hookshot',
      language: 'English (US)',
      prepare: true,
      dlss: false,
      track: 'release',
      checkText: '',
      latest: null,
      spaceGb: 120,
      buttonLabel: 'Build the game',
      aboutLabel: 'About 45 min',
      gameReady: false,
      sourcePicked: false,
      dlssToggled: false,
      mode: 'build',
    );

Widget _app(BuilderState state) => FluentApp(
      theme: hsTheme(),
      home: BlocProvider<BuilderBloc>.value(
        value: _FixedBuilderBloc(state),
        child: switch (state) {
          BuildRunning() => const ProgressPage(),
          BuildDone() => const ReadyPage(),
          BuildFailed() => const ProblemPage(),
          _ => const FilesPage(),
        },
      ),
    );

void _useSize(WidgetTester tester, Size size) {
  tester.view.devicePixelRatio = 1;
  tester.view.physicalSize = size;
  addTearDown(tester.view.resetPhysicalSize);
  addTearDown(tester.view.resetDevicePixelRatio);
}

void main() {
  testWidgets('form stays inside the minimum desktop window and scrolls cleanly', (tester) async {
    _useSize(tester, const Size(880, 640));
    await tester.pumpWidget(_app(_form()));
    await tester.pump();

    expect(find.text('Build your game'), findsOneWidget);
    expect(find.text('GAME FILES'), findsOneWidget);
    expect(find.text('INSTALL LOCATION'), findsOneWidget);
    expect(find.text('BUILD OPTIONS'), findsOneWidget);
    expect(tester.takeException(), isNull);
  });

  testWidgets('extracted-folder form uses the same grouped layout', (tester) async {
    _useSize(tester, const Size(1000, 720));
    await tester.pumpWidget(_app(_form(kind: 'folders')));
    await tester.pump();

    expect(find.text('romfs folder'), findsOneWidget);
    expect(find.text('exefs folder'), findsOneWidget);
    expect(find.text('Update track'), findsOneWidget);
    expect(tester.takeException(), isNull);
  });

  testWidgets('build progress fits the minimum desktop window', (tester) async {
    _useSize(tester, const Size(880, 640));
    final state = BuildRunning(
      title: 'Building your game',
      stageText: 'Compiling 7 of 10 changed files',
      fraction: 0.62,
      eta: 120,
      log: List.generate(40, (i) => 'Build output line $i'),
      changed: 10,
      compiledFiles: 7,
      totalFiles: 10,
      started: DateTime.now().subtract(const Duration(minutes: 2)),
      compileStarted: DateTime.now().subtract(const Duration(minutes: 1)),
      totalSecs: null,
      compiledSecs: null,
      previousSecs: null,
      shadersLater: false,
      damagedCount: 2,
      error: null,
      built: null,
    );
    await tester.pumpWidget(_app(state));
    await tester.pump();

    expect(find.text('BUILD PROGRESS'), findsOneWidget);
    expect(find.text('BUILD LOG'), findsOneWidget);
    expect(find.text('2 damaged game file(s) found'), findsOneWidget);
    expect(tester.takeException(), isNull);
  });

  testWidgets('ready page keeps damaged-file warning visible', (tester) async {
    _useSize(tester, const Size(1000, 720));
    await tester.pumpWidget(_app(const BuildDone(
      folder: '/games/Hookshot',
      text: 'Ready in 00:40',
      compiledSecs: 10,
      previousSecs: null,
      shadersLater: false,
      damagedCount: 3,
    )));
    await tester.pump();

    expect(find.text('Your game is ready'), findsOneWidget);
    expect(find.text('3 damaged game file(s) found'), findsOneWidget);
    expect(tester.takeException(), isNull);
  });
}
