"""The game folder's launcher page, as the community mockup draws it: a green hookshot rail on the left, the game hero filling the
right, the Play disc over it, "Build & Update" over its scrim band with the version chain, and the status strip along the bottom.

The hero is the player's own picture, never an art file of ours: the page shows <game folder>/hookshot_hero.png when the folder has
one (a screenshot the player keeps beside their game, or one a later release's own screenshot step writes) and a calm field-green
gradient otherwise. Nothing that comes from the game ships in the builder (CONTRIBUTING.md, "The rule with no exceptions")."""
import os

from PySide6.QtCore import QPointF, QRect, QRectF, Qt
from PySide6.QtGui import QColor, QLinearGradient, QPainter, QPainterPath, QPen, QPixmap
from PySide6.QtWidgets import QAbstractButton, QHBoxLayout, QLabel, QVBoxLayout, QWidget

from .theme import C, W_BOLD, W_MEDIUM, W_SEMIBOLD, Button, argb, font, label, rounded

GREEN = (argb("#006A02"), argb("#001E00"))   # (the mockup's rail: #006701 at the top, #001F00 at the foot)
FIELD = (argb("#14291F"), argb("#0B1014"))   # (the hero without the player's picture: dusk over a field, no game art)
HERO_R = 10
SIDEBAR_W, SIDEBAR_GAP = 246, 12
HERO_FILE = "hookshot_hero.png"


def hero_file(folder):
    """The player's hero picture for this game folder, when it has one ("" when it does not)"""
    p = os.path.join(folder, HERO_FILE)
    return p if os.path.isfile(p) else ""


def vbox(*items, spacing=0, margins=(0, 0, 0, 0)):
    l = QVBoxLayout()
    l.setSpacing(spacing)
    l.setContentsMargins(*margins)
    for it in items:
        if it is None:
            l.addStretch(1)
        elif isinstance(it, int):
            l.addSpacing(it)
        else:
            l.addWidget(it)
    return l


def hbox(*items, spacing=0, margins=(0, 0, 0, 0)):
    l = QHBoxLayout()
    l.setSpacing(spacing)
    l.setContentsMargins(*margins)
    for it in items:
        if it is None:
            l.addStretch(1)
        elif isinstance(it, int):
            l.addSpacing(it)
        else:
            l.addWidget(it)
    return l


