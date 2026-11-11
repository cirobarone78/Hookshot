// Build/update progress: stage track, live log, elapsed time and cancel.
import 'dart:async';

import 'package:fluent_ui/fluent_ui.dart';
import 'package:flutter_bloc/flutter_bloc.dart';
import 'package:lucide_icons_flutter/lucide_icons.dart';

import '../blocs/builder_bloc.dart';
import '../theme.dart';
import 'widgets.dart';

class ProgressPage extends StatefulWidget {
  const ProgressPage({super.key});
  @override
  State<ProgressPage> createState() => _ProgressPageState();
}

class _ProgressPageState extends State<ProgressPage> {
  Timer? _timer;

  @override
  void initState() {
    super.initState();
    _timer = Timer.periodic(const Duration(seconds: 1), (_) => setState(() {}));
  }

  @override
  void dispose() {
    _timer?.cancel();
    super.dispose();
  }

  String _clock(BuildRunning state) {
    String two(int value) => value.toString().padLeft(2, '0');
    final elapsed = DateTime.now().difference(state.started);
    var text = 'Elapsed ${elapsed.inHours}:${two(elapsed.inMinutes % 60)}:${two(elapsed.inSeconds % 60)}';
    if (state.compileStarted != null) {
      final compile = DateTime.now().difference(state.compileStarted!);
      text += ' · compiling ${compile.inMinutes}:${two(compile.inSeconds % 60)}';
    }
    if (state.eta != null) text += ' · ${leftText(state.eta!)}';
    return text;
  }

  int _stage(BuildRunning state) {
    final text = state.stageText.toLowerCase();
    if (text.contains('read')) return 0;
    if (text.contains('translat') || text.contains('lift')) return 1;
    if (text.contains('compil')) return 2;
    if (text.contains('putting') || text.contains('shader') || text.contains('finish')) return 3;
    final progress = state.fraction;
    if (progress == null) return 0;
    if (progress < 0.05) return 0;
    if (progress < 0.25) return 1;
    if (progress < 0.95) return 2;
    return 3;
  }

