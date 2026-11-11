// Shared Builder chrome: window head, page column, cards, footer, banners,
// stage track, log view and dialogs. Fluent widgets in the Slate look.
import 'dart:io';

import 'package:bitsdojo_window/bitsdojo_window.dart';
import 'package:fluent_ui/fluent_ui.dart';
import 'package:lucide_icons_flutter/lucide_icons.dart';

import '../config.dart' show builderVersion, toolsRoot;
import '../theme.dart';

/// The rocket logo beside the brand name (assets/hookshot.png, as the Tk window).
class BrandLogo extends StatelessWidget {
  const BrandLogo({super.key});
  @override
  Widget build(BuildContext context) {
    final file = File('${toolsRoot()}/assets/hookshot.png');
    if (file.existsSync()) return Image.file(file, height: 30, filterQuality: FilterQuality.medium);
    return const SizedBox.shrink();
  }
}

/// Window head: logo and brand on the left, the steps pill in the middle and
/// an optional chip beside the brand. Dragging it moves the window.
class HsHeader extends StatelessWidget {
  final int? step; // 0 Game files, 1 Build, 2 Play
  final String? chip;
  const HsHeader({super.key, this.step, this.chip});

  @override
  Widget build(BuildContext context) {
    return Container(
      height: 60,
      decoration: BoxDecoration(
        color: HsColors.page,
        border: Border(bottom: BorderSide(color: HsColors.glassLine)),
      ),
      padding: const EdgeInsets.symmetric(horizontal: 24),
      child: MoveWindow(
        child: SizedBox(
          height: 60,
          child: Row(
            children: [
              const BrandLogo(),
              const SizedBox(width: 10),
              const Text('Hookshot', style: TextStyle(fontSize: 15, fontWeight: FontWeight.bold, color: HsColors.ink)),
              const SizedBox(width: 8),
              Container(width: 1, height: 14, color: HsColors.glassLine),
              const SizedBox(width: 8),
              const Text('Builder $builderVersion', style: TextStyle(fontSize: 12.5, color: HsColors.inkFaint)),
              if (chip != null) ...[
                const SizedBox(width: 14),
                Flexible(
                  child: Text(chip!,
                      maxLines: 1,
                      overflow: TextOverflow.ellipsis,
                      style: const TextStyle(fontSize: 12.5, color: HsColors.inkSoft)),
                ),
              ],
              if (step != null) Expanded(child: Center(child: StepsPill(on: step!))) else const Spacer(),
            ],
          ),
        ),
      ),
    );
  }
}

class StepsPill extends StatelessWidget {
  final int on;
  const StepsPill({super.key, required this.on});
  @override
  Widget build(BuildContext context) {
    const names = ['Game files', 'Build', 'Play'];
    return Container(
      padding: const EdgeInsets.all(3),
      decoration: BoxDecoration(
        color: HsColors.raised,
        borderRadius: BorderRadius.circular(20),
        border: Border.all(color: HsColors.glassLine),
      ),
      child: Row(
        mainAxisSize: MainAxisSize.min,
        children: [
          for (var i = 0; i < names.length; i++) _step(names[i], i),
        ],
      ),
    );
  }

  Widget _step(String name, int i) {
    final done = i < on;
    final current = i == on;
    return AnimatedContainer(
      duration: const Duration(milliseconds: 240),
      curve: Curves.easeOutCubic,
      padding: const EdgeInsets.symmetric(horizontal: 13, vertical: 6),
      decoration: current
          ? BoxDecoration(
              gradient: const LinearGradient(colors: [Color(0xFF3557d6), Color(0xFF4b70f0)]),
              borderRadius: BorderRadius.circular(16),
            )
          : const BoxDecoration(color: Colors.transparent, borderRadius: BorderRadius.all(Radius.circular(16))),
      child: Row(
        mainAxisSize: MainAxisSize.min,
        children: [
          AnimatedSize(
            duration: const Duration(milliseconds: 200),
            curve: Curves.easeOutCubic,
            child: done
                ? const Padding(
                    padding: EdgeInsets.only(right: 5),
                    child: Icon(LucideIcons.check, size: 12, color: HsColors.go),
                  )
                : const SizedBox.shrink(),
          ),
          AnimatedDefaultTextStyle(
            duration: const Duration(milliseconds: 200),
            curve: Curves.easeOutCubic,
            style: TextStyle(
              fontSize: 12,
              fontWeight: current ? FontWeight.w600 : FontWeight.normal,
              color: current ? Colors.white : (done ? HsColors.inkSoft : HsColors.inkFaint),
            ),
            child: Text(name),
          ),
        ],
      ),
    );
  }
}

