// Hookshot Builder: the Linux and Windows builder window in Flutter.
// Usage mirrors builder/linux/hookshot_builder.py:
//   (no args)            the builder window (Play is in the window, once built)
//   --play [folder]      start the built game, without opening the window
//   --launch <folder>    that folder's launcher: Play, and Update when newer
//   --update <folder> [--fetched] [--tag <tag>]   download the new release and build again
import 'dart:io';

import 'package:bitsdojo_window/bitsdojo_window.dart';
import 'package:fluent_ui/fluent_ui.dart';
import 'package:flutter_bloc/flutter_bloc.dart';

import 'blocs/builder_bloc.dart';
import 'blocs/launcher_bloc.dart';
import 'blocs/update_bloc.dart';
import 'config.dart' as cfg;
import 'navigation.dart';
import 'pages/files_page.dart';
import 'pages/launcher_page.dart';
import 'pages/progress_page.dart';
import 'pages/ready_page.dart';
import 'pages/widgets.dart';
import 'theme.dart';
import 'updater/manifest.dart' as upd;

Future<void> main(List<String> args) async {
  WidgetsFlutterBinding.ensureInitialized();
  doWhenWindowReady(() {
    appWindow
      ..minSize = const Size(880, 640)
      ..size = const Size(1000, 720)
      ..alignment = Alignment.center
      ..title = 'Hookshot Builder'
      ..show();
  });

  String? play;
  String? launch;
  String? update;
  var fetched = false;
  String? tag;
  for (var i = 0; i < args.length; i++) {
    switch (args[i]) {
      case '--play':
        play = (i + 1 < args.length && !args[i + 1].startsWith('--')) ? args[++i] : '';
      case '--launch':
        if (i + 1 < args.length) launch = args[++i];
      case '--update':
        if (i + 1 < args.length) update = args[++i];
      case '--fetched':
        fetched = true;
      case '--tag':
        if (i + 1 < args.length) tag = args[++i];
    }
  }

  if (play != null) {
    final folder = play.isEmpty ? cfg.loadConfig()['out'] : play;
    if (folder != null && upd.gameReady(folder)) {
      await BuilderBloc.playFolder(folder);
      exit(0);
    }
    // else fall through to the window
  }

  final toolsTag = upd.toolsTag(upd.runningRoot() ?? cfg.toolsRoot());
  runApp(HookshotApp(
      launchFolder: launch, updateFolder: update, updateFetched: fetched, updateTag: tag, toolsTag: toolsTag));
}

class HookshotApp extends StatefulWidget {
  final String? launchFolder;
  final String? updateFolder;
  final bool updateFetched;
  final String? updateTag;
  final String toolsTag;
  const HookshotApp(
      {super.key,
      this.launchFolder,
      this.updateFolder,
      this.updateFetched = false,
      this.updateTag,
      required this.toolsTag});

  @override
  State<HookshotApp> createState() => _HookshotAppState();
}

class _HookshotAppState extends State<HookshotApp> {
  late final BuilderBloc _builder;
  late final UpdateBloc _updater;

  @override
  void initState() {
    super.initState();
    _builder = BuilderBloc();
    _updater = UpdateBloc();
    if (widget.updateFolder != null) {
      _updater.add(BeginUpdate(
          folder: widget.updateFolder!,
          toolsTag: widget.toolsTag,
          latest: null,
          tag: widget.updateTag,
          fetched: widget.updateFetched));
    }
  }

  @override
  void dispose() {
    _builder.close();
    _updater.close();
    super.dispose();
  }

  Widget _launcher(String folder, {required VoidCallback? back}) {
    return BlocProvider(
      create: (_) => LauncherBloc(folder)..add(LauncherStarted(folder, widget.toolsTag)),
      child: _UpdateShell(
        fallback: LauncherPage(toolsTag: widget.toolsTag, onBack: back),
        returnToBuilder: false,
      ),
    );
  }

  Widget _switch(String key, Widget child) {
    return AnimatedSwitcher(
      duration: const Duration(milliseconds: 220),
      switchInCurve: Curves.easeOutCubic,
      switchOutCurve: Curves.easeInCubic,
      transitionBuilder: (child, animation) {
        final slide = Tween<Offset>(begin: const Offset(0, 0.012), end: Offset.zero)
            .animate(CurvedAnimation(parent: animation, curve: Curves.easeOutCubic));
        return FadeTransition(opacity: animation, child: SlideTransition(position: slide, child: child));
      },
      child: KeyedSubtree(key: ValueKey(key), child: child),
    );
  }

  @override
  Widget build(BuildContext context) {
    return MultiBlocProvider(
      providers: [
        BlocProvider.value(value: _builder),
        BlocProvider.value(value: _updater),
      ],
      child: FluentApp(
        title: 'Hookshot Builder',
        theme: hsTheme(),
        debugShowCheckedModeBanner: false,
        home: Container(
            color: const Color(0xFF14161a),
            child: Builder(builder: (context) {
              if (widget.launchFolder != null) {
                return _switch('launcher', _launcher(widget.launchFolder!, back: null));
              }
              return ValueListenableBuilder<String?>(
                valueListenable: gameLauncher,
                builder: (context, folder, _) {
                  if (folder != null) {
                    return _switch('launcher-$folder', _launcher(folder, back: closeGameLauncher));
                  }
                  if (widget.updateFolder != null) {
                    return _switch('update', const _UpdateShell(returnToBuilder: true));
                  }
                  return BlocBuilder<BuilderBloc, BuilderState>(
                    builder: (context, state) => _switch(
                      'builder-${state.runtimeType}',
                      switch (state) {
                        BuildRunning() => const ProgressPage(),
                        BuildDone() => const ReadyPage(),
                        BuildFailed() => const ProblemPage(),
                        _ => const FilesPage(),
                      },
                    ),
                  );
                },
              );
            })),
      ),
    );
  }
}

