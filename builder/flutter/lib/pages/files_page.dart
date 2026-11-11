// The Builder's main form: game files, destination and build options.
import 'dart:async';

import 'package:file_selector/file_selector.dart';
import 'package:fluent_ui/fluent_ui.dart';
import 'package:flutter_bloc/flutter_bloc.dart';
import 'package:lucide_icons_flutter/lucide_icons.dart';

import '../blocs/builder_bloc.dart';
import '../blocs/update_bloc.dart';
import '../config.dart' as cfg;
import '../navigation.dart';
import '../theme.dart';
import 'widgets.dart';

class FilesPage extends StatelessWidget {
  const FilesPage({super.key});

  @override
  Widget build(BuildContext context) {
    return BlocBuilder<BuilderBloc, BuilderState>(
      builder: (context, state) {
        if (state is! BuilderForm) return const SizedBox.shrink();
        final bloc = context.read<BuilderBloc>();
        return Column(
          children: [
            HsHeader(step: 0, chip: bloc.toolsTag.isEmpty ? null : 'tools ${bloc.toolsTag}'),
            Expanded(
              child: HsPage(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    const Text('Build your game',
                        style: TextStyle(fontSize: 25, fontWeight: FontWeight.bold, color: HsColors.ink)),
                    const SizedBox(height: 5),
                    const HsNote('Choose your game files, install location and build options.'),
                    if (state.gameReady && state.mode != 'up-to-date') ...[
                      const SizedBox(height: 18),
                      HsBanner(
                        kind: HsBannerKind.success,
                        title: 'A built game is already here',
                        message: state.out,
                        action: HsButton.quiet(
                          label: 'Play',
                          onPressed: () => openGameLauncher(state.out),
                        ),
                      ),
                    ],
                    const SizedBox(height: 20),
                    HsCard(
                      title: 'Game files',
                      subtitle: 'Use a game package or point to an extracted dump.',
                      child: Column(
                        crossAxisAlignment: CrossAxisAlignment.start,
                        children: [
                          Row(
                            children: [
                              Expanded(
                                child: _KindChoice(
                                  icon: LucideIcons.file,
                                  title: '.nup package',
                                  subtitle: 'A single game file',
                                  selected: state.kind == 'nup',
                                  onTap: () => bloc.add(const FormChanged(kind: 'nup')),
                                ),
                              ),
                              const SizedBox(width: 10),
                              Expanded(
                                child: _KindChoice(
                                  icon: LucideIcons.folderOpen,
                                  title: 'Extracted folders',
                                  subtitle: 'romfs and exefs',
                                  selected: state.kind == 'folders',
                                  onTap: () => bloc.add(const FormChanged(kind: 'folders')),
                                ),
                              ),
                            ],
                          ),
                          const SizedBox(height: 14),
                          if (state.kind == 'nup')
                            _PathRow(
                              label: 'Package',
                              value: state.nup,
                              onChanged: (v) => bloc.add(FormChanged(nup: v)),
                              onSubmitted: (v) => bloc.add(FormChanged(nup: v)),
                              onBrowse: () => _pickNup(context, bloc),
                              placeholder: 'Select a .nup game package',
                            )
                          else
                            LayoutBuilder(
                              builder: (context, constraints) {
                                final vertical = constraints.maxWidth < 650;
                                final romfs = _PathRow(
                                  label: 'romfs folder',
                                  value: state.romfs,
                                  onChanged: (v) => bloc.add(FormChanged(romfs: v)),
                                  onSubmitted: (v) => bloc.add(FormChanged(romfs: v)),
                                  onBrowse: () => _pickDir(context, bloc, state.romfs, (v) => FormChanged(romfs: v)),
                                  placeholder: 'Select romfs',
                                );
                                final exefs = _PathRow(
                                  label: 'exefs folder',
                                  value: state.exefs,
                                  onChanged: (v) => bloc.add(FormChanged(exefs: v)),
                                  onSubmitted: (v) {
                                    bloc.add(FormChanged(exefs: v));
                                    bloc.add(const SourcePicked());
                                  },
                                  onBrowse: () =>
                                      _pickDir(context, bloc, state.exefs, (v) => FormChanged(exefs: v), picked: true),
                                  placeholder: 'Select exefs',
                                );
                                if (vertical) {
                                  return Column(
                                    children: [romfs, const SizedBox(height: 12), exefs],
                                  );
                                }
                                return Row(
                                  crossAxisAlignment: CrossAxisAlignment.start,
                                  children: [
                                    Expanded(child: romfs),
                                    const SizedBox(width: 12),
                                    Expanded(child: exefs),
                                  ],
                                );
                              },
                            ),
                          if (state.checkText.isNotEmpty) ...[
                            const SizedBox(height: 12),
                            HsStatusLine(state.checkText),
                          ],
                        ],
                      ),
                    ),
                    const SizedBox(height: 12),
                    HsCard(
                      title: 'Install location',
                      subtitle: 'Choose where the finished game folder should live.',
                      child: Column(
                        crossAxisAlignment: CrossAxisAlignment.start,
                        children: [
                          _PathRow(
                            value: state.out,
                            onChanged: (v) => bloc.add(FormChanged(out: v)),
                            onSubmitted: (v) => bloc.add(FormChanged(out: v)),
                            onBrowse: () => _pickOutput(context, bloc, state.out),
                            button: 'Choose folder',
                            placeholder: 'Select an install folder',
                          ),
                          const SizedBox(height: 14),
                          _SpaceMeter(state: state),
                        ],
                      ),
                    ),
                    const SizedBox(height: 12),
                    HsCard(
                      title: 'Build options',
                      subtitle: 'These choices are saved for your next build.',
                      child: Column(
                        children: [
                          Row(
                            crossAxisAlignment: CrossAxisAlignment.start,
                            children: [
                              SizedBox(
                                width: 190,
                                child: HsField(
                                  label: 'Game language',
                                  child: _LanguageDropdown(state: state),
                                ),
                              ),
                              const SizedBox(width: 16),
                              SizedBox(
                                width: 190,
                                child: HsField(
                                  label: 'Update track',
                                  child: _TrackDropdown(state: state),
                                ),
                              ),
                            ],
                          ),
                          const SizedBox(height: 14),
                          const Divider(),
                          const SizedBox(height: 8),
                          _OptionRow(
                            checked: state.prepare,
                            onChanged: (v) => bloc.add(FormChanged(prepare: v)),
                            title: 'Prepare shaders before first launch',
                            detail:
                                'Takes a few minutes at the end of the build. If skipped, the game prepares them on its first start.',
                          ),
                          const SizedBox(height: 8),
                          _OptionRow(
                            checked: state.dlss,
                            onChanged: (v) => _setDlss(context, bloc, v),
                            title: 'NVIDIA DLSS',
                            detail:
                                "For NVIDIA RTX graphics cards. NVIDIA's SDK is downloaded to this PC under NVIDIA's license; never share a game folder built with it.",
                          ),
                        ],
                      ),
                    ),
                    if (state.statusText.isNotEmpty) ...[
                      const SizedBox(height: 12),
                      HsBanner(
                        kind: state.mode == 'up-to-date' ? HsBannerKind.success : HsBannerKind.info,
                        title: switch (state.mode) {
                          'update-game' => 'Game update available',
                          'update-builder' => 'Builder update available',
                          'up-to-date' => 'You are up to date',
                          _ => 'Update status',
                        },
                        message: state.statusText,
                      ),
                    ],
                  ],
                ),
              ),
            ),
            HsFooter(
              leading: Text(
                state.aboutLabel.isEmpty ? 'Ready when you are' : 'Typical first build · ${state.aboutLabel}',
                maxLines: 1,
                overflow: TextOverflow.ellipsis,
                style: const TextStyle(fontSize: 12, color: HsColors.inkFaint),
              ),
              actions: [
                if (state.gameReady && state.mode != 'up-to-date')
                  HsButton.quiet(
                    label: 'Play existing game',
                    onPressed: () => openGameLauncher(state.out),
                  ),
                if (state.mode == 'up-to-date')
                  HsButton.go(
                    label: state.buttonLabel,
                    icon: const Icon(LucideIcons.play, size: 14),
                    onPressed: () => _onAction(context, bloc, state),
                  )
                else
                  HsButton.primary(
                    label: state.buttonLabel,
                    onPressed: () => _onAction(context, bloc, state),
                  ),
              ],
            ),
          ],
        );
      },
    );
  }

  Future<void> _pickNup(BuildContext context, BuilderBloc bloc) async {
    final file = await openFile(
      acceptedTypeGroups: [
        const XTypeGroup(label: 'Switch 2 game package', extensions: ['nup'])
      ],
    );
    if (file != null) {
      bloc.add(FormChanged(nup: file.path));
      bloc.add(const SourcePicked());
      bloc.add(const CheckRequested());
    }
  }

  Future<void> _pickDir(
    BuildContext context,
    BuilderBloc bloc,
    String initial,
    FormChanged Function(String) change, {
    bool picked = false,
  }) async {
    final dir = await getDirectoryPath(initialDirectory: initial.isEmpty ? null : initial);
    if (dir != null) {
      bloc.add(change(dir));
      if (picked) bloc.add(const SourcePicked());
      bloc.add(const CheckRequested());
    }
  }

  Future<void> _pickOutput(BuildContext context, BuilderBloc bloc, String initial) async {
    final dir = await getDirectoryPath(initialDirectory: initial.isEmpty ? null : initial);
    if (dir != null) bloc.add(FormChanged(out: dir));
  }

  Future<void> _setDlss(BuildContext context, BuilderBloc bloc, bool value) async {
    if (!value) {
      bloc.add(const DlssSet(false));
      return;
    }
    final accepted = await showDialog<bool>(
      context: context,
      builder: (context) => ContentDialog(
        title: const Text('NVIDIA DLSS license'),
        content: const SizedBox(
          width: 520,
          child: SingleChildScrollView(child: SelectableText(cfg.dlssLicense)),
        ),
        actions: [
          Button(child: const Text('Decline'), onPressed: () => Navigator.pop(context, false)),
          FilledButton(child: const Text('Accept'), onPressed: () => Navigator.pop(context, true)),
        ],
      ),
    );
    if (accepted == true) bloc.add(const DlssSet(true));
  }

  Future<void> _onAction(BuildContext context, BuilderBloc bloc, BuilderForm state) async {
    switch (state.mode) {
      case 'up-to-date':
        openGameLauncher(state.out);
      case 'update-game':
        context.read<UpdateBloc>().add(
            BeginUpdate(folder: state.out, toolsTag: bloc.toolsTag, latest: state.latest, switching: bloc.switching));
      case 'update-builder':
        context
            .read<UpdateBloc>()
            .add(BeginUpdate(folder: '', toolsTag: bloc.toolsTag, latest: state.latest, switching: bloc.switching));
      default:
        if (state.kind == 'nup' && state.nup.trim().isEmpty) {
          hsError(context, 'Game files needed', "Choose your game's .nup file.");
          return;
        }
        if (state.kind != 'nup' && (state.romfs.trim().isEmpty || state.exefs.trim().isEmpty)) {
          hsError(context, 'Game files needed', "Choose your game's romfs and exefs folders.");
          return;
        }
        if (state.out.trim().isEmpty) {
          hsError(context, 'Install location needed', 'Choose where to save the game.');
          return;
        }
        bloc.add(const BuildRequested());
    }
  }
}