/// A one-shot pop for status icons: scales in with a small overshoot.
class HsPopIn extends StatelessWidget {
  final Widget child;
  const HsPopIn({super.key, required this.child});

  @override
  Widget build(BuildContext context) {
    return TweenAnimationBuilder<double>(
      tween: Tween(begin: 0.82, end: 1),
      duration: const Duration(milliseconds: 420),
      curve: Curves.easeOutBack,
      builder: (context, value, child) => Transform.scale(scale: value, child: child),
      child: child,
    );
  }
}

/// Page column: centered, 1040px wide at most, 32px side padding.
/// [fill] gives the child the whole body height (for split views); otherwise
/// the page scrolls.
class HsPage extends StatelessWidget {
  final Widget child;
  final bool fill;
  final double maxWidth;
  final EdgeInsets padding;
  const HsPage({
    super.key,
    required this.child,
    this.fill = false,
    this.maxWidth = 1040,
    this.padding = const EdgeInsets.fromLTRB(32, 24, 32, 24),
  });

  @override
  Widget build(BuildContext context) {
    // A page opens with the page itself focused, not its first text field: that
    // field would show its placeholder (or a ComboBox its value) as selected.
    return Focus(
      autofocus: true,
      child: fill
          ? Padding(
              padding: padding,
              child: Align(
                alignment: Alignment.topCenter,
                child: ConstrainedBox(
                  constraints: BoxConstraints(maxWidth: maxWidth),
                  child: SizedBox(width: double.infinity, height: double.infinity, child: child),
                ),
              ),
            )
          : SingleChildScrollView(
              padding: padding,
              child: Center(
                child: ConstrainedBox(constraints: BoxConstraints(maxWidth: maxWidth), child: child),
              ),
            ),
    );
  }
}

/// The persistent action bar at the bottom of a page.
class HsFooter extends StatelessWidget {
  final Widget? leading;
  final List<Widget> actions;
  const HsFooter({super.key, this.leading, this.actions = const []});

  @override
  Widget build(BuildContext context) {
    return Container(
      decoration: BoxDecoration(
        color: HsColors.page,
        border: Border(top: BorderSide(color: HsColors.glassLine)),
      ),
      padding: const EdgeInsets.symmetric(horizontal: 32, vertical: 13),
      child: Center(
        child: ConstrainedBox(
          constraints: const BoxConstraints(maxWidth: 1040),
          child: Row(
            children: [
              Expanded(child: leading ?? const SizedBox.shrink()),
              if (actions.isNotEmpty) const SizedBox(width: 16),
              for (var i = 0; i < actions.length; i++) ...[
                if (i > 0) const SizedBox(width: 10),
                actions[i],
              ],
            ],
          ),
        ),
      ),
    );
  }
}

/// A grouped block: uppercase title, optional subtitle and trailing widget,
/// then its content.
class HsCard extends StatelessWidget {
  final String? title;
  final String? subtitle;
  final Widget? trailing;
  final Widget child;
  final bool fills;
  final EdgeInsets padding;
  const HsCard({
    super.key,
    this.title,
    this.subtitle,
    this.trailing,
    required this.child,
    this.fills = false,
    this.padding = const EdgeInsets.all(18),
  });

  @override
  Widget build(BuildContext context) {
    return Container(
      decoration: BoxDecoration(
        color: HsColors.raised,
        borderRadius: BorderRadius.circular(10),
        border: Border.all(color: HsColors.glassLine),
      ),
      padding: padding,
      child: Column(
        mainAxisSize: fills ? MainAxisSize.max : MainAxisSize.min,
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          if (title != null)
            Row(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Expanded(
                  child: Text(title!.toUpperCase(),
                      style: const TextStyle(
                          fontSize: 11, fontWeight: FontWeight.bold, letterSpacing: 0.9, color: HsColors.inkSoft)),
                ),
                if (trailing != null) trailing!,
              ],
            ),
          if (subtitle != null)
            Padding(
              padding: const EdgeInsets.only(top: 4),
              child: Text(subtitle!, style: const TextStyle(fontSize: 12, color: HsColors.inkFaint)),
            ),
          if (title != null || subtitle != null) const SizedBox(height: 14),
          if (fills) Expanded(child: child) else child,
        ],
      ),
    );
  }
}

/// A labelled form control.
class HsField extends StatelessWidget {
  final String label;
  final Widget child;
  final String? hint;
  const HsField({super.key, required this.label, required this.child, this.hint});

