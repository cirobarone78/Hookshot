// Build completion and failure screens.
import 'package:fluent_ui/fluent_ui.dart';
import 'package:flutter_bloc/flutter_bloc.dart';
import 'package:lucide_icons_flutter/lucide_icons.dart';

import '../blocs/builder_bloc.dart';
import '../navigation.dart';
import '../play.dart';
import '../theme.dart';
import 'widgets.dart';

class ReadyPage extends StatefulWidget {
  const ReadyPage({super.key});
  @override
  State<ReadyPage> createState() => _ReadyPageState();
}

class _ReadyPageState extends State<ReadyPage> {
  bool _warned = false;

  @override
  Widget build(BuildContext context) {
    return BlocBuilder<BuilderBloc, BuilderState>(
      builder: (context, state) {
        if (state is! BuildDone) return const SizedBox.shrink();
        if (state.damagedCount > 0 && !_warned) {
          _warned = true;
          WidgetsBinding.instance.addPostFrameCallback((_) {
            if (!mounted) return;
            hsWarning(
              context,
              'Damaged game files found',
              '${state.damagedCount} damaged game file(s) were found during the build. Available files were replaced with stand-ins, so some textures may differ from the original dump.\n\nDump the game again for the original files. The list is in hookshot_damaged_files.txt beside the game.',
            );
          });
        }
        return Column(
          children: [
            const HsHeader(step: 2),
            Expanded(
              child: HsPage(
                child: Center(
                  child: ConstrainedBox(
                    constraints: const BoxConstraints(maxWidth: 760),
                    child: HsCard(
                      padding: const EdgeInsets.all(24),
                      child: Column(
                        crossAxisAlignment: CrossAxisAlignment.start,
                        mainAxisSize: MainAxisSize.min,
                        children: [
                          Row(
                            children: [
                              HsPopIn(
                                child: Container(
                                  width: 42,
                                  height: 42,
                                  decoration: BoxDecoration(
                                    color: HsColors.go.withValues(alpha: 0.14),
                                    borderRadius: BorderRadius.circular(12),
                                  ),
                                  child: const Icon(LucideIcons.circleCheck, color: HsColors.go),
                                ),
                              ),
                              const SizedBox(width: 14),
                              const Expanded(
                                child: Column(
                                  crossAxisAlignment: CrossAxisAlignment.start,
                                  children: [
                                    Text('Your game is ready',
                                        style:
                                            TextStyle(fontSize: 22, fontWeight: FontWeight.bold, color: HsColors.ink)),
                                    SizedBox(height: 3),
                                    Text('The build completed successfully.',
                                        style: TextStyle(fontSize: 12.5, color: HsColors.inkSoft)),
                                  ],
                                ),
                              ),
                            ],
                          ),
                          const SizedBox(height: 20),
                          const Divider(),
                          const SizedBox(height: 16),
                          const Text('GAME FOLDER',
                              style: TextStyle(
                                  fontSize: 10.5,
                                  fontWeight: FontWeight.bold,
                                  letterSpacing: 0.8,
                                  color: HsColors.inkFaint)),
                          const SizedBox(height: 7),
                          SelectableText(state.folder,
                              style: const TextStyle(
                                  fontSize: 12.5, color: HsColors.inkSoft, fontFamilyFallback: hsMonoFamilies)),
                          const SizedBox(height: 12),
                          HsStatusLine(state.text, icon: LucideIcons.clock),
                          if (state.shadersLater) ...[
                            const SizedBox(height: 14),
                            const HsBanner(
                              kind: HsBannerKind.info,
                              title: 'Shaders will prepare on first launch',
                              message: 'The first start may take a few minutes while the game prepares them.',
                            ),
                          ],
                          if (state.damagedCount > 0) ...[
                            const SizedBox(height: 14),
                            HsBanner(
                              kind: HsBannerKind.warning,
                              title: '${state.damagedCount} damaged game file(s) found',
                              message:
                                  'Available stand-ins were used, so some textures may differ. See hookshot_damaged_files.txt in the game folder.',
                            ),
                          ],
                        ],
                      ),
                    ),
                  ),
                ),
              ),
            ),
            HsFooter(
              leading: const HsStatusLine('Ready to play', icon: LucideIcons.circleCheck, color: HsColors.go),
              actions: [
                HsButton.quiet(label: 'Open folder', onPressed: () => openFolder(state.folder)),
                HsButton.go(
                  label: 'Play',
                  icon: const Icon(LucideIcons.play, size: 14),
                  onPressed: () => openGameLauncher(state.folder),
                ),
              ],
            ),
          ],
        );
      },
    );
  }
}

