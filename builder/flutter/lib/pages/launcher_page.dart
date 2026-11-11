// Game-folder launcher (--launch <folder>): update, play or open its folder.
import 'dart:io';

import 'package:file_selector/file_selector.dart';
import 'package:fluent_ui/fluent_ui.dart';
import 'package:flutter_bloc/flutter_bloc.dart';
import 'package:lucide_icons_flutter/lucide_icons.dart';

import '../blocs/launcher_bloc.dart';
import '../blocs/update_bloc.dart';
import '../config.dart' as cfg;
import '../gamescope.dart';
import '../play.dart';
import '../profiles.dart';
import '../theme.dart';
import '../updater/manifest.dart' as upd;
import '../updater/version_policy.dart' as policy;
import 'gamescope_dialog.dart';
import 'widgets.dart';

class LauncherPage extends StatelessWidget {
  final String toolsTag;
  final VoidCallback? onBack;
  const LauncherPage({super.key, required this.toolsTag, this.onBack});

  @override
  Widget build(BuildContext context) {
    return BlocBuilder<LauncherBloc, LauncherState>(
      builder: (context, state) {
        final version = state is LauncherReady ? state.game : null;
        final folder = switch (state) {
          LauncherLoading(:final folder) => folder,
          LauncherReady(:final folder) => folder,
        };
        return Column(
          children: [
            HsHeader(chip: version ?? 'Game launcher'),
            Expanded(
              child: HsPage(
                child: Align(
                  alignment: Alignment.topCenter,
                  child: ConstrainedBox(
                    constraints: const BoxConstraints(maxWidth: 700),
                    child: switch (state) {
                      LauncherLoading() => const HsCard(
                          title: 'Checking your game',
                          subtitle: 'Looking up its version and checking for updates.',
                          child: Padding(
                            padding: EdgeInsets.symmetric(vertical: 26),
                            child: Center(child: ProgressRing()),
                          ),
                        ),
                      LauncherReady() => _LauncherDetails(state: state),
                    },
                  ),
                ),
              ),
            ),
            HsFooter(
              leading: Text(
                state is LauncherReady ? state.status : 'Checking for updates…',
                maxLines: 1,
                overflow: TextOverflow.ellipsis,
                style: const TextStyle(fontSize: 12, color: HsColors.inkSoft),
              ),
              actions: [
                if (onBack != null) HsButton.quiet(label: 'Back', onPressed: onBack),
                HsButton.quiet(label: 'Open folder', onPressed: () => openFolder(folder)),
                if (state is LauncherReady && state.kept)
                  HsButton.quiet(
                    label: 'Rebuild',
                    icon: const Icon(LucideIcons.refreshCw, size: 14),
                    onPressed: () => _rebuild(context, state),
                  ),
                if (state is LauncherReady && state.showUpdate)
                  HsButton.primary(
                    label: 'Switch version',
                    onPressed: () => _switchVersion(context, state),
                  ),
                HsButton.go(
                  label: 'Play',
                  icon: const Icon(LucideIcons.play, size: 14),
                  onPressed: state is LauncherReady && upd.gameReady(state.folder)
                      ? () => playAndClose(context, state.folder, profile: state.profileId, gamescope: state.gamescope)
                      : null,
                ),
              ],
            ),
          ],
        );
      },
    );
  }

  Future<void> _rebuild(BuildContext context, LauncherReady state) async {
    final yes = await showDialog<bool>(
      context: context,
      builder: (context) => ContentDialog(
        title: const Text('Rebuild this game?'),
        content: const Text(
          'Hookshot rebuilds the game from the files this folder kept. Your saves and settings are kept. '
          'This is the repair to use when the game or its shaders will not start.',
        ),
        actions: [
          Button(child: const Text('Cancel'), onPressed: () => Navigator.pop(context, false)),
          FilledButton(child: const Text('Rebuild'), onPressed: () => Navigator.pop(context, true)),
        ],
      ),
    );
    if (yes == true && context.mounted) {
      context.read<UpdateBloc>().add(RebuildFolder(state.folder));
    }
  }