  @override
  Widget build(BuildContext context) {
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Text(label, style: const TextStyle(fontSize: 12, fontWeight: FontWeight.w600, color: HsColors.inkSoft)),
        const SizedBox(height: 6),
        child,
        if (hint != null) ...[
          const SizedBox(height: 5),
          Text(hint!, style: const TextStyle(fontSize: 11.5, color: HsColors.inkFaint)),
        ],
      ],
    );
  }
}

enum HsBannerKind { info, warning, success }

/// A tinted strip for state that must be visible on the page itself.
class HsBanner extends StatelessWidget {
  final HsBannerKind kind;
  final String title;
  final String? message;
  final Widget? action;
  const HsBanner({super.key, required this.kind, required this.title, this.message, this.action});

  @override
  Widget build(BuildContext context) {
    final color = switch (kind) {
      HsBannerKind.info => HsColors.brand,
      HsBannerKind.warning => HsColors.bad,
      HsBannerKind.success => HsColors.go,
    };
    final icon = switch (kind) {
      HsBannerKind.info => LucideIcons.info,
      HsBannerKind.warning => LucideIcons.triangleAlert,
      HsBannerKind.success => LucideIcons.circleCheck,
    };
    return Container(
      width: double.infinity,
      padding: const EdgeInsets.all(14),
      decoration: BoxDecoration(
        color: Color.alphaBlend(color.withValues(alpha: 0.12), HsColors.page),
        borderRadius: BorderRadius.circular(10),
        border: Border.all(color: Color.alphaBlend(color.withValues(alpha: 0.45), HsColors.page)),
      ),
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Icon(icon, size: 16, color: color),
          const SizedBox(width: 10),
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(title, style: const TextStyle(fontSize: 13, fontWeight: FontWeight.w600, color: HsColors.ink)),
                if (message != null) ...[
                  const SizedBox(height: 3),
                  Text(message!, style: const TextStyle(fontSize: 12.5, height: 1.35, color: HsColors.inkSoft)),
                ],
              ],
            ),
          ),
          if (action != null) ...[const SizedBox(width: 12), action!],
        ],
      ),
    );
  }
}

class HsStage {
  final String label;
  final String? note;
  const HsStage(this.label, {this.note});
}

/// Vertical step list for the build page: done, current, still to come.
class HsStageTrack extends StatelessWidget {
  final List<HsStage> stages;
  final int current; // -1 nothing started, stages.length all done
  const HsStageTrack({super.key, required this.stages, required this.current});

  @override
  Widget build(BuildContext context) {
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        for (var i = 0; i < stages.length; i++)
          SizedBox(
            height: i == stages.length - 1 ? 40 : 56,
            child: Row(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                SizedBox(
                  width: 22,
                  child: Column(
                    children: [
                      _dot(i),
                      if (i < stages.length - 1)
                        Expanded(
                          child: Center(
                            child: AnimatedContainer(
                              duration: const Duration(milliseconds: 260),
                              curve: Curves.easeOutCubic,
                              width: 2,
                              color: i < current ? HsColors.go : HsColors.glassLine,
                            ),
                          ),
                        ),
                    ],
                  ),
                ),
                const SizedBox(width: 12),
                Expanded(
                  child: Padding(
                    padding: const EdgeInsets.only(top: 2),
                    child: Column(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                        Row(
                          children: [
                            Flexible(
                              child: Text(
                                stages[i].label,
                                style: TextStyle(
                                  fontSize: 13,
                                  fontWeight: i == current ? FontWeight.w600 : FontWeight.normal,
                                  color: i <= current ? HsColors.ink : HsColors.inkFaint,
                                ),
                              ),
                            ),
                            if (i == current)
                              const Padding(
                                padding: EdgeInsets.only(left: 8),
                                child: SizedBox(width: 12, height: 12, child: ProgressRing(strokeWidth: 2)),
                              ),
                          ],
                        ),
                        if (stages[i].note != null)
                          Padding(
                            padding: const EdgeInsets.only(top: 2),
                            child:
                                Text(stages[i].note!, style: const TextStyle(fontSize: 11.5, color: HsColors.inkFaint)),
                          ),
                      ],
                    ),
                  ),
                ),
              ],
            ),
          ),
      ],
    );
  }

  Widget _dot(int i) {
    if (i < current) {
      return AnimatedContainer(
        duration: const Duration(milliseconds: 260),
        curve: Curves.easeOutCubic,
        width: 20,
        height: 20,
        decoration: const BoxDecoration(color: HsColors.go, shape: BoxShape.circle),
        child: const Center(child: Icon(LucideIcons.check, size: 12, color: HsColors.goInk)),
      );
    }
    if (i == current) {
      return AnimatedContainer(
        duration: const Duration(milliseconds: 260),
        curve: Curves.easeOutCubic,
        width: 20,
        height: 20,
        decoration: BoxDecoration(
          shape: BoxShape.circle,
          color: HsColors.brand,
          border: Border.all(color: HsColors.brandHover, width: 3),
        ),
      );
    }
    return AnimatedContainer(
      duration: const Duration(milliseconds: 260),
      curve: Curves.easeOutCubic,
      width: 20,
      height: 20,
      decoration: BoxDecoration(
        shape: BoxShape.circle,
        border: Border.all(color: HsColors.quietLine, width: 2),
      ),
    );
  }
}

