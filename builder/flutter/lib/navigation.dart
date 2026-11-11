// In-window navigation from the builder's Play buttons to the game's launcher.
import 'package:flutter/foundation.dart';

final ValueNotifier<String?> gameLauncher = ValueNotifier<String?>(null);

void openGameLauncher(String folder) => gameLauncher.value = folder;

void closeGameLauncher() => gameLauncher.value = null;
