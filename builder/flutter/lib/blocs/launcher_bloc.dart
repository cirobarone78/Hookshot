// Game-folder launcher state: release selection, pinning and update offer.
import 'dart:io';

import 'package:flutter_bloc/flutter_bloc.dart';
import 'package:equatable/equatable.dart';

import '../config.dart' as cfg;
import '../profiles.dart';
import '../updater/installer.dart' show latestTag, releaseTags, fetchBytes;
import '../updater/manifest.dart' as upd;
import '../updater/version_policy.dart' as policy;

sealed class LauncherEvent extends Equatable {
  const LauncherEvent();
  @override
  List<Object?> get props => [];
}

class LauncherStarted extends LauncherEvent {
  final String folder;
  final String toolsTag;
  const LauncherStarted(this.folder, this.toolsTag);
  @override
  List<Object?> get props => [folder, toolsTag];
}

class LauncherSelectionChanged extends LauncherEvent {
  final String? version;
  final bool? pinSelected;
  const LauncherSelectionChanged({this.version, this.pinSelected});
  @override
  List<Object?> get props => [version, pinSelected];
}

class LauncherProfileChanged extends LauncherEvent {
  final String id;
  const LauncherProfileChanged(this.id);
  @override
  List<Object?> get props => [id];
}

class LauncherGamescopeChanged extends LauncherEvent {
  final bool value;
  const LauncherGamescopeChanged(this.value);
  @override
  List<Object?> get props => [value];
}

class LauncherProfilesReload extends LauncherEvent {
  final String? select;
  const LauncherProfilesReload({this.select});
  @override
  List<Object?> get props => [select];
}

class _LauncherLoaded extends LauncherEvent {
  final String? latest;
  final List<String> versions;
  final Profiles? profiles;
  final String? profileError;
  const _LauncherLoaded(this.latest, this.versions, this.profiles, this.profileError);
  @override
  List<Object?> get props => [latest, versions, profiles, profileError];
}

sealed class LauncherState extends Equatable {
  const LauncherState();
  @override
  List<Object?> get props => [];
}

class LauncherLoading extends LauncherState {
  final String folder;
  const LauncherLoading(this.folder);
  @override
  List<Object?> get props => [folder];
}

class LauncherReady extends LauncherState {
  final String folder;
  final String? game;
  final String? latest;
  final String toolsTag;
  final List<String> versions;
  final String? selectedVersion;
  final String? pinnedTag;
  final bool pinSelected;
  final String status;
  final bool showUpdate;
  final Profiles? profiles;
  final String? profileId;
  final String? profileError;
  final bool kept;
  final bool gamescope;
  const LauncherReady({
    required this.folder,
    required this.game,
    required this.latest,
    required this.toolsTag,
    required this.versions,
    required this.selectedVersion,
    required this.pinnedTag,
    required this.pinSelected,
    required this.status,
    required this.showUpdate,
    this.profiles,
    this.profileId,
    this.profileError,
    required this.kept,
    this.gamescope = false,
  });
  @override
  List<Object?> get props => [
        folder,
        game,
        latest,
        toolsTag,
        versions,
        selectedVersion,
        pinnedTag,
        pinSelected,
        status,
        showUpdate,
        profiles,
        profileId,
        profileError,
        kept,
        gamescope,
      ];
}

class LauncherBloc extends Bloc<LauncherEvent, LauncherState> {
  final ProfilesService _profiles;
  LauncherBloc(String folder, {ProfilesService? profiles})
      : _profiles = profiles ?? ProfilesService(),
        super(LauncherLoading(folder)) {
    on<LauncherStarted>(_onStarted);
    on<_LauncherLoaded>(_onLoaded);
    on<LauncherSelectionChanged>(_onSelectionChanged);
    on<LauncherProfileChanged>(_onProfileChanged);
    on<LauncherProfilesReload>(_onProfilesReload);
    on<LauncherGamescopeChanged>(_onGamescopeChanged);
  }