/// Update flow shell: download phase, then hand off to the build bloc. The
/// fallback is either the files form or the launched game's page.
class _UpdateShell extends StatelessWidget {
  final Widget? fallback;
  final bool returnToBuilder;
  const _UpdateShell({this.fallback, required this.returnToBuilder});

  @override
  Widget build(BuildContext context) {
    return MultiBlocListener(
      listeners: [
        BlocListener<UpdateBloc, UpdateState>(
          listener: (context, state) {
            if (state is UpdateHandoff && state.folder.isNotEmpty) {
              context.read<BuilderBloc>().add(MakeUpdateRequested(state.folder));
            } else if (state is UpdateReexec) {
              UpdateBloc.reexec(state.apprun, state.folder, state.tag);
            }
          },
        ),
      ],
      child: BlocBuilder<UpdateBloc, UpdateState>(
        builder: (context, state) {
          if (state is UpdateWorking) return _UpdateWorkingPage.fromState(state: state);
          if (state is UpdateIdle) return fallback ?? const FilesPage();
          if (state is UpdateFailed) {
            return _UpdateFailedPage(
              error: state.error,
              returnToBuilder: returnToBuilder,
              onBack: () {
                context.read<UpdateBloc>().add(const UpdateReset());
                if (returnToBuilder) context.read<BuilderBloc>().add(const BackToForm());
              },
            );
          }
          if (state is UpdateHandoff) {
            return BlocBuilder<BuilderBloc, BuilderState>(
              builder: (context, buildState) => switch (buildState) {
                BuildRunning() => const ProgressPage(),
                BuildDone() => const ReadyPage(),
                BuildFailed() => const ProblemPage(),
                _ => fallback ?? const FilesPage(),
              },
            );
          }
          // A self-update is about to replace and restart this process.
          return const _UpdateWorkingPage(
            title: 'Restarting Hookshot Builder',
            note: 'The update is ready. The builder will reopen shortly.',
            canCancel: false,
          );
        },
      ),
    );
  }
}

class _UpdateWorkingPage extends StatelessWidget {
  final String title;
  final String note;
  final bool canCancel;
  const _UpdateWorkingPage({
    required this.title,
    required this.note,
    this.canCancel = true,
  });
  _UpdateWorkingPage.fromState({required UpdateWorking state})
      : title = state.title,
        note = state.note,
        canCancel = true;

  @override
  Widget build(BuildContext context) {
    return Column(
      children: [
        const HsHeader(step: 1),
        Expanded(
          child: HsPage(
            fill: true,
            child: Center(
              child: ConstrainedBox(
                constraints: const BoxConstraints(maxWidth: 680),
                child: HsCard(
                  title: 'Update',
                  child: Row(
                    children: [
                      const ProgressRing(),
                      const SizedBox(width: 16),
                      Expanded(
                        child: Column(
                          crossAxisAlignment: CrossAxisAlignment.start,
                          mainAxisSize: MainAxisSize.min,
                          children: [
                            Text(title,
                                style: const TextStyle(fontSize: 18, fontWeight: FontWeight.w600, color: HsColors.ink)),
                            const SizedBox(height: 6),
                            HsNote(note),
                          ],
                        ),
                      ),
                    ],
                  ),
                ),
              ),
            ),
          ),
        ),
        if (canCancel)
          HsFooter(
            leading: const HsStatusLine('Downloaded files are verified before they are installed.'),
            actions: [
              HsButton.quiet(
                label: note.toLowerCase().contains('stopping') ? 'Stopping…' : 'Cancel update',
                onPressed: note.toLowerCase().contains('stopping')
                    ? null
                    : () => context.read<UpdateBloc>().add(const CancelUpdate()),
              ),
            ],
          )
        else
          const HsFooter(leading: HsStatusLine('Please keep Hookshot Builder open.')),
      ],
    );
  }
}

class _UpdateFailedPage extends StatelessWidget {
  final String error;
  final bool returnToBuilder;
  final VoidCallback onBack;
  const _UpdateFailedPage({required this.error, required this.returnToBuilder, required this.onBack});

  @override
  Widget build(BuildContext context) {
    return Column(
      children: [
        const HsHeader(step: 1),
        Expanded(
          child: HsPage(
            fill: true,
            child: Center(
              child: ConstrainedBox(
                constraints: const BoxConstraints(maxWidth: 720),
                child: HsCard(
                  title: 'The update stopped',
                  subtitle: 'Your current game and builder files were left in place.',
                  child: HsBanner(kind: HsBannerKind.warning, title: 'Error details', message: error),
                ),
              ),
            ),
          ),
        ),
        HsFooter(
          leading: const HsStatusLine('You can return and try the update again.'),
          actions: [
            HsButton.primary(
              label: returnToBuilder ? 'Back to builder' : 'Back to game',
              onPressed: onBack,
            ),
          ],
        ),
      ],
    );
  }
}
