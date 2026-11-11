// Parsed make_game.py builder-protocol lines (the @@ lines plus the two plain
// sentences the window acts on). Mirrors hookshot_builder.py on_line() and
// make_game.reported(). Pure: unit-tested in test/build_events_test.dart.
import 'package:equatable/equatable.dart';

sealed class BuildEvent extends Equatable {
  const BuildEvent();
  @override
  List<Object?> get props => [];
}

class StageEvent extends BuildEvent {
  final String id;
  final String text;
  const StageEvent(this.id, this.text);
  @override
  List<Object?> get props => [id, text];
}

class ProgressEvent extends BuildEvent {
  final double fraction;
  const ProgressEvent(this.fraction);
  @override
  List<Object?> get props => [fraction];
}

class PlanEvent extends BuildEvent {
  final int changed;
  final int total;
  const PlanEvent(this.changed, this.total);
  @override
  List<Object?> get props => [changed, total];
}

class FileEvent extends BuildEvent {
  final String name;
  final double seconds;
  final String kind; // "new", "again" or "cached"
  const FileEvent(this.name, this.seconds, this.kind);
  @override
  List<Object?> get props => [name, seconds, kind];
}

class EtaEvent extends BuildEvent {
  final double seconds;
  const EtaEvent(this.seconds);
  @override
  List<Object?> get props => [seconds];
}

class TimesEvent extends BuildEvent {
  final double total;
  final double compiled;
  final double previous; // -1 when none
  const TimesEvent(this.total, this.compiled, this.previous);
  @override
  List<Object?> get props => [total, compiled, previous];
}

class DoneEvent extends BuildEvent {
  final String folder;
  const DoneEvent(this.folder);
  @override
  List<Object?> get props => [folder];
}

class ErrorEvent extends BuildEvent {
  final String text;
  const ErrorEvent(this.text);
  @override
  List<Object?> get props => [text];
}

/// make_game.py NOT_PREPARED plain line ("the shaders were not prepared now ...").
class NotPreparedEvent extends BuildEvent {
  const NotPreparedEvent();
}

/// "Your game dump is incomplete: N game file(s) ...": N damaged files replaced.
class DamagedEvent extends BuildEvent {
  final int count;
  const DamagedEvent(this.count);
  @override
  List<Object?> get props => [count];
}

/// Any other line: shown in the log only.
class LogEvent extends BuildEvent {
  final String line;
  const LogEvent(this.line);
  @override
  List<Object?> get props => [line];
}

/// The damaged count from make_game's "Your game dump is incomplete: N ..." line, else 0.
int damagedCount(String line) {
  const head = 'Your game dump is incomplete: ';
  if (!line.startsWith(head)) return 0;
  return int.tryParse(line.substring(head.length).split(' ').first) ?? 0;
}

/// make_game.reported(): the sentence after @@error/@@check ok|bad, else null.
String? reported(String line) {
  if (line.startsWith('@@error ')) return line.substring('@@error '.length);
  if (line.startsWith('@@check ok ') || line.startsWith('@@check bad ')) {
    return line.split(' ').skip(2).join(' ');
  }
  return null;
}

/// Parse one builder-protocol line. Never throws.
BuildEvent parseBuilderLine(String line) {
  if (line.startsWith('@@stage ')) {
    final rest = line.substring('@@stage '.length);
    final i = rest.indexOf(' ');
    if (i < 0) return LogEvent(line);
    return StageEvent(rest.substring(0, i), rest.substring(i + 1));
  }
  if (line.startsWith('@@progress ')) {
    final v = double.tryParse(line.substring('@@progress '.length).trim());
    if (v != null) return ProgressEvent(v);
    return LogEvent(line);
  }
  if (line.startsWith('@@plan ')) {
    final p = line.split(' ');
    if (p.length == 3) {
      final c = int.tryParse(p[1]);
      final t = int.tryParse(p[2]);
      if (c != null && t != null) return PlanEvent(c, t);
    }
    return LogEvent(line);
  }
  if (line.startsWith('@@file ')) {
    final p = line.split(' ');
    if (p.length == 4) {
      final s = double.tryParse(p[2]);
      if (s != null) return FileEvent(p[1], s, p[3]);
    }
    return LogEvent(line);
  }
  if (line.startsWith('@@eta ')) {
    final v = double.tryParse(line.substring('@@eta '.length).trim());
    if (v != null) return EtaEvent(v);
    return LogEvent(line);
  }
  if (line.startsWith('@@times ')) {
    final p = line.split(' ');
    if (p.length == 4) {
      final a = double.tryParse(p[1]);
      final b = double.tryParse(p[2]);
      final c = double.tryParse(p[3]);
      if (a != null && b != null && c != null) return TimesEvent(a, b, c);
    }
    return LogEvent(line);
  }
  if (line.startsWith('@@done ')) return DoneEvent(line.substring('@@done '.length));
  if (line.startsWith('@@error ')) return ErrorEvent(line.substring('@@error '.length));
  if (line.startsWith('the shaders were not prepared now')) return const NotPreparedEvent();
  final d = damagedCount(line);
  if (d > 0) return DamagedEvent(d);
  return LogEvent(line);
}