class HsNote extends StatelessWidget {
  final String text;
  const HsNote(this.text, {super.key});
  @override
  Widget build(BuildContext context) {
    return Text(text, style: const TextStyle(fontSize: 13, height: 1.35, color: HsColors.inkSoft));
  }
}

/// Read-only log view with autoscroll. [expand] lets it fill its parent
/// (put it in an Expanded or a fills card); otherwise it is 220px tall.
class HsLogView extends StatefulWidget {
  final List<String> lines;
  final bool expand;
  const HsLogView(this.lines, {super.key, this.expand = false});
  @override
  State<HsLogView> createState() => _HsLogViewState();
}

class _HsLogViewState extends State<HsLogView> {
  final _controller = ScrollController();

  void _toEnd() {
    WidgetsBinding.instance.addPostFrameCallback((_) {
      if (!_controller.hasClients) return;
      _controller.animateTo(_controller.position.maxScrollExtent,
          duration: const Duration(milliseconds: 120), curve: Curves.easeOutCubic);
    });
  }

  @override
  void initState() {
    super.initState();
    _toEnd();
  }

  @override
  void didUpdateWidget(HsLogView old) {
    super.didUpdateWidget(old);
    if (widget.lines.length != old.lines.length) _toEnd();
  }

  @override
  void dispose() {
    _controller.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    return Container(
      height: widget.expand ? null : 220,
      padding: const EdgeInsets.all(8),
      decoration: BoxDecoration(
        color: HsColors.logBg,
        borderRadius: BorderRadius.circular(6),
        border: Border.all(color: HsColors.glassLine),
      ),
      child: Scrollbar(
        controller: _controller,
        child: ListView.builder(
          controller: _controller,
          reverse: true,
          itemCount: widget.lines.length,
          itemExtent: 17,
          itemBuilder: (context, i) => SelectableText(widget.lines[widget.lines.length - 1 - i],
              style: const TextStyle(fontSize: 11, color: HsColors.inkSoft, fontFamilyFallback: hsMonoFamilies)),
        ),
      ),
    );
  }
}

/// A muted status line with an icon.
class HsStatusLine extends StatelessWidget {
  final String text;
  final Color color;
  final IconData icon;
  const HsStatusLine(this.text, {super.key, this.color = HsColors.inkSoft, this.icon = LucideIcons.info});

  @override
  Widget build(BuildContext context) {
    return Row(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Padding(
          padding: const EdgeInsets.only(top: 1),
          child: Icon(icon, size: 13, color: color),
        ),
        const SizedBox(width: 7),
        Expanded(
          child: Text(text, style: TextStyle(fontSize: 12, height: 1.3, color: color)),
        ),
      ],
    );
  }
}

Future<bool> hsConfirm(BuildContext context, String title, String message) async {
  final result = await showDialog<bool>(
    context: context,
    builder: (context) => ContentDialog(
      title: Text(title),
      content: Text(message),
      actions: [
        Button(child: const Text('Cancel'), onPressed: () => Navigator.pop(context, false)),
        FilledButton(child: const Text('OK'), onPressed: () => Navigator.pop(context, true)),
      ],
    ),
  );
  return result ?? false;
}

void hsError(BuildContext context, String title, String message) {
  showDialog<void>(
    context: context,
    builder: (context) => ContentDialog(
      title: Text(title),
      content: SelectableText(message),
      actions: [FilledButton(child: const Text('OK'), onPressed: () => Navigator.pop(context))],
    ),
  );
}

void hsWarning(BuildContext context, String title, String message) {
  showDialog<void>(
    context: context,
    builder: (context) => ContentDialog(
      title: Row(children: [
        const Icon(LucideIcons.triangleAlert, color: HsColors.bad),
        const SizedBox(width: 8),
        Text(title),
      ]),
      content: SelectableText(message),
      actions: [FilledButton(child: const Text('OK'), onPressed: () => Navigator.pop(context))],
    ),
  );
}
