"""Display-only answer history, Markdown rendering and turn navigation."""
from dataclasses import dataclass
import html
import re

from PySide6.QtCore import Qt, Signal, QTimer, QEvent
from PySide6.QtGui import QTextDocument, QTextCursor, QFont, QTextCharFormat, QColor
from PySide6.QtWidgets import (QApplication, QWidget, QVBoxLayout, QHBoxLayout, QTextBrowser,
                              QComboBox, QPushButton, QLabel, QCheckBox)
from .themes import document_style, COLORS


@dataclass
class AnswerEntry:
    epoch: int
    question: str
    text: str = ""
    state: str = "waiting"
    turn: int | None = None
    scroll: int = 0
    follow: bool = True


def key_points_first(text):
    """Reorder existing sections only. Never infer a new summary or alter prompts."""
    sections, buffer, fenced = [], [], False
    for line in text.splitlines(keepends=True):
        if line.startswith('```'):
            fenced = not fenced
        if not fenced and re.match(r'^#{1,3} ', line) and buffer:
            sections.append(''.join(buffer)); buffer = []
        buffer.append(line)
    if buffer:
        sections.append(''.join(buffer))
    if not sections:
        return text
    points = [section for section in sections if re.match(r'^#{1,3} Key points\b', section, re.I)]
    # Preserve the opening, then move only the existing Key points section.
    first = sections[0] if sections[0] not in points else ''
    ordered = [first, *points, *(section for section in sections[1:] if section not in points)]
    return ''.join(ordered) if points else text



class RichAnswer(QTextBrowser):
    followChanged = Signal(bool)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.follow = True
        self.updating = False
        self.last_scroll = 0
        self.key_first = True
        self.theme = "Dark"
        self.text_size = 22
        self.family = "Segoe UI"
        self.source = ""
        self.code_blocks = []
        self.setObjectName("answerCanvas")
        self.setOpenExternalLinks(False)
        self.setOpenLinks(False)
        self.anchorClicked.connect(self.copy_anchor)
        self.verticalScrollBar().valueChanged.connect(self.scrolled)
        self.viewport().installEventFilter(self)

    def eventFilter(self, watched, event):
        if event.type() == QEvent.Type.Wheel and event.angleDelta().y() > 0:
            self.pause()
        if event.type() == QEvent.Type.KeyPress and event.key() in (Qt.Key.Key_Up, Qt.Key.Key_PageUp, Qt.Key.Key_Home):
            self.pause()
        return super().eventFilter(watched, event)

    def scrolled(self, value):
        if not self.updating and value < self.last_scroll:
            self.pause()
        self.last_scroll = value

    def pause(self):
        self.follow = False
        self.followChanged.emit(False)

    def jump(self):
        self.follow = True
        self.updating = True
        self.moveCursor(QTextCursor.MoveOperation.End)
        self.verticalScrollBar().setValue(self.verticalScrollBar().maximum())
        self.last_scroll = self.verticalScrollBar().value()
        self.updating = False
        self.followChanged.emit(True)

    def setMarkdown(self, text):
        self.render(text)

    def render(self, text):
        self.source = text
        bar = self.verticalScrollBar()
        old_scroll = bar.value()
        cursor = self.textCursor()
        selection = (cursor.anchor(), cursor.position())
        display = key_points_first(text) if self.key_first else text
        self.code_blocks = re.findall(r'(?ms)^```[^\n]*\n(.*?)(?:^```\s*$|\Z)', display)
        number = [0]
        def code_link(match):
            index = number[0]; number[0] += 1
            return f"\n[Copy code {index + 1}](ally-code:{index})\n\n" + match.group(0)
        display = re.sub(r'(?ms)^```[^\n]*\n.*?(?:^```\s*$|\Z)', code_link, display)
        document = QTextDocument()
        font = QFont(self.family)
        font.setPointSizeF(self.text_size * .75)
        document.setDefaultFont(font)
        # No arbitrary HTML or resource loading from provider text.
        document.setMarkdown(display, QTextDocument.MarkdownFeature.MarkdownDialectGitHub | QTextDocument.MarkdownFeature.MarkdownNoHTML)
        rendered = document.toHtml()
        if self.key_first:
            rendered = re.sub(r'<p\b', '<p class="summary"', rendered, count=1)
        self.updating = True
        self.document().setDefaultStyleSheet(document_style(self.theme, self.text_size, self.family))
        self.setHtml(rendered)
        if self.key_first and self.document().firstBlock().isValid():
            summary = QTextCursor(self.document().firstBlock())
            summary.select(QTextCursor.SelectionType.BlockUnderCursor)
            style = QTextCharFormat(); style.setFontPointSize((self.text_size + 4) * .75)
            summary.mergeCharFormat(style)
        # Qt's Markdown exporter embeds a default link foreground; use the theme instead.
        block = self.document().begin()
        while block.isValid():
            fragment = block.begin()
            while not fragment.atEnd():
                part = fragment.fragment()
                if part.isValid() and part.charFormat().isAnchor():
                    cursor = QTextCursor(self.document())
                    cursor.setPosition(part.position())
                    cursor.setPosition(part.position() + part.length(), QTextCursor.MoveMode.KeepAnchor)
                    style = QTextCharFormat(); style.setForeground(QColor(COLORS[self.theme]['accent']))
                    cursor.mergeCharFormat(style)
                fragment += 1
            block = block.next()
        self.document().setDocumentMargin(12)
        if self.follow:
            self.moveCursor(QTextCursor.MoveOperation.End)
        if not self.follow:
            cursor = self.textCursor()
            limit = self.document().characterCount() - 1
            cursor.setPosition(min(selection[0], limit))
            cursor.setPosition(min(selection[1], limit), QTextCursor.MoveMode.KeepAnchor)
            self.setTextCursor(cursor)
        bar.setValue(bar.maximum() if self.follow else old_scroll)
        self.last_scroll = bar.value()
        self.updating = False
        if self.follow:
            QTimer.singleShot(0, self.follow_bottom)

    def follow_bottom(self):
        if self.follow:
            self.updating = True
            self.verticalScrollBar().setValue(self.verticalScrollBar().maximum())
            self.last_scroll = self.verticalScrollBar().value()
            self.updating = False

    def copy_anchor(self, url):
        if url.scheme() == 'ally-code':
            try:
                QApplication.clipboard().setText(self.code_blocks[int(url.path())].rstrip('\n'))
            except (ValueError, IndexError):
                pass

    def loadResource(self, kind, url):
        # Model output cannot request images, local files or network resources.
        return None