class Rail(QWidget):
    """The green rail: its gradient, the hookshot, and the launcher's name with the version it was built with"""

    def __init__(self, hook):
        super().__init__()
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.art = QLabel(self)
        px = hook.scaled(210, 210, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
        self.art.setPixmap(px)
        self.art.setGeometry(0, 40, 210, px.height())
        self.caption = label("Hookshot Launcher", 13, W_SEMIBOLD, "White")
        self.caption.setParent(self)
        self.caption.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.caption.setGeometry(10, self.height() - 44, self.width() - 20, 20)

    def set_caption(self, text):
        self.caption.setText(text)

    def resizeEvent(self, e):
        self.art.move((self.width() - 210) // 2, 40)
        self.caption.setGeometry(10, self.height() - 44, self.width() - 20, 20)

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        r = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        g = QLinearGradient(0, 0, 0, self.height())
        g.setColorAt(0, GREEN[0])
        g.setColorAt(1, GREEN[1])
        p.fillPath(rounded(r, HERO_R), g)
        p.setPen(QPen(argb("#26FFFFFF"), 1))
        p.drawPath(rounded(r, HERO_R))


class PlayDisc(QAbstractButton):
    """Play, the mockup's way: a 96 px disc over the hero, the triangle in it (dim when the folder holds no game yet)"""

    def __init__(self):
        super().__init__()
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.hover = False
        self.setFixedSize(96, 96)

    def enterEvent(self, e):
        self.hover = True
        self.update()

    def leaveEvent(self, e):
        self.hover = False
        self.update()

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHints(QPainter.RenderHint.Antialiasing)
        on = self.isEnabled()
        c = QPointF(48, 48)
        if on:
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor(255, 255, 255, 58 if self.hover else 36))
            p.drawEllipse(c, 47, 47)
            p.setPen(QPen(argb("#40FFFFFF"), 1.4))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawEllipse(c, 47, 47)
            tri = QPainterPath(QPointF(38, 28))
            tri.lineTo(70, 48)
            tri.lineTo(38, 68)
            tri.closeSubpath()
            p.fillPath(tri, C["White"])
        else:
            p.setPen(QPen(argb("#33FFFFFF"), 1.4))
            p.setBrush(argb("#14FFFFFF"))
            p.drawEllipse(c, 47, 47)
            tri = QPainterPath(QPointF(38, 28))
            tri.lineTo(70, 48)
            tri.lineTo(38, 68)
            tri.closeSubpath()
            p.fillPath(tri, argb("#66FFFFFF"))


class Hero(QWidget):
    """The right two thirds: the player's picture or the field gradient, the scrim band for the title, the status strip along its foot"""

    def __init__(self):
        super().__init__()
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.px, self.ready = None, ""

    def show_hero(self, path):
        self.px = QPixmap(path) if path else None
        self.update()

    def set_ready(self, text):
        self.ready = text
        self.update()

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHints(QPainter.RenderHint.Antialiasing | QPainter.RenderHint.SmoothPixmapTransform)
        r = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        p.setClipPath(rounded(r, HERO_R))
        if self.px and not self.px.isNull():   # (cover: fill the hero, keep its centre)
            s = max(r.width() / self.px.width(), r.height() / self.px.height())
            w, h = self.px.width() * s, self.px.height() * s
            p.drawPixmap(QRectF((r.width() - w) / 2, (r.height() - h) / 2, w, h), self.px, QRectF(self.px.rect()))
        else:
            g = QLinearGradient(0, 0, r.width() * 0.35, r.height())
            g.setColorAt(0, FIELD[0])
            g.setColorAt(1, FIELD[1])
            p.fillRect(r, g)
            band = QLinearGradient(0, r.height() * 0.35, 0, r.height() * 0.75)   # (a light sweep, like dusk on the field)
            band.setColorAt(0, argb("#00FFFFFF"))
            band.setColorAt(0.5, argb("#0DFFFFFF"))
            band.setColorAt(1, argb("#00FFFFFF"))
            p.fillRect(r, band)
        top = QLinearGradient(0, 0, 0, 104)   # (the scrim band the "Build & Update" head sits on, as the mockup draws it)
        top.setColorAt(0, argb("#66000000"))
        top.setColorAt(1, argb("#00000000"))
        p.fillRect(QRectF(0, 0, r.width(), 104), top)
        p.fillRect(QRectF(0, r.height() - 54, r.width(), 54), argb("#99000000"))   # (the status strip along the foot)
        p.setPen(QPen(argb("#26FFFFFF"), 1))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawPath(rounded(r, HERO_R))
        if self.ready:
            p.setFont(font(15, W_SEMIBOLD))
            p.setPen(C["White"])
            p.drawText(QRectF(0, r.height() / 2 - 86, r.width(), 22), Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignVCenter,
                       self.ready)


class LaunchPage(QWidget):
    """The whole launcher: rail + hero, and the head, version chain, Play disc, Update button, open-folder link and status over them.
    The window drives it through set_hero / set_ready / set_caption and the labels and buttons it keeps: update, play, fold."""

    def __init__(self, hook):
        super().__init__()
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.folder = ""
        self.rail = Rail(hook)
        self.hero = Hero()
        self.title = label("Build & Update", 26, W_BOLD, "White")
        self.version = label("", 13, color="InkSoft")
        self.status = label("Checking for updates…", 13, W_MEDIUM, "White")
        self.update_button = Button("Update", "primary")   # (not named update: QWidget.update schedules a repaint)
        self.update_button.setFixedHeight(44)
        self.update_button.fixed_h, self.update_button.padx = 44, 26
        self.update_button.hide()
        self.play = PlayDisc()
        self.fold = Button("Open the game folder", "link", color=argb("#B0FFFFFF"))
        for wdg in (self.rail, self.hero, self.title, self.version, self.status, self.update_button, self.play, self.fold):
            wdg.setParent(self)   # (the page draws them as its own: they are its children, not of the layout)
        self._place()

    def _place(self):
        w, h = self.width(), self.height()
        self.rail.setGeometry(0, 0, SIDEBAR_W, h)
        hx, hy = SIDEBAR_W + SIDEBAR_GAP, 0
        hw, hh = w - hx, h
        self.hero.setGeometry(hx, hy, hw, hh)
        self.title.move(hx + 26, 18)
        self.version.setGeometry(hx + 27, 58, hw - 240, 20)
        self.update_button.move(hx + hw - 26 - self.update_button.sizeHint().width(), hy + 22)
        self.play.move(hx + (hw - 96) // 2, hy + hh // 2 - 40)
        fold_w = self.fold.sizeHint().width()
        self.status.setGeometry(hx + 26, hh - 46, hw - fold_w - 80, 26)
        self.fold.move(hx + hw - fold_w - 26, hh - 46)

    def resizeEvent(self, e):
        self._place()

    # ---- what the window tells it ----

    def set_hero(self, folder):
        """The hero shows this game folder's own hookshot_hero.png, if it keeps one (hero_file)."""
        self.folder = folder
        self.hero.show_hero(hero_file(folder))

    def set_ready(self, text):
        self.hero.set_ready(text)

    def set_title(self, text):
        self.title.setText(text)

    def set_caption(self, text):
        self.rail.set_caption(text)