class ProblemPage extends StatelessWidget {
  const ProblemPage({super.key});

  @override
  Widget build(BuildContext context) {
    return BlocBuilder<BuilderBloc, BuilderState>(
      builder: (context, state) {
        if (state is! BuildFailed) return const SizedBox.shrink();
        final damagedLines = state.log.where((line) => line.contains('.zs')).take(8).toList();
        return Column(
          children: [
            const HsHeader(step: 1),
            Expanded(
              child: HsPage(
                child: Center(
                  child: ConstrainedBox(
                    constraints: const BoxConstraints(maxWidth: 720),
                    child: HsCard(
                      padding: const EdgeInsets.all(24),
                      child: Column(
                        mainAxisSize: MainAxisSize.min,
                        crossAxisAlignment: CrossAxisAlignment.start,
                        children: [
                          Row(
                            children: [
                              HsPopIn(
                                child: Container(
                                  width: 42,
                                  height: 42,
                                  decoration: BoxDecoration(
                                    color: (state.cancelled ? HsColors.go : HsColors.bad).withValues(alpha: 0.14),
                                    borderRadius: BorderRadius.circular(12),
                                  ),
                                  child: Icon(state.cancelled ? LucideIcons.circleCheck : LucideIcons.circleAlert,
                                      color: state.cancelled ? HsColors.go : HsColors.bad),
                                ),
                              ),
                              const SizedBox(width: 14),
                              Expanded(
                                child: Column(
                                  crossAxisAlignment: CrossAxisAlignment.start,
                                  children: [
                                    Text(state.cancelled ? 'Build cancelled' : 'The build stopped',
                                        style: const TextStyle(
                                            fontSize: 22, fontWeight: FontWeight.bold, color: HsColors.ink)),
                                    const SizedBox(height: 3),
                                    Text(
                                        state.cancelled
                                            ? 'Nothing was replaced. Your options are kept for another try.'
                                            : 'Review the error below, then return to the form to try again.',
                                        style: const TextStyle(fontSize: 12.5, color: HsColors.inkSoft)),
                                  ],
                                ),
                              ),
                            ],
                          ),
                          const SizedBox(height: 20),
                          if (!state.cancelled)
                            HsBanner(kind: HsBannerKind.warning, title: 'Error details', message: state.error)
                          else
                            const HsStatusLine('No files were changed.', icon: LucideIcons.circleStop),
                          if (state.damagedCount > 0) ...[
                            const SizedBox(height: 14),
                            HsBanner(
                              kind: HsBannerKind.warning,
                              title: '${state.damagedCount} damaged game file(s) found',
                              message:
                                  'The build did not complete. Check hookshot_damaged_files.txt beside the game, then select a complete dump and try again.',
                            ),
                            if (damagedLines.isNotEmpty) ...[
                              const SizedBox(height: 10),
                              SelectableText(
                                damagedLines.join('\n'),
                                style: const TextStyle(
                                    fontSize: 11, color: HsColors.inkSoft, fontFamilyFallback: hsMonoFamilies),
                              ),
                            ],
                          ],
                        ],
                      ),
                    ),
                  ),
                ),
              ),
            ),
            HsFooter(
              leading: const HsStatusLine('Your selected options have been kept.'),
              actions: [
                HsButton.primary(
                  label: 'Back to form',
                  onPressed: () => context.read<BuilderBloc>().add(const BackToForm()),
                ),
              ],
            ),
          ],
        );
      },
    );
  }
}