  Future<void> _switchVersion(BuildContext context, LauncherReady state) async {
    final selected = state.selectedVersion;
    if (selected == null || selected == state.game || !state.showUpdate) return;
    final proceed = await showDialog<bool>(
      context: context,
      builder: (context) => ContentDialog(
        title: const Text('Switch Hookshot version?'),
        content: Text(
          'Hookshot will rebuild this game folder with $selected. A local backup of the saves and settings will be made first.',
        ),
        actions: [
          Button(child: const Text('Cancel'), onPressed: () => Navigator.pop(context, false)),
          FilledButton(child: const Text('Back up and switch'), onPressed: () => Navigator.pop(context, true)),
        ],
      ),
    );
    if (proceed != true || !context.mounted) return;
    try {
      policy.backupBeforeSwitch(state.folder);
      policy.setPinnedVersion(state.folder, state.pinSelected ? selected : null);
    } catch (error) {
      hsError(context, 'Could not prepare the version switch', '$error');
      return;
    }
    context.read<UpdateBloc>().add(BeginUpdate(
          folder: state.folder,
          toolsTag: toolsTag,
          latest: state.latest,
          tag: selected,
          switching: true,
        ));
  }
}

class _LauncherDetails extends StatelessWidget {
  final LauncherReady state;
  const _LauncherDetails({required this.state});

  @override
  Widget build(BuildContext context) {
    return HsCard(
      padding: const EdgeInsets.all(24),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        mainAxisSize: MainAxisSize.min,
        children: [
          Row(
            children: [
              Container(
                width: 42,
                height: 42,
                decoration: BoxDecoration(
                  color: HsColors.brand.withValues(alpha: 0.14),
                  borderRadius: BorderRadius.circular(12),
                ),
                child: const Icon(LucideIcons.gamepad2, color: HsColors.brandHover),
              ),
              const SizedBox(width: 14),
              const Expanded(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text('Your game', style: TextStyle(fontSize: 22, fontWeight: FontWeight.bold, color: HsColors.ink)),
                    SizedBox(height: 3),
                    Text('Launch the installed game or update it first.',
                        style: TextStyle(fontSize: 12.5, color: HsColors.inkSoft)),
                  ],
                ),
              ),
            ],
          ),
          const SizedBox(height: 18),
          const Divider(),
          const SizedBox(height: 14),
          const Text('GAME FOLDER',
              style:
                  TextStyle(fontSize: 10.5, fontWeight: FontWeight.bold, letterSpacing: 0.8, color: HsColors.inkFaint)),
          const SizedBox(height: 7),
          SelectableText(state.folder,
              style: const TextStyle(fontSize: 12.5, color: HsColors.inkSoft, fontFamilyFallback: hsMonoFamilies)),
          const SizedBox(height: 18),
          if (state.profileError != null) ...[
            HsBanner(kind: HsBannerKind.warning, title: 'Profiles could not be read', message: state.profileError),
            const SizedBox(height: 16),
          ] else if (state.profiles != null) ...[
            _ProfileField(state: state, enabled: state.profiles!.supported),
            if (!state.profiles!.supported) ...[
              const SizedBox(height: 10),
              const HsBanner(
                kind: HsBannerKind.warning,
                title: 'Rebuild to use profiles',
                message:
                    'This folder was built before profiles. Rebuild it below to keep separate saves for each player.',
              ),
            ],
            const SizedBox(height: 18),
          ],
          HsField(
            label: 'Game version',
            child: ComboBox<String>(
              isExpanded: true,
              value: state.selectedVersion,
              placeholder: const Text('Choose a release'),
              items: [
                for (final version in state.versions)
                  ComboBoxItem(value: version, child: Text(version, style: const TextStyle(fontSize: 12)))
              ],
              onChanged: (version) {
                if (version != null) {
                  context.read<LauncherBloc>().add(LauncherSelectionChanged(version: version));
                }
              },
            ),
          ),
          const SizedBox(height: 18),
          const Text('LAUNCH OPTIONS',
              style:
                  TextStyle(fontSize: 10.5, fontWeight: FontWeight.bold, letterSpacing: 0.8, color: HsColors.inkFaint)),
          const SizedBox(height: 8),
          Row(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Checkbox(
                checked: state.pinSelected,
                onChanged: (value) =>
                    context.read<LauncherBloc>().add(LauncherSelectionChanged(pinSelected: value ?? false)),
              ),
              const SizedBox(width: 8),
              const Expanded(
                child: Padding(
                  padding: EdgeInsets.only(top: 3),
                  child:
                      Text('Stay on the selected version', style: TextStyle(fontSize: 12.5, color: HsColors.inkSoft)),
                ),
              ),
            ],
          ),
          if (Platform.isLinux)
            Row(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Checkbox(
                  checked: state.gamescope,
                  onChanged: (value) => context.read<LauncherBloc>().add(LauncherGamescopeChanged(value ?? false)),
                ),
                const SizedBox(width: 8),
                Expanded(
                  child: Padding(
                    padding: const EdgeInsets.only(top: 3),
                    child: Column(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                        const Text('Launch the game in gamescope',
                            style: TextStyle(fontSize: 12.5, color: HsColors.inkSoft)),
                        Text(GamescopeSettings.load().summary,
                            style: const TextStyle(fontSize: 11, color: HsColors.inkFaint)),
                      ],
                    ),
                  ),
                ),
                HsButton.quiet(
                  label: 'Options…',
                  onPressed: () async {
                    final settings = await editGamescope(context);
                    if (settings != null && context.mounted) {
                      context.read<LauncherBloc>().add(LauncherGamescopeChanged(settings.enabled));
                    }
                  },
                ),
              ],
            ),
          if (Platform.isLinux || Platform.isWindows) const _CloseAfterLaunchOption(),
          const SizedBox(height: 12),
          const Divider(),
          const SizedBox(height: 10),
          AnimatedSwitcher(
            duration: const Duration(milliseconds: 200),
            switchInCurve: Curves.easeOutCubic,
            switchOutCurve: Curves.easeInCubic,
            child: state.showUpdate
                ? HsBanner(
                    key: const ValueKey('update'),
                    kind: HsBannerKind.warning,
                    title: 'Version switch',
                    message: state.status,
                  )
                : HsStatusLine(state.status, key: ValueKey(state.status), icon: LucideIcons.info),
          ),
        ],
      ),
    );
  }
}

