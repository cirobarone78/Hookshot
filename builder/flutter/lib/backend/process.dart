// Subprocess runner for make_game.py: lines streamed, whole group killed on cancel.
// Tk starts the build in its own session (start_new_session) and kills the group
// (os.killpg); here the command runs under setsid on POSIX so the group can be
// signalled, and taskkill /T on Windows.
import 'dart:async';
import 'dart:convert';
import 'dart:io';

/// A running build/update/check process.
class BuildProcess {
  final Process _proc;
  final Stream<String> lines;
  BuildProcess._(this._proc, this.lines);

  int get pid => _proc.pid;
  Future<int> get exitCode => _proc.exitCode;

  static Future<BuildProcess> start(List<String> command, {required String cwd, Map<String, String>? env}) async {
    final List<String> cmd;
    if (Platform.isWindows) {
      cmd = command;
    } else {
      cmd = ['setsid', ...command];
    }
    final proc = await Process.start(cmd.first, cmd.sublist(1),
        workingDirectory: cwd, environment: env, runInShell: false, mode: ProcessStartMode.normal);
    // Tk merges stderr into stdout; merge both here the same way.
    final controller = StreamController<String>.broadcast();
    var open = 2;
    void pump(Stream<List<int>> stream) {
      stream.transform(const SystemEncoding().decoder).transform(const LineSplitter()).listen(controller.add,
          onDone: () {
        if (--open == 0) controller.close();
      });
    }

    pump(proc.stdout);
    pump(proc.stderr);
    return BuildProcess._(proc, controller.stream);
  }

  /// Stop the whole group (compilers included), as the Tk builder does.
  Future<bool> killGroup() async {
    if (Platform.isWindows) {
      final r = await Process.run('taskkill', ['/PID', '${_proc.pid}', '/T', '/F']);
      return r.exitCode == 0;
    }
    final r = await Process.run('kill', ['-TERM', '-${_proc.pid}']);
    return r.exitCode == 0;
  }

  bool kill() => _proc.kill(ProcessSignal.sigterm);
}