class AnswerWorkspace(QWidget):
    selectedTurn = Signal(object)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.entries = []
        self.selected = -1
        self.active_epoch = None
        layout = QVBoxLayout(self); layout.setContentsMargins(0, 0, 0, 0); layout.setSpacing(8)
        row = QHBoxLayout()
        self.previous = QPushButton("← Previous")
        self.next = QPushButton("Next →")
        self.history = QComboBox(); self.history.setMinimumWidth(0)
        self.history.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        self.history.setMinimumContentsLength(10)
        row.addWidget(self.previous); row.addWidget(self.history, 1); row.addWidget(self.next)
        layout.addLayout(row)
        self.context = QLabel("No answer yet"); self.context.setWordWrap(True)
        self.context.setTextFormat(Qt.TextFormat.PlainText)
        layout.addWidget(self.context)
        row = QHBoxLayout()
        self.key_first = QCheckBox("Key points first"); self.key_first.setChecked(True)
        self.code_choice = QComboBox(); self.code_choice.setMinimumWidth(0)
        self.copy_code = QPushButton("Copy code")
        self.jump_latest = QPushButton("Jump to latest")
        row.addWidget(self.key_first); row.addStretch(); row.addWidget(self.code_choice)
        row.addWidget(self.copy_code); row.addWidget(self.jump_latest)
        layout.addLayout(row)
        self.browser = RichAnswer()
        self.browser.setMinimumHeight(120)
        layout.addWidget(self.browser, 1)
        self.previous.clicked.connect(lambda: self.select(self.selected - 1))
        self.next.clicked.connect(lambda: self.select(self.selected + 1))
        self.history.currentIndexChanged.connect(self.select)
        self.key_first.toggled.connect(self.change_order)
        self.copy_code.clicked.connect(self.copy_current_code)
        self.jump_latest.clicked.connect(self.latest)
        self.browser.followChanged.connect(lambda _: self.refresh_controls())
        self.refresh_controls()

    def remember_position(self):
        if 0 <= self.selected < len(self.entries):
            entry = self.entries[self.selected]
            entry.scroll = self.browser.verticalScrollBar().value()
            entry.follow = self.browser.follow

    def begin(self, epoch, question, turn=None):
        self.active_epoch = epoch
        self.entries.append(AnswerEntry(epoch, question, turn=turn))
        self.history.blockSignals(True)
        self.history.addItem(question[:70])
        self.history.blockSignals(False)
        # Preserve whichever answer the user is reading, including its scroll position.
        if self.selected < 0 or self.entries[self.selected].state == 'cancelled':
            self.select(len(self.entries) - 1)
        self.refresh_controls()

    def update_answer(self, epoch, text, state="streaming"):
        for index, entry in enumerate(self.entries):
            if entry.epoch == epoch:
                entry.text, entry.state = text, state
                if index == self.selected:
                    self.browser.render(text)
                    self.context.setText(f"{entry.state.title()} · {entry.question}")
                self.refresh_controls()
                return index == self.selected
        return False

    def cancel(self, epoch, discard=False):
        for index, entry in enumerate(self.entries):
            if entry.epoch == epoch:
                entry.state = 'cancelled'
                if discard:
                    entry.text = ''
                if index == self.selected:
                    self.browser.render(entry.text or 'Answer cancelled.')
                    self.context.setText('Cancelled · ' + entry.question)
        self.refresh_controls()

    def select(self, index):
        if not 0 <= index < len(self.entries):
            return
        self.remember_position()
        self.selected = index
        entry = self.entries[index]
        self.history.blockSignals(True); self.history.setCurrentIndex(index); self.history.blockSignals(False)
        self.browser.follow = entry.follow
        self.browser.render(entry.text)
        if not entry.follow:
            self.browser.updating = True
            self.browser.verticalScrollBar().setValue(entry.scroll)
            self.browser.updating = False
        self.context.setText(f"{entry.state.title()} · {entry.question}")
        self.selectedTurn.emit(entry.turn)
        self.refresh_controls()

    def latest(self):
        self.select(len(self.entries) - 1)
        self.browser.jump()
        self.refresh_controls()

    def refresh_controls(self):
        self.previous.setEnabled(self.selected > 0)
        self.next.setEnabled(0 <= self.selected < len(self.entries) - 1)
        unseen = self.selected != len(self.entries) - 1
        self.jump_latest.setVisible(bool(self.entries) and (unseen or not self.browser.follow))
        codes = self.browser.code_blocks
        choice = self.code_choice.currentIndex()
        self.code_choice.clear()
        self.code_choice.addItems([f"Block {i+1}" for i in range(len(codes))])
        self.code_choice.setCurrentIndex(max(0, min(choice, len(codes) - 1)))
        self.code_choice.setVisible(bool(codes))
        self.copy_code.setVisible(bool(codes))

    def copy_current_code(self):
        index = self.code_choice.currentIndex()
        if 0 <= index < len(self.browser.code_blocks):
            QApplication.clipboard().setText(self.browser.code_blocks[index].rstrip('\n'))

    def change_order(self, enabled):
        self.browser.key_first = enabled
        self.browser.render(self.browser.source)

    def clear(self):
        self.entries.clear(); self.selected = -1; self.active_epoch = None
        self.history.clear(); self.browser.clear(); self.browser.source = ''; self.browser.code_blocks = []
        self.context.setText('No answer yet'); self.refresh_controls()