/// Whether the builder window closes once the game started (the old
/// behaviour) or stays open beside it.
class _CloseAfterLaunchOption extends StatefulWidget {
  const _CloseAfterLaunchOption();
  @override
  State<_CloseAfterLaunchOption> createState() => _CloseAfterLaunchOptionState();
}

class _CloseAfterLaunchOptionState extends State<_CloseAfterLaunchOption> {
  bool _close = cfg.loadConfig()['close_after_launch'] != '0';

  @override
  Widget build(BuildContext context) {
    return Row(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Checkbox(
          checked: _close,
          onChanged: (value) {
            setState(() => _close = value ?? false);
            final config = cfg.loadConfig()..['close_after_launch'] = _close ? '1' : '0';
            cfg.saveConfig(config);
          },
        ),
        const SizedBox(width: 8),
        const Expanded(
          child: Padding(
            padding: EdgeInsets.only(top: 3),
            child: Text('Close the builder after the game starts',
                style: TextStyle(fontSize: 12.5, color: HsColors.inkSoft)),
          ),
        ),
      ],
    );
  }
}

/// The launcher's profile, and the actions that keep it: nx2/profiles.py owns the list and the save folders.
class _ProfileField extends StatelessWidget {
  final LauncherReady state;
  final bool enabled;
  const _ProfileField({required this.state, required this.enabled});

  @override
  Widget build(BuildContext context) {
    final profiles = state.profiles!;
    final current = profiles.byId(state.profileId) ?? profiles.list.first;
    return HsField(
      label: 'Profile',
      hint: enabled
          ? '${current.name} keeps its saves in ${profiles.user}'
          : 'Rebuild this folder to keep a save for each player.',
      child: Row(
        children: [
          Expanded(
            child: ComboBox<String>(
              isExpanded: true,
              value: current.id,
              items: [
                for (final profile in profiles.list)
                  ComboBoxItem(
                    value: profile.id,
                    child: Text(profile.isDefault ? '${profile.name} (default)' : profile.name,
                        style: const TextStyle(fontSize: 12)),
                  )
              ],
              onChanged: enabled
                  ? (id) {
                      if (id != null) context.read<LauncherBloc>().add(LauncherProfileChanged(id));
                    }
                  : null,
            ),
          ),
          const SizedBox(width: 8),
          HsButton.quiet(
            label: 'Manage',
            icon: const Icon(LucideIcons.users, size: 14),
            onPressed: enabled ? () => _manage(context) : null,
          ),
        ],
      ),
    );
  }