  Future<void> _onStarted(LauncherStarted e, Emitter<LauncherState> emit) async {
    final gv = upd.gameVersion(e.folder);
    final pinned = policy.pinnedVersion(e.folder);
    final savedProfile = cfg.loadConfig()['profile'];
    emit(LauncherReady(
      folder: e.folder,
      game: gv.version,
      latest: null,
      toolsTag: e.toolsTag,
      versions: [if (gv.version != null) gv.version!],
      selectedVersion: pinned ?? gv.version,
      pinnedTag: pinned,
      pinSelected: pinned != null,
      status: 'Checking for updates…',
      showUpdate: false,
      profileId: savedProfile,
      kept: gv.kept,
      gamescope: cfg.loadConfig()['gamescope'] == '1',
    ));

    final forced = Platform.environment['HOOKSHOT_LATEST_TAG'] ??
        const String.fromEnvironment('HOOKSHOT_LATEST_TAG', defaultValue: '');
    String? latest;
    final versions = <String>[];
    if (forced == 'none') {
      latest = null;
    } else if (forced.isNotEmpty) {
      latest = forced;
    } else {
      try {
        latest = await latestTag(fetchBytes);
      } catch (_) {
        latest = null;
      }
    }
    try {
      versions.addAll(await releaseTags(fetchBytes));
    } catch (_) {
      // Keep the installed/latest tags available when GitHub's release list is offline.
    }
    Profiles? profiles;
    String? profileError;
    try {
      profiles = await _profiles.load(e.folder);
    } catch (error) {
      profileError = '$error';
    }
    add(_LauncherLoaded(latest, versions, profiles, profileError));
  }

  void _onLoaded(_LauncherLoaded e, Emitter<LauncherState> emit) {
    final s = state;
    if (s is! LauncherReady) return;
    final gv = upd.gameVersion(s.folder);
    final target = upd.updateTarget(e.latest, s.toolsTag);
    final versions = [...e.versions];
    if (target != null && !versions.contains(target)) versions.insert(0, target);
    if (gv.version != null && !versions.contains(gv.version)) versions.add(gv.version!);
    if (s.pinnedTag != null && !versions.contains(s.pinnedTag)) versions.add(s.pinnedTag!);
    final selected =
        s.selectedVersion ?? s.pinnedTag ?? target ?? gv.version ?? (versions.isEmpty ? null : versions.first);
    emit(_ready(
      folder: s.folder,
      game: gv.version,
      latest: e.latest,
      toolsTag: s.toolsTag,
      versions: versions,
      selectedVersion: selected,
      pinnedTag: s.pinnedTag,
      pinSelected: s.pinSelected,
      kept: gv.kept,
      profiles: e.profiles,
      profileId: s.profileId,
      profileError: e.profileError,
      gamescope: s.gamescope,
    ));
  }

  void _onSelectionChanged(LauncherSelectionChanged e, Emitter<LauncherState> emit) {
    final s = state;
    if (s is! LauncherReady) return;
    final selected = e.version ?? s.selectedVersion;
    final pin = e.pinSelected ?? s.pinSelected;
    var pinnedTag = s.pinnedTag;
    if (e.pinSelected != null) {
      if (!pin) {
        policy.setPinnedVersion(s.folder, null);
        pinnedTag = null;
      } else if (selected != null && selected == s.game) {
        policy.setPinnedVersion(s.folder, selected);
        pinnedTag = selected;
      }
    }
    final gv = upd.gameVersion(s.folder);
    emit(_ready(
      folder: s.folder,
      game: s.game,
      latest: s.latest,
      toolsTag: s.toolsTag,
      versions: s.versions,
      selectedVersion: selected,
      pinnedTag: pinnedTag,
      pinSelected: pin,
      kept: gv.kept,
      profiles: s.profiles,
      profileId: s.profileId,
      profileError: s.profileError,
      gamescope: s.gamescope,
    ));
  }

