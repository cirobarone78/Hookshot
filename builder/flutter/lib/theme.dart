// The look: the Windows builder's "Slate" theme, carried over the Fluent widgets.
// Same colours, Inter-first font stack, rounded cards/buttons/fields.
import 'package:fluent_ui/fluent_ui.dart';

int mixChannel(int x, int y, double alpha) => ((x * alpha) + (y * (1 - alpha))).round();

Color mix(Color a, Color b, double alpha) {
  if (alpha >= 1) return a;
  final av = a.toARGB32();
  final bv = b.toARGB32();
  return Color.fromARGB(255, mixChannel((av >> 16) & 255, (bv >> 16) & 255, alpha),
      mixChannel((av >> 8) & 255, (bv >> 8) & 255, alpha), mixChannel(av & 255, bv & 255, alpha));
}

const _page = Color(0xFF14161a);

class HsColors {
  static const page = _page;
  static const raised = Color(0xFF1c1f24);
  static const raisedHover = Color(0xFF23272d);
  static const lineStrong = Color(0xFF3d434c);
  static const ink = Color(0xFFedeff2);
  static const inkSoft = Color(0xFFa2a9b3);
  static const inkFaint = Color(0xFF6e7681);
  static const brand = Color(0xFF3d63e6);
  static const brandHover = Color(0xFF4b70f0);
  static const brandInk = Color(0xFFdfe6ff);
  static const go = Color(0xFF5fb08a);
  static const goHover = Color(0xFF70c09a);
  static const goInk = Color(0xFF06150e);
  static const bad = Color(0xFFe2776b);
  static const white = Color(0xFFFFFFFF);
  static final glass = mix(white, page, 0x0D / 255);
  static final glassLine = mix(white, page, 0x17 / 255);
  static final quiet = mix(white, page, 0x08 / 255);
  static final quietLine = mix(white, page, 0x1F / 255);
  static final quietHoverLine = mix(white, page, 0x2A / 255);
  static final tickLine = mix(white, page, 0x40 / 255);
  static final track = mix(white, page, 0x12 / 255);
  static final logBg = mix(const Color(0xFF000000), glass, 0x33 / 255);
}

const hsFontFamilies = ['Inter', 'Segoe UI', 'Cantarell', 'Noto Sans', 'DejaVu Sans', 'Liberation Sans'];
const hsMonoFamilies = ['Cascadia Mono', 'JetBrains Mono', 'DejaVu Sans Mono', 'Noto Sans Mono', 'Liberation Mono'];

AccentColor _brandAccent() => AccentColor.swatch(const <String, Color>{
      'darkest': Color(0xFF2c46ab),
      'darker': Color(0xFF3557d6),
      'dark': Color(0xFF3d63e6),
      'normal': Color(0xFF3d63e6),
      'light': Color(0xFF4b70f0),
      'lighter': Color(0xFF6b8bf5),
      'lightest': Color(0xFFdfe6ff),
    });

FluentThemeData hsTheme() => FluentThemeData(
      brightness: Brightness.dark,
      scaffoldBackgroundColor: HsColors.page,
      accentColor: _brandAccent(),
      fontFamily: 'Inter',
    );

TextStyle hsText(double size, {FontWeight w = FontWeight.normal, Color? color, bool mono = false}) => TextStyle(
    fontSize: size,
    fontWeight: w,
    color: color ?? HsColors.ink,
    fontFamilyFallback: mono ? hsMonoFamilies : hsFontFamilies);

enum HsButtonKind { primary, go, quiet }

/// Rounded button in the three builder styles: primary (blue), go (green), quiet (ghost).
class HsButton extends StatelessWidget {
  final String label;
  final VoidCallback? onPressed;
  final HsButtonKind kind;
  final Widget? icon;
  const HsButton.primary({super.key, required this.label, this.onPressed})
      : kind = HsButtonKind.primary,
        icon = null;
  const HsButton.go({super.key, required this.label, this.onPressed, this.icon}) : kind = HsButtonKind.go;
  const HsButton.quiet({super.key, required this.label, this.onPressed, this.icon}) : kind = HsButtonKind.quiet;

  @override
  Widget build(BuildContext context) {
    final content = icon == null
        ? Text(label, style: const TextStyle(fontSize: 14, fontWeight: FontWeight.bold))
        : Row(mainAxisSize: MainAxisSize.min, children: [
            icon!,
            const SizedBox(width: 8),
            Text(label, style: const TextStyle(fontSize: 14, fontWeight: FontWeight.bold))
          ]);
    final pad = switch (kind) {
      HsButtonKind.primary => const EdgeInsets.symmetric(horizontal: 22, vertical: 6),
      HsButtonKind.go => const EdgeInsets.symmetric(horizontal: 30, vertical: 10),
      HsButtonKind.quiet => const EdgeInsets.symmetric(horizontal: 18, vertical: 6),
    };
    final style = switch (kind) {
      HsButtonKind.primary => const ButtonStyle(),
      HsButtonKind.go => ButtonStyle(
          backgroundColor: WidgetStateProperty.resolveWith((states) {
            if (states.contains(WidgetState.hovered)) return HsColors.goHover;
            return HsColors.go;
          }),
          foregroundColor: WidgetStateProperty.all(HsColors.goInk)),
      HsButtonKind.quiet => const ButtonStyle(),
    };
    final child = Padding(padding: pad, child: content);
    if (kind == HsButtonKind.primary) {
      return FilledButton(onPressed: onPressed, style: const ButtonStyle(), child: child);
    }
    return Button(onPressed: onPressed, style: style, child: child);
  }
}