  Future<void> _manage(BuildContext context) async {
    final current = state.profiles!.byId(state.profileId) ?? state.profiles!.list.first;
    final action = await showDialog<_ProfileAction>(
      context: context,
      builder: (context) => ContentDialog(
        title: const Text('Profiles'),
        content: SizedBox(
          width: 430,
          child: Column(
            mainAxisSize: MainAxisSize.min,
            crossAxisAlignment: CrossAxisAlignment.stretch,
            children: [
              Text('${current.name} is the profile Play starts.',
                  style: const TextStyle(fontSize: 12.5, color: HsColors.inkSoft)),
              const SizedBox(height: 14),
              _action(context, LucideIcons.userPlus, 'New profile', 'A separate user with an empty file select.',
                  _ProfileAction.create),
              _action(context, LucideIcons.pencil, 'Rename profile', 'Change the name shown here, not its saves.',
                  _ProfileAction.rename),
              _action(
                  context,
                  LucideIcons.trash2,
                  'Remove profile',
                  current.isDefault ? 'The default profile cannot be removed.' : 'Its saves move to save-backups.',
                  _ProfileAction.remove,
                  enabled: !current.isDefault),
              _action(context, LucideIcons.download, 'Import save',
                  'Copy a save from an emulator or a folder into this profile.', _ProfileAction.importSave),
              _action(context, LucideIcons.upload, 'Export save', 'Copy this profile\'s save into a new folder.',
                  _ProfileAction.exportSave),
              _action(context, LucideIcons.folderOpen, 'Open save folder', 'Show where this profile keeps its saves.',
                  _ProfileAction.openFolder),
            ],
          ),
        ),
        actions: [Button(child: const Text('Close'), onPressed: () => Navigator.pop(context))],
      ),
    );
    if (action == null || !context.mounted) return;
    final service = ProfilesService();
    switch (action) {
      case _ProfileAction.create:
        final name = await _askName(context, 'New profile');
        if (name == null || !context.mounted) return;
        try {
          final updated = await service.add(state.folder, name);
          if (!context.mounted) return;
          context.read<LauncherBloc>().add(LauncherProfilesReload(select: updated.selected));
        } catch (error) {
          if (context.mounted) hsError(context, 'Could not make the profile', '$error');
        }
      case _ProfileAction.rename:
        final name = await _askName(context, 'Rename ${current.name}', initial: current.name);
        if (name == null || !context.mounted) return;
        try {
          await service.rename(state.folder, current.id, name);
          if (context.mounted) context.read<LauncherBloc>().add(const LauncherProfilesReload());
        } catch (error) {
          if (context.mounted) hsError(context, 'Could not rename the profile', '$error');
        }
      case _ProfileAction.remove:
        final yes = await _confirm(context, 'Remove ${current.name}?',
            'Its saves are moved to save-backups, not deleted. The profile leaves the list.');
        if (yes != true || !context.mounted) return;
        try {
          await service.remove(state.folder, current.id);
          if (context.mounted) context.read<LauncherBloc>().add(const LauncherProfilesReload());
        } catch (error) {
          if (context.mounted) hsError(context, 'Could not remove the profile', '$error');
        }
      case _ProfileAction.importSave:
        await _import(context, service, current);
      case _ProfileAction.exportSave:
        final parent = await getDirectoryPath(initialDirectory: state.folder);
        if (parent == null || !context.mounted) return;
        try {
          final made = await service.export(state.folder, current.id, parent);
          if (context.mounted) {
            await _message(context, 'Save exported', 'Copied ${current.name}\'s save to\n$made');
          }
        } catch (error) {
          if (context.mounted) hsError(context, 'Could not export the save', '$error');
        }
      case _ProfileAction.openFolder:
        final folder = state.profiles!.folderToShow(current.id);
        if (folder == null) {
          if (context.mounted) hsError(context, 'No save folder yet', '${current.name} has not saved anything yet.');
        } else {
          await openFolder(folder);
        }
    }
  }

  Future<void> _import(BuildContext context, ProfilesService service, GameProfile current) async {
    final source = await getDirectoryPath(initialDirectory: state.folder);
    if (source == null || !context.mounted) return;
    try {
      final saves = await service.saves(source);
      if (saves.isEmpty) throw const ProfileException('No Ocarina of Time save was found in that folder.');
      SaveEntry chosen = saves.first;
      if (saves.length > 1 && context.mounted) {
        final picked = await showDialog<SaveEntry>(
          context: context,
          builder: (context) => _SaveChooser(saves: saves),
        );
        if (picked == null) return;
        chosen = picked;
      }
      final result =
          await service.importSave(state.folder, state.profiles!, current.id, source, sourceProfile: chosen.id);
      if (!context.mounted) return;
      context.read<LauncherBloc>().add(const LauncherProfilesReload());
      await _message(context, 'Save imported', 'Imported into ${current.name}.\n\n$result');
    } catch (error) {
      if (context.mounted) hsError(context, 'Could not import the save', '$error');
    }
  }

