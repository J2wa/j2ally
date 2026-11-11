"""All application colors and design tokens; Qt handles logical-pixel DPI scaling."""
from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QFont, QPalette

SPACE = {"xs": 4, "sm": 8, "md": 12, "lg": 16, "xl": 24}
TYPE = {"small": 12, "body": 14, "heading": 24, "answer": 22}
COLORS = {
    "Dark": dict(bg="#10151e", panel="#18212e", input="#111b28", text="#edf2fa", muted="#a8b8cb", border="#42546b", accent="#afd1ff", accent_text="#102139", hover="#2a405d", answer="#182434", code="#0d1622", error="#ffd5c9", error_bg="#4c2724"),
    "Light": dict(bg="#f2f5f9", panel="#ffffff", input="#f7f9fc", text="#17283f", muted="#52647a", border="#9aaec7", accent="#164a8b", accent_text="#ffffff", hover="#dce8f7", answer="#ffffff", code="#e9eff7", error="#842810", error_bg="#ffede7"),
    "High contrast": dict(bg="#000000", panel="#000000", input="#000000", text="#ffffff", muted="#ffffff", border="#ffffff", accent="#ffff00", accent_text="#000000", hover="#242424", answer="#000000", code="#000000", error="#ffffff", error_bg="#000000"),
}


def resolved_theme(choice, app):
    if not hasattr(app, '_ally_style_hints'):
        app._ally_style_hints = app.styleHints()
        app._ally_accessibility = app._ally_style_hints.accessibility()
    if choice != "Follow Windows":
        return choice if choice in COLORS else "Dark"
    # Qt forwards native Windows contrast and color-scheme preferences.
    if app._ally_accessibility.contrastPreference().name == 'HighContrast':
        return "High contrast"
    return "Dark" if app._ally_style_hints.colorScheme() == Qt.ColorScheme.Dark else "Light"


def stylesheet(name="Dark", compact=False, family="Segoe UI"):
    c = COLORS[name]
    pad = 6 if compact else 10
    family = family.replace("'", "").replace('"', '')
    return f"""
QWidget {{ background: {c['bg']}; color: {c['text']}; font-family: '{family}'; font-size: 14px; }}
QLabel {{ background: transparent; }}
QLabel#brand {{ font-size: 38px; font-weight: 800; letter-spacing: 2px; }}
QLabel#heading {{ font-size: 24px; font-weight: 700; }}
QLabel#eyebrow {{ font-size: 12px; font-weight: 700; color: {c['accent']}; }}
QLabel#muted, QLabel#interim {{ color: {c['muted']}; }}
QLabel#badge, QLabel#questionState {{ background: {c['hover']}; color: {c['text']}; padding: 6px; border-radius: 6px; }}
QFrame#sidebar, QFrame#card, QWidget#statusStrip {{ background: {c['panel']}; border: 1px solid {c['border']}; border-radius: 8px; }}
QFrame#card QLabel {{ background: transparent; }}
QPushButton, QToolButton {{ background: {c['panel']}; border: 1px solid {c['border']}; border-radius: 6px; padding: {pad}px 12px; font-weight: 600; }}
QPushButton:hover, QToolButton:hover {{ background: {c['hover']}; }}
QPushButton:focus, QToolButton:focus, QLineEdit:focus, QPlainTextEdit:focus, QComboBox:focus {{ border: 2px solid {c['accent']}; }}
QPushButton:disabled, QToolButton:disabled {{ color: {c['muted']}; }}
QPushButton#primary, QPushButton:checked {{ background: {c['accent']}; color: {c['accent_text']}; }}
QPushButton#primary:disabled, QPushButton#danger:disabled {{ background: {c['panel']}; color: {c['muted']}; }}
QPushButton#danger {{ color: {c['error']}; background: {c['error_bg']}; }}
QPushButton#nav {{ text-align: left; border: 0; background: transparent; padding: {pad}px; }}
QPushButton#nav:checked {{ background: {c['hover']}; color: {c['text']}; }}
QLineEdit, QComboBox, QSpinBox, QFontComboBox, QPlainTextEdit, QTextBrowser {{ background: {c['input']}; color: {c['text']}; border: 1px solid {c['border']}; border-radius: 6px; padding: {pad}px; selection-background-color: {c['accent']}; selection-color: {c['accent_text']}; }}
QComboBox QAbstractItemView {{ background: {c['panel']}; color: {c['text']}; selection-background-color: {c['hover']}; }}
QTextBrowser#answerCanvas {{ background: {c['answer']}; color: {c['text']}; border: 1px solid {c['border']}; padding: {pad}px; }}
QLabel#practiceQuestion {{ background: {c['panel']}; border: 1px solid {c['border']}; padding: 14px; border-radius: 8px; font-size: 22px; }}
QCheckBox {{ spacing: 8px; padding: 4px 0; }}
QProgressBar {{ background: {c['input']}; border: 1px solid {c['border']}; border-radius: 3px; max-height: 8px; }}
QProgressBar::chunk {{ background: {c['accent']}; }}
QScrollArea {{ border: 0; }}
QSplitter::handle {{ background: {c['border']}; }}
QMenu, QMenuBar {{ background: {c['panel']}; color: {c['text']}; }}
QMenu::item:selected {{ background: {c['hover']}; }}
QToolTip {{ background: {c['panel']}; color: {c['text']}; border: 1px solid {c['border']}; }}
QWidget#errorBanner {{ background: {c['error_bg']}; color: {c['error']}; border: 1px solid {c['error']}; border-radius: 6px; }}
"""