class _KindChoice extends StatelessWidget {
  final IconData icon;
  final String title;
  final String subtitle;
  final bool selected;
  final VoidCallback onTap;
  const _KindChoice({
    required this.icon,
    required this.title,
    required this.subtitle,
    required this.selected,
    required this.onTap,
  });

  @override
  Widget build(BuildContext context) {
    final border = selected ? HsColors.brand : HsColors.glassLine;
    return GestureDetector(
      onTap: onTap,
      behavior: HitTestBehavior.opaque,
      child: AnimatedContainer(
        duration: const Duration(milliseconds: 120),
        padding: const EdgeInsets.symmetric(horizontal: 13, vertical: 10),
        decoration: BoxDecoration(
          color: selected ? HsColors.brand.withValues(alpha: 0.13) : HsColors.page.withValues(alpha: 0.35),
          borderRadius: BorderRadius.circular(8),
          border: Border.all(color: border, width: selected ? 1.5 : 1),
        ),
        child: Row(
          children: [
            Icon(icon, size: 17, color: selected ? HsColors.brandHover : HsColors.inkFaint),
            const SizedBox(width: 10),
            Expanded(
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Text(title,
                      style: TextStyle(
                          fontSize: 12.5,
                          fontWeight: FontWeight.w600,
                          color: selected ? HsColors.ink : HsColors.inkSoft)),
                  const SizedBox(height: 2),
                  Text(subtitle, style: const TextStyle(fontSize: 11, color: HsColors.inkFaint)),
                ],
              ),
            ),
            if (selected) const Icon(LucideIcons.circleCheck, size: 14, color: HsColors.brandHover),
          ],
        ),
      ),
    );
  }
}