  Widget _action(BuildContext context, IconData icon, String title, String subtitle, _ProfileAction action,
      {bool enabled = true}) {
    return Padding(
      padding: const EdgeInsets.only(bottom: 4),
      child: Button(
        onPressed: enabled ? () => Navigator.pop(context, action) : null,
        child: Padding(
          padding: const EdgeInsets.symmetric(vertical: 7, horizontal: 4),
          child: Row(
            children: [
              Icon(icon, size: 16, color: enabled ? HsColors.inkSoft : HsColors.inkFaint),
              const SizedBox(width: 10),
              Expanded(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text(title, style: const TextStyle(fontSize: 13, fontWeight: FontWeight.w600)),
                    Text(subtitle, style: const TextStyle(fontSize: 11.5, color: HsColors.inkFaint)),
                  ],
                ),
              ),
            ],
          ),
        ),
      ),
    );
  }

  Future<String?> _askName(BuildContext context, String title, {String initial = ''}) async {
    final controller = TextEditingController(text: initial);
    final name = await showDialog<String>(
      context: context,
      builder: (context) => ContentDialog(
        title: Text(title),
        content: SizedBox(
          height: 36,
          child: TextBox(
            controller: controller,
            autofocus: true,
            maxLines: 1,
            placeholder: 'Name',
            onSubmitted: (value) => Navigator.pop(context, value.trim()),
          ),
        ),
        actions: [
          Button(child: const Text('Cancel'), onPressed: () => Navigator.pop(context)),
          FilledButton(
            child: const Text('Save'),
            onPressed: () => Navigator.pop(context, controller.text.trim()),
          ),
        ],
      ),
    );
    controller.dispose();
    return name == null || name.isEmpty ? null : name;
  }

  Future<bool?> _confirm(BuildContext context, String title, String message) => showDialog<bool>(
        context: context,
        builder: (context) => ContentDialog(
          title: Text(title),
          content: Text(message),
          actions: [
            Button(child: const Text('Cancel'), onPressed: () => Navigator.pop(context, false)),
            FilledButton(child: const Text('Remove'), onPressed: () => Navigator.pop(context, true)),
          ],
        ),
      );

  Future<void> _message(BuildContext context, String title, String message) => showDialog<void>(
        context: context,
        builder: (context) => ContentDialog(
          title: Text(title),
          content: SelectableText(message),
          actions: [FilledButton(child: const Text('OK'), onPressed: () => Navigator.pop(context))],
        ),
      );
}

enum _ProfileAction { create, rename, remove, importSave, exportSave, openFolder }

class _SaveChooser extends StatefulWidget {
  final List<SaveEntry> saves;
  const _SaveChooser({required this.saves});

  @override
  State<_SaveChooser> createState() => _SaveChooserState();
}

class _SaveChooserState extends State<_SaveChooser> {
  late SaveEntry _selected = widget.saves.first;

  @override
  Widget build(BuildContext context) {
    return ContentDialog(
      title: const Text('Which save?'),
      content: SizedBox(
        width: 440,
        child: Column(
          mainAxisSize: MainAxisSize.min,
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            const Text('That folder has saves from more than one user.',
                style: TextStyle(fontSize: 12.5, color: HsColors.inkSoft)),
            const SizedBox(height: 12),
            ComboBox<SaveEntry>(
              isExpanded: true,
              value: _selected,
              items: [
                for (final save in widget.saves)
                  ComboBoxItem(value: save, child: Text(save.label, style: const TextStyle(fontSize: 12))),
              ],
              onChanged: (value) {
                if (value != null) setState(() => _selected = value);
              },
            ),
          ],
        ),
      ),
      actions: [
        Button(child: const Text('Cancel'), onPressed: () => Navigator.pop(context)),
        FilledButton(child: const Text('Import'), onPressed: () => Navigator.pop(context, _selected)),
      ],
    );
  }
}