  @override
  Widget build(BuildContext context) {
    return BlocBuilder<BuilderBloc, BuilderState>(
      builder: (context, state) {
        if (state is! BuildRunning) return const SizedBox.shrink();
        final stage = _stage(state);
        return Column(
          children: [
            const HsHeader(step: 1),
            Expanded(
              child: HsPage(
                fill: true,
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text(state.title,
                        style: const TextStyle(fontSize: 23, fontWeight: FontWeight.bold, color: HsColors.ink)),
                    const SizedBox(height: 4),
                    const HsNote('Hookshot is working through the build. You can keep using your PC.'),
                    if (state.damagedCount > 0) ...[
                      const SizedBox(height: 14),
                      HsBanner(
                        kind: HsBannerKind.warning,
                        title: '${state.damagedCount} damaged game file(s) found',
                        message:
                            'Available stand-ins are being used; files with no replacement stop the build. The list is saved as hookshot_damaged_files.txt beside the game.',
                      ),
                    ],
                    const SizedBox(height: 16),
                    Expanded(
                      child: LayoutBuilder(
                        builder: (context, constraints) {
                          final compact = constraints.maxHeight < 350 || constraints.maxWidth < 720;
                          final stages = _progressCard(state, stage, compact: compact);
                          final log = _logCard(state);
                          if (constraints.maxWidth < 720) {
                            return Column(
                              children: [
                                SizedBox(height: 235, child: stages),
                                const SizedBox(height: 12),
                                Expanded(child: log),
                              ],
                            );
                          }
                          return Row(
                            crossAxisAlignment: CrossAxisAlignment.stretch,
                            children: [
                              SizedBox(width: 290, child: stages),
                              const SizedBox(width: 14),
                              Expanded(child: log),
                            ],
                          );
                        },
                      ),
                    ),
                  ],
                ),
              ),
            ),
            HsFooter(
              leading: HsStatusLine(_clock(state), icon: LucideIcons.clock),
              actions: [
                HsButton.quiet(
                  label: 'Cancel build',
                  onPressed: () => context.read<BuilderBloc>().add(const CancelRequested()),
                ),
              ],
            ),
          ],
        );
      },
    );
  }

  Widget _progressCard(BuildRunning state, int stage, {required bool compact}) {
    final percent = state.fraction == null ? null : (state.fraction! * 100).clamp(0.0, 100.0);
    final working = state.fraction == null || state.fraction == 0;
    final detail = state.changed > 0
        ? '${state.compiledFiles} of ${state.changed} changed files compiled'
        : state.totalFiles != null
            ? '${state.totalFiles} files in this build'
            : null;
    return HsCard(
      title: 'Build progress',
      subtitle: detail,
      fills: true,
      child: compact
          ? Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              mainAxisSize: MainAxisSize.min,
              children: [
                SizedBox(
                  height: 14,
                  child: Row(
                    children: [
                      Expanded(child: ProgressBar(value: working ? null : percent, strokeWidth: 4)),
                      const SizedBox(width: 8),
                      Text(percent == null ? '0%' : '${percent.toStringAsFixed(0)}%',
                          style: const TextStyle(fontSize: 10, color: HsColors.inkSoft)),
                    ],
                  ),
                ),
                const SizedBox(height: 4),
                Text(state.stageText,
                    maxLines: 1,
                    overflow: TextOverflow.ellipsis,
                    style: const TextStyle(fontSize: 10.5, color: HsColors.inkSoft)),
                const SizedBox(height: 3),
                for (var i = 0; i < 4; i++)
                  SizedBox(
                    height: 18,
                    child: Row(
                      children: [
                        _compactDot(i, stage),
                        const SizedBox(width: 7),
                        Text(
                          const [
                            'Read game files',
                            'Translate to PC code',
                            'Compile changed files',
                            'Assemble game folder'
                          ][i],
                          maxLines: 1,
                          overflow: TextOverflow.ellipsis,
                          style: TextStyle(
                            fontSize: 10.5,
                            color: i <= stage ? HsColors.ink : HsColors.inkFaint,
                            fontWeight: i == stage ? FontWeight.w600 : FontWeight.normal,
                          ),
                        ),
                      ],
                    ),
                  ),
              ],
            )
          : Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Row(
                  children: [
                    Expanded(child: ProgressBar(value: working ? null : percent)),
                    const SizedBox(width: 10),
                    Text(percent == null ? '0%' : '${percent.toStringAsFixed(0)}%',
                        style: const TextStyle(fontSize: 11, color: HsColors.inkSoft)),
                  ],
                ),
                const SizedBox(height: 18),
                Expanded(
                  child: HsStageTrack(
                    stages: const [
                      HsStage('Read game files'),
                      HsStage('Translate to PC code'),
                      HsStage('Compile changed files'),
                      HsStage('Assemble game folder'),
                    ],
                    current: stage,
                  ),
                ),
                HsStatusLine(state.stageText, icon: LucideIcons.refreshCw),
              ],
            ),
    );
  }

  Widget _compactDot(int index, int current) {
    if (index < current) {
      return const Icon(LucideIcons.check, size: 11, color: HsColors.go);
    }
    return Container(
      width: 9,
      height: 9,
      decoration: BoxDecoration(
        shape: BoxShape.circle,
        color: index == current ? HsColors.brand : Colors.transparent,
        border: Border.all(color: index <= current ? HsColors.brandHover : HsColors.quietLine),
      ),
    );
  }

  Widget _logCard(BuildRunning state) {
    return HsCard(
      title: 'Build log',
      subtitle: 'Live output from the build process',
      fills: true,
      padding: const EdgeInsets.fromLTRB(16, 16, 12, 12),
      child: HsLogView(state.log, expand: true),
    );
  }
}
