// Start the built game and close the window (the Tk Play button's play_and_close).
import 'dart:io';

import 'package:flutter/widgets.dart';

import 'blocs/builder_bloc.dart';
import 'config.dart' as cfg;

/// [profile] is the launcher's chosen game user (nx2/profiles.py); the game
/// ignores it when it was built before profiles.
Future<void> playAndClose(BuildContext context, String folder, {String? profile, bool? gamescope}) async {
  await BuilderBloc.playFolder(folder, profile: profile, gamescope: gamescope);
  // (the launcher's option; unset keeps the old behaviour: the window closes)
  if (cfg.loadConfig()['close_after_launch'] != '0') exit(0);
}

/// Open a folder in the platform's default file manager.
Future<void> openFolder(String folder) async {
  final command = Platform.isWindows ? 'explorer.exe' : 'xdg-open';
  await Process.start(command, [folder], mode: ProcessStartMode.detached);
}