class _PathRow extends StatefulWidget {
  final String? label;
  final String value;
  final ValueChanged<String> onChanged;
  final ValueChanged<String> onSubmitted;
  final VoidCallback onBrowse;
  final String button;
  final String placeholder;
  const _PathRow({
    this.label,
    required this.value,
    required this.onChanged,
    required this.onSubmitted,
    required this.onBrowse,
    this.button = 'Browse…',
    this.placeholder = '',
  });

  @override
  State<_PathRow> createState() => _PathRowState();
}

class _PathRowState extends State<_PathRow> {
  late final TextEditingController _controller = TextEditingController(text: widget.value);
  Timer? _editTimer;

  @override
  void didUpdateWidget(covariant _PathRow oldWidget) {
    super.didUpdateWidget(oldWidget);
    if (widget.value != _controller.text) {
      _editTimer?.cancel();
      _controller.value = TextEditingValue(
        text: widget.value,
        selection: TextSelection.collapsed(offset: widget.value.length),
      );
    }
  }

  @override
  void dispose() {
    _editTimer?.cancel();
    _controller.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    return Row(
      children: [
        if (widget.label != null) ...[
          SizedBox(
            width: 92,
            child: Text(widget.label!,
                style: const TextStyle(fontSize: 11.5, fontWeight: FontWeight.w600, color: HsColors.inkSoft)),
          ),
          const SizedBox(width: 10),
        ],
        Expanded(
          child: TextBox(
            controller: _controller,
            placeholder: widget.placeholder,
            placeholderStyle: const TextStyle(color: HsColors.inkFaint, fontWeight: FontWeight.w300),
            onChanged: (value) {
              _editTimer?.cancel();
              _editTimer = Timer(const Duration(milliseconds: 350), () {
                if (mounted) widget.onChanged(value);
              });
            },
            onSubmitted: (value) {
              _editTimer?.cancel();
              widget.onSubmitted(value);
            },
            style: const TextStyle(fontSize: 12, fontFamilyFallback: hsMonoFamilies, color: HsColors.ink),
          ),
        ),
        const SizedBox(width: 9),
        HsButton.quiet(label: widget.button, onPressed: widget.onBrowse),
      ],
    );
  }
}

