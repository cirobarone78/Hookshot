// Self-update and game-update download flow. Ports hookshot_builder.py's
// begin_update(): download the manifest's parts, install them, then either
// re-exec into the new builder (self update) or hand the folder back for a
// make_game --update run.
import 'dart:async';
import 'dart:io';

import 'package:flutter_bloc/flutter_bloc.dart';
import 'package:equatable/equatable.dart';

import '../updater/installer.dart' as inst;
import '../updater/manifest.dart' as upd;

sealed class UpdateEvent extends Equatable {
  const UpdateEvent();
  @override
  List<Object?> get props => [];
}

/// Rebuild a game folder from the sources it kept, without downloading anything.
class RebuildFolder extends UpdateEvent {
  final String folder;
  const RebuildFolder(this.folder);
  @override
  List<Object?> get props => [folder];
}

/// Start an update. [folder] empty: update the builder itself.
class BeginUpdate extends UpdateEvent {
  final String folder;
  final String? tag;
  final bool fetched;
  final String toolsTag;
  final String? latest;
  final bool switching;
  const BeginUpdate(
      {required this.folder,
      required this.toolsTag,
      required this.latest,
      this.tag,
      this.fetched = false,
      this.switching = false});
  @override
  List<Object?> get props => [folder, tag, fetched, toolsTag, latest, switching];
}

class _UpdateNote extends UpdateEvent {
  final String message;
  const _UpdateNote(this.message);
  @override
  List<Object?> get props => [message];
}

class _UpdateFailed extends UpdateEvent {
  final String error;
  const _UpdateFailed(this.error);
  @override
  List<Object?> get props => [error];
}

class _UpdateHandoff extends UpdateEvent {
  final String folder;
  const _UpdateHandoff(this.folder);
  @override
  List<Object?> get props => [folder];
}

/// Stop the download, if one is running. The staged parts are removed.
class CancelUpdate extends UpdateEvent {
  const CancelUpdate();
}

/// Back to the files form after a stopped or failed update.
class UpdateReset extends UpdateEvent {
  const UpdateReset();
}

class _UpdateReexec extends UpdateEvent {
  final String apprun;
  final String? folder;
  final String tag;
  const _UpdateReexec(this.apprun, this.folder, this.tag);
  @override
  List<Object?> get props => [apprun, folder, tag];
}

sealed class UpdateState extends Equatable {
  const UpdateState();
  @override
  List<Object?> get props => [];
}

class UpdateIdle extends UpdateState {
  const UpdateIdle();
}

class UpdateWorking extends UpdateState {
  final String note;
  final String title;
  const UpdateWorking(this.title, this.note);
  @override
  List<Object?> get props => [title, note];
}

class UpdateFailed extends UpdateState {
  final String error;
  const UpdateFailed(this.error);
  @override
  List<Object?> get props => [error];
}

/// Hand the folder to the build bloc for make_game --update.
class UpdateHandoff extends UpdateState {
  final String folder;
  const UpdateHandoff(this.folder);
  @override
  List<Object?> get props => [folder];
}

/// Re-exec into the freshly installed builder.
class UpdateReexec extends UpdateState {
  final String apprun;
  final String? folder;
  final String tag;
  const UpdateReexec(this.apprun, this.folder, this.tag);
  @override
  List<Object?> get props => [apprun, folder, tag];
}

typedef FetchBytes = Future<List<int>> Function(String url, {inst.StopFlag? stop});

class UpdateBloc extends Bloc<UpdateEvent, UpdateState> {
  final FetchBytes _fetcher;
  final String? Function()? _runningRoot;
  final String? _installRoot;
  inst.StopFlag? _stop;
  String _title = 'Updating';

  UpdateBloc({FetchBytes? fetcher, String? Function()? runningRoot, String? installRoot})
      : _fetcher = fetcher ?? inst.fetchBytes,
        _runningRoot = runningRoot,
        _installRoot = installRoot,
        super(const UpdateIdle()) {
    on<BeginUpdate>(_onBegin);
    on<RebuildFolder>((e, emit) => emit(UpdateHandoff(e.folder)));
    on<_UpdateNote>((e, emit) {
      final s = state;
      emit(UpdateWorking(s is UpdateWorking ? s.title : 'Updating', e.message));
    });
    on<_UpdateFailed>((e, emit) => emit(UpdateFailed(e.error)));
    on<_UpdateHandoff>((e, emit) => emit(UpdateHandoff(e.folder)));
    on<_UpdateReexec>((e, emit) => emit(UpdateReexec(e.apprun, e.folder, e.tag)));
    on<CancelUpdate>(_onCancel);
    on<UpdateReset>((e, emit) {
      _stop = null;
      emit(const UpdateIdle());
    });
  }

  Future<void> _onBegin(BeginUpdate e, Emitter<UpdateState> emit) async {
    final title = e.folder.isNotEmpty ? 'Updating your game' : 'Updating Hookshot Builder';
    _title = title;
    _stop = inst.StopFlag();
    emit(UpdateWorking(title, 'Checking for updates...'));
    final target = e.tag ?? upd.updateTarget(e.latest, e.toolsTag, switchTrack: e.switching);
    final fetched = e.fetched || (e.folder.isNotEmpty && e.toolsTag.isNotEmpty && target == e.toolsTag);
    try {
      if (!fetched) {
        final root = _runningRoot != null ? _runningRoot!() : upd.runningRoot();
        if (root == null) {
          throw StateError(
              'These tools are a source checkout, so they cannot download a release. Start the AppImage to update.');
        }
        final named = (target != null && (e.switching || upd.trackOf(target) != 'release')) ? target : null;
        Future<List<int>> get(String url) => _fetcher(url, stop: _stop);
        final manifest = await inst.startupManifest(root, get, tag: named, stop: _stop);
        if (manifest.tag != upd.toolsTag(root)) {
          if (e.tag != null && manifest.tag != e.tag) {
            throw StateError(
                'GitHub offered ${manifest.tag}, not ${e.tag}: its download links can lag right after a release. Try Update again in a few minutes.');
          }
          final source = inst.readManifest(root);
          final apprun = await inst.install(manifest, root, source,
              get: get, note: (m) => add(_UpdateNote(m)), stop: _stop, rootOverride: _installRoot);
          add(_UpdateReexec(apprun, e.folder.isEmpty ? null : e.folder, manifest.tag));
          return;
        }
      }
      add(_UpdateHandoff(e.folder));
    } catch (err) {
      add(_UpdateFailed('$err'));
    }
  }

  void _onCancel(CancelUpdate e, Emitter<UpdateState> emit) {
    if (state is UpdateWorking && _stop != null) {
      _stop!.set();
      emit(UpdateWorking(_title, 'Stopping the update'));
    }
  }

  /// Re-exec into the new builder (or the new builder with --update), then exit.
  static Future<void> reexec(String apprun, String? folder, String tag) async {
    final args = <String>[];
    if (folder != null && folder.isNotEmpty) args.addAll(['--update', folder, '--tag', tag, '--fetched']);
    await Process.start(apprun, args, mode: ProcessStartMode.detached);
    exit(0);
  }
}