def document_style(name, size=22, family="Segoe UI"):
    c = COLORS[name]
    family = family.replace("'", "").replace('"', '')
    return f"body {{ color: {c['text']}; font-family: '{family}'; font-size: {size}px; }} p {{ margin: 8px 0 12px; }} h1,h2,h3 {{ color: {c['accent']}; margin: 12px 0 8px; }} li {{ margin: 6px 0; }} pre {{ background: {c['code']}; padding: 12px; white-space: pre-wrap; }} code,pre {{ font-family: Consolas, 'Cascadia Mono', monospace; }} a {{ color: {c['accent']}; }} .summary {{ font-size: {size + 4}px; font-weight: 600; }}"


def apply_theme(app, choice, compact=False, family="Segoe UI"):
    name = resolved_theme(choice, app)
    c = COLORS[name]
    palette = QPalette()
    for role, key in ((QPalette.ColorRole.Window, 'bg'), (QPalette.ColorRole.Base, 'input'),
                      (QPalette.ColorRole.AlternateBase, 'panel'), (QPalette.ColorRole.Text, 'text'),
                      (QPalette.ColorRole.WindowText, 'text'), (QPalette.ColorRole.Button, 'panel'),
                      (QPalette.ColorRole.ButtonText, 'text'), (QPalette.ColorRole.Highlight, 'accent'),
                      (QPalette.ColorRole.HighlightedText, 'accent_text'), (QPalette.ColorRole.ToolTipBase, 'panel'),
                      (QPalette.ColorRole.ToolTipText, 'text'), (QPalette.ColorRole.Link, 'accent')):
        palette.setColor(role, QColor(c[key]))
    app.setPalette(palette)
    app.setFont(QFont(family, 10))
    app.setStyleSheet(stylesheet(name, compact, family))
    return name

# Overlay is intentionally dark regardless of the Standard view theme.
OVERLAY = dict(panel='#14161b', raised='#1b1e25', border='#2b303b', text='#e8eaf0',
               muted='#a3abbd', accent='#8aa4ff', success='#3ddc97', red='#c9252d',
               white='#ffffff', ink='#101218', keyword='#c8a6ff', types='#72dccc',
               function='#9fc5ff', number='#ffcf89', comment='#a3abbd')
ACCENTS = {'Periwinkle': '#8aa4ff', 'Mint': '#83dbbe', 'Lavender': '#c4a5ff', 'Sand': '#edc58b'}


def overlay_styles(accent='Periwinkle'):
    c = dict(OVERLAY, accent=ACCENTS.get(accent, OVERLAY['accent']))
    return f"""
QWidget#overlayRoot {{ background: {c['ink']}; color: {c['text']}; font-family: Inter, 'Segoe UI'; font-size: 13px; }}
QWidget#overlayRoot QFrame#panel {{ background: {c['panel']}; border: 1px solid {c['border']}; border-radius: 16px; }}
QWidget#overlayRoot QLabel {{ color: {c['text']}; background: transparent; border: 0; }}
QWidget#overlayRoot QLabel[muted="true"] {{ color: {c['muted']}; }}
QWidget#overlayRoot QPushButton, QWidget#overlayRoot QComboBox, QWidget#overlayRoot QLineEdit {{ background: {c['raised']}; color: {c['text']}; border: 1px solid {c['border']}; border-radius: 10px; padding: 4px 8px; min-height: 28px; }}
QWidget#overlayRoot QPushButton:focus, QWidget#overlayRoot QLineEdit:focus, QWidget#overlayRoot QComboBox:focus {{ border: 2px solid {c['accent']}; }}
QWidget#overlayRoot QPushButton#primary, QWidget#overlayRoot QPushButton:checked, QWidget#overlayRoot QLabel#mark {{ background: {c['accent']}; color: {c['ink']}; border-radius: 10px; }}
QWidget#overlayRoot QLabel#timer {{ background: {c['red']}; color: {c['white']}; padding: 5px 8px; border-radius: 10px; }}
QWidget#overlayRoot QFrame#divider {{ background: {c['border']}; border: 0; }}
QWidget#overlayRoot QFrame#caret {{ background: {c['accent']}; border: 0; }}
QWidget#overlayRoot QTextBrowser {{ background: {c['panel']}; color: {c['text']}; border: 0; padding: 8px; }}
QWidget#overlayRoot QPushButton:disabled {{ color: {c['muted']}; }}
"""