class _LanguageDropdown extends StatelessWidget {
  final BuilderForm state;
  const _LanguageDropdown({required this.state});
  @override
  Widget build(BuildContext context) {
    return ComboBox<String>(
      isExpanded: true,
      value: state.language,
      items: [
        for (final l in cfg.languages)
          ComboBoxItem(value: l.$2, child: Text(l.$2, style: const TextStyle(fontSize: 12)))
      ],
      onChanged: (v) {
        if (v != null) context.read<BuilderBloc>().add(FormChanged(language: v));
      },
    );
  }
}

class _TrackDropdown extends StatelessWidget {
  final BuilderForm state;
  const _TrackDropdown({required this.state});
  @override
  Widget build(BuildContext context) {
    return ComboBox<String>(
      isExpanded: true,
      value: state.track,
      items: [
        for (final e in cfg.trackNames.entries)
          ComboBoxItem(value: e.key, child: Text(e.value, style: const TextStyle(fontSize: 12)))
      ],
      onChanged: (v) {
        if (v != null) {
          context.read<BuilderBloc>().add(FormChanged(track: v));
          context.read<BuilderBloc>().add(const LatestRefreshRequested());
        }
      },
    );
  }
}

class _OptionRow extends StatelessWidget {
  final bool checked;
  final ValueChanged<bool> onChanged;
  final String title;
  final String detail;
  const _OptionRow({required this.checked, required this.onChanged, required this.title, required this.detail});

  @override
  Widget build(BuildContext context) {
    return Row(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Padding(
          padding: const EdgeInsets.only(top: 1),
          child: Checkbox(checked: checked, onChanged: (value) => onChanged(value ?? false)),
        ),
        const SizedBox(width: 10),
        Expanded(
          child: GestureDetector(
            behavior: HitTestBehavior.opaque,
            onTap: () => onChanged(!checked),
            child: Padding(
              padding: const EdgeInsets.only(top: 2),
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Text(title, style: const TextStyle(fontSize: 12.5, fontWeight: FontWeight.w600, color: HsColors.ink)),
                  const SizedBox(height: 3),
                  Text(detail, style: const TextStyle(fontSize: 11.5, height: 1.35, color: HsColors.inkFaint)),
                ],
              ),
            ),
          ),
        ),
      ],
    );
  }
}

class _SpaceMeter extends StatelessWidget {
  final BuilderForm state;
  const _SpaceMeter({required this.state});

  @override
  Widget build(BuildContext context) {
    final gb = state.spaceGb;
    if (gb == null) {
      return const HsStatusLine('Available disk space could not be checked for this location.');
    }
    final enough = gb >= 45;
    final color = enough ? HsColors.go : HsColors.bad;
    return Row(
      children: [
        const Icon(LucideIcons.hardDrive, size: 14, color: HsColors.inkFaint),
        const SizedBox(width: 8),
        Expanded(
          child: ProgressBar(
            value: (gb / 45).clamp(0.0, 1.0) * 100,
            activeColor: color,
            backgroundColor: HsColors.track,
            strokeWidth: 4,
          ),
        ),
        const SizedBox(width: 12),
        Text(
          '${gb.toStringAsFixed(0)} GB free · 45 GB recommended',
          style: TextStyle(fontSize: 11.5, color: enough ? HsColors.inkSoft : color),
        ),
      ],
    );
  }
}