class TurnTranscript(QTextBrowser):
    reask = Signal(int, str)

    def __init__(self):
        super().__init__()
        self.turns = []
        self.open_turn = False
        self.current_turn = None
        self.setOpenLinks(False); self.setOpenExternalLinks(False)
        self.anchorClicked.connect(self.clicked)
        self.setMinimumWidth(0)

    def setReadOnly(self, value):
        super().setReadOnly(value)

    def setPlaceholderText(self, text):
        self._placeholder = text
        super().setPlaceholderText(text)

    def appendPlainText(self, entry):
        match = re.match(r'\[(.*?)\]\s*(.*)', entry, re.S)
        stamp, text = match.groups() if match else ('', entry)
        if self.open_turn and self.turns:
            previous_stamp, previous = self.turns[-1]
            self.turns[-1] = (previous_stamp, previous + ' ' + text)
        else:
            self.turns.append((stamp, text))
        self.open_turn = True
        self.refresh()

    def finish_turn(self, text):
        if self.open_turn and self.turns:
            self.turns[-1] = (self.turns[-1][0], text)
        self.open_turn = False
        self.refresh()

    def refresh(self):
        bar = self.verticalScrollBar()
        follow, position = bar.value() >= bar.maximum() - 2, bar.value()
        rows = []
        for i, (stamp, text) in enumerate(self.turns):
            responding = ' · Answering this turn' if i == self.current_turn else ''
            rows.append(f'<p><b>{html.escape(stamp)}{responding}</b><br>{html.escape(text)}<br><a href="ally-turn:{i}">Re-ask this turn</a></p><hr>')
        self.setHtml(''.join(rows))
        bar.setValue(bar.maximum() if follow else position)

    def mark_turn(self, index):
        self.current_turn = index
        self.refresh()

    def clicked(self, url):
        if url.scheme() == 'ally-turn':
            try:
                index = int(url.path())
                self.reask.emit(index, self.turns[index][1])
            except (ValueError, IndexError):
                pass

    def clear(self):
        self.turns.clear(); self.current_turn = None; self.open_turn = False
        super().clear()