  void _onProfileChanged(LauncherProfileChanged e, Emitter<LauncherState> emit) {
    final s = state;
    if (s is! LauncherReady || s.profiles?.byId(e.id) == null) return;
    final config = cfg.loadConfig()..['profile'] = e.id;
    cfg.saveConfig(config);
    emit(_copyWithProfile(s, profileId: e.id));
  }

  void _onGamescopeChanged(LauncherGamescopeChanged e, Emitter<LauncherState> emit) {
    final s = state;
    if (s is! LauncherReady) return;
    final config = cfg.loadConfig()..['gamescope'] = e.value ? '1' : '0';
    cfg.saveConfig(config);
    emit(_copyWithProfile(s, gamescope: e.value));
  }

  Future<void> _onProfilesReload(LauncherProfilesReload e, Emitter<LauncherState> emit) async {
    final s = state;
    if (s is! LauncherReady) return;
    try {
      final profiles = await _profiles.load(s.folder);
      final id = profiles.byId(e.select ?? s.profileId)?.id ?? profiles.selected;
      if (e.select != null) {
        final config = cfg.loadConfig()..['profile'] = id;
        cfg.saveConfig(config);
      }
      emit(_copyWithProfile(s, profiles: profiles, profileId: id, clearError: true));
    } catch (error) {
      emit(_copyWithProfile(s, error: '$error'));
    }
  }

  LauncherReady _copyWithProfile(
    LauncherReady s, {
    Profiles? profiles,
    String? profileId,
    String? error,
    bool clearError = false,
    bool? gamescope,
  }) {
    return LauncherReady(
      folder: s.folder,
      game: s.game,
      latest: s.latest,
      toolsTag: s.toolsTag,
      versions: s.versions,
      selectedVersion: s.selectedVersion,
      pinnedTag: s.pinnedTag,
      pinSelected: s.pinSelected,
      status: s.status,
      showUpdate: s.showUpdate,
      profiles: profiles ?? s.profiles,
      profileId: profileId ?? s.profileId,
      profileError: clearError ? null : (error ?? s.profileError),
      kept: s.kept,
      gamescope: gamescope ?? s.gamescope,
    );
  }

  LauncherReady _ready({
    required String folder,
    required String? game,
    required String? latest,
    required String toolsTag,
    required List<String> versions,
    required String? selectedVersion,
    required String? pinnedTag,
    required bool pinSelected,
    required bool kept,
    Profiles? profiles,
    String? profileId,
    String? profileError,
    bool? gamescope,
  }) {
    final selected = selectedVersion;
    final current = game;
    final showUpdate = selected != null && current != null && selected != current && kept;
    final String status;
    if (selected == null) {
      status = 'No installable releases were found';
    } else if (showUpdate) {
      status = 'Switch from $current to $selected. Saves and settings will be backed up first.';
    } else if (selected != current && !kept) {
      status = 'This installation has no saved game files for rebuilding.';
    } else if (pinnedTag != null && current == pinnedTag) {
      status = '$current is installed and pinned; automatic update prompts are off.';
    } else if (current == null && kept) {
      status = 'This folder was built from source; ready to play.';
    } else if (current != null && latest == null) {
      status = 'Up to date with this builder (GitHub did not answer)';
    } else if (current != null) {
      status = current == latest ? 'Up to date' : '$current is installed';
    } else if (latest == null) {
      status = 'Could not check for updates (GitHub did not answer)';
    } else {
      status = 'Select an available version to build this folder.';
    }
    return LauncherReady(
      folder: folder,
      game: game,
      latest: latest,
      toolsTag: toolsTag,
      versions: versions,
      selectedVersion: selected,
      pinnedTag: pinnedTag,
      pinSelected: pinSelected,
      status: status,
      showUpdate: showUpdate,
      profiles: profiles,
      profileId: profiles?.byId(profileId) == null ? profiles?.selected : profileId,
      profileError: profileError,
      kept: kept,
      gamescope: gamescope ?? false,
    );
  }
}
