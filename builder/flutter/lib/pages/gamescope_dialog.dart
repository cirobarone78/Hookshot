// The gamescope options behind the Linux-only "Launch in gamescope" choice.
import 'package:fluent_ui/fluent_ui.dart';

import '../gamescope.dart';
import '../theme.dart';

Future<GamescopeSettings?> editGamescope(BuildContext context) async {
  final current = GamescopeSettings.load();
  final changed = await showDialog<GamescopeSettings>(
    context: context,
    builder: (context) => _GamescopeDialog(initial: current),
  );
  changed?.save();
  return changed;
}

class _GamescopeDialog extends StatefulWidget {
  final GamescopeSettings initial;
  const _GamescopeDialog({required this.initial});

  @override
  State<_GamescopeDialog> createState() => _GamescopeDialogState();
}

class _GamescopeDialogState extends State<_GamescopeDialog> {
  late final _width = TextEditingController(text: widget.initial.width?.toString() ?? '');
  late final _height = TextEditingController(text: widget.initial.height?.toString() ?? '');
  late final _refresh = TextEditingController(text: widget.initial.refresh?.toString() ?? '');
  late final _extra = TextEditingController(text: widget.initial.extra);
  late bool _hdr = widget.initial.hdr;
  late bool _fullscreen = widget.initial.fullscreen;
  late bool _realTime = widget.initial.realTime;
  late bool _grab = widget.initial.forceGrabCursor;
  late bool _gameMode = widget.initial.gameMode;
  String? _error;

  @override
  void dispose() {
    _width.dispose();
    _height.dispose();
    _refresh.dispose();
    _extra.dispose();
    super.dispose();
  }

  int? _number(TextEditingController field, int min, int max, String name) {
    final text = field.text.trim();
    if (text.isEmpty) return null;
    final value = int.tryParse(text);
    if (value == null || value < min || value > max) {
      _error = '$name must be $min to $max, or empty for gamescope’s default.';
      return null;
    }
    return value;
  }

  void _save() {
    _error = null;
    final width = _number(_width, 320, 16384, 'Width');
    final height = _number(_height, 200, 16384, 'Height');
    final refresh = _number(_refresh, 1, 1000, 'Refresh rate');
    if (_error != null) {
      setState(() {});
      return;
    }
    Navigator.pop(
      context,
      GamescopeSettings(
        enabled: true,
        width: width,
        height: height,
        refresh: refresh,
        hdr: _hdr,
        fullscreen: _fullscreen,
        realTime: _realTime,
        forceGrabCursor: _grab,
        gameMode: _gameMode,
        extra: _extra.text.trim(),
      ),
    );
  }

  @override
  Widget build(BuildContext context) {
    return ContentDialog(
      title: const Text('gamescope options'),
      content: SizedBox(
        width: 520,
        child: SingleChildScrollView(
          child: Column(
            mainAxisSize: MainAxisSize.min,
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              const Text(
                'These are the arguments gamescope receives before the game. Empty size or refresh boxes use gamescope’s own.',
                style: TextStyle(fontSize: 12, color: HsColors.inkSoft),
              ),
              const SizedBox(height: 14),
              Row(
                children: [
                  Expanded(child: _numberField('Width', _width, '3840')),
                  const SizedBox(width: 10),
                  Expanded(child: _numberField('Height', _height, '2160')),
                  const SizedBox(width: 10),
                  Expanded(child: _numberField('Refresh (Hz)', _refresh, '164')),
                ],
              ),
              const SizedBox(height: 10),
              _check('Fullscreen', '-f', _fullscreen, (v) => setState(() => _fullscreen = v)),
              _check('HDR', '--hdr-enabled', _hdr, (v) => setState(() => _hdr = v)),
              _check('Force grab cursor', '--force-grab-cursor', _grab, (v) => setState(() => _grab = v)),
              _check('Real-time scheduling', '--rt', _realTime, (v) => setState(() => _realTime = v)),
              _check('Run through gamemoderun', 'gamemoderun', _gameMode, (v) => setState(() => _gameMode = v)),
              const SizedBox(height: 8),
              const Text('More arguments',
                  style: TextStyle(fontSize: 12, fontWeight: FontWeight.w600, color: HsColors.inkSoft)),
              const SizedBox(height: 6),
              SizedBox(
                height: 36,
                child: TextBox(
                  controller: _extra,
                  maxLines: 1,
                  placeholder: 'e.g. --adaptive-sync --mangoapp',
                  placeholderStyle: const TextStyle(color: HsColors.inkFaint, fontWeight: FontWeight.w300),
                ),
              ),
              if (_error != null) ...[
                const SizedBox(height: 10),
                Text(_error!, style: const TextStyle(fontSize: 12, color: HsColors.bad)),
              ],
            ],
          ),
        ),
      ),
      actions: [
        Button(onPressed: () => Navigator.pop(context), child: const Text('Cancel')),
        FilledButton(onPressed: _save, child: const Text('Save')),
      ],
    );
  }

  Widget _numberField(String label, TextEditingController controller, String placeholder) {
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Text(label, style: const TextStyle(fontSize: 12, fontWeight: FontWeight.w600, color: HsColors.inkSoft)),
        const SizedBox(height: 6),
        SizedBox(
          height: 36,
          child: TextBox(
            controller: controller,
            maxLines: 1,
            placeholder: placeholder,
            placeholderStyle: const TextStyle(color: HsColors.inkFaint, fontWeight: FontWeight.w300),
          ),
        ),
      ],
    );
  }

  Widget _check(String title, String flag, bool value, ValueChanged<bool> onChanged) {
    return Padding(
      padding: const EdgeInsets.only(bottom: 4),
      child: Row(
        children: [
          Checkbox(checked: value, onChanged: (v) => onChanged(v ?? false)),
          const SizedBox(width: 8),
          Expanded(child: Text(title, style: const TextStyle(fontSize: 12.5, color: HsColors.inkSoft))),
          Text(flag,
              style: const TextStyle(fontSize: 11, color: HsColors.inkFaint, fontFamilyFallback: hsMonoFamilies)),
        ],
      ),
    );
  }
}
