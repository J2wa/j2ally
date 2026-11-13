"""Floating presentation shell. No capture, prompt or provider logic lives here."""
import re
from PySide6.QtCore import Qt, QTimer, QEvent, QSize
from PySide6.QtGui import (QPainter, QPen, QColor, QIcon, QPixmap, QFontDatabase,
                          QTextCursor, QTextCharFormat, QAccessible, QAccessibleAnnouncementEvent)
from PySide6.QtWidgets import (QWidget, QFrame, QLabel, QPushButton, QVBoxLayout, QHBoxLayout,
                              QComboBox, QLineEdit, QMenu, QApplication, QMessageBox, QSizeGrip)
from .reading import RichAnswer
from .themes import OVERLAY, ACCENTS, overlay_styles, COLORS

DEFAULT_SHORTCUTS = {'Answer': 'Ctrl+Return', 'Question': 'Ctrl+L', 'Screenshot': 'Ctrl+Shift+S',
                     'Chat': 'Ctrl+Shift+C', 'Previous': 'Alt+Left', 'Next': 'Alt+Right',
                     'Clear answer': 'Ctrl+Backspace', 'Clear transcript': 'Ctrl+Shift+Backspace'}


def fences(markdown):
    """Complete and incomplete fenced blocks, without changing source text."""
    result = []; active = None
    for line in markdown.splitlines(keepends=True):
        if line.startswith('```'):
            if active is None:
                active = {'language': line[3:].strip(), 'code': '', 'complete': False}
            else:
                active['complete'] = True; result.append(active); active = None
        elif active is not None:
            active['code'] += line
    if active is not None:
        result.append(active)
    return result


def stroke_icon(name, color):
    # Draw scalable stroke icons at 2x resolution, avoiding emoji/platform glyph changes.
    pix = QPixmap(40, 40); pix.fill(Qt.GlobalColor.transparent); pix.setDevicePixelRatio(2)
    p = QPainter(pix); p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.setPen(QPen(QColor(color), 1.8, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
    paths = {'move': [(3,10,17,10),(10,3,10,17),(3,10,6,7),(3,10,6,13),(17,10,14,7),(17,10,14,13)],
             'expand': [(3,8,3,3),(3,3,8,3),(12,17,17,17),(17,17,17,12),(3,3,8,8),(17,17,12,12)],
             'collapse': [(3,3,8,8),(8,3,8,8),(3,8,8,8),(17,17,12,12),(12,12,17,12),(12,12,12,17)],
             'previous': [(15,10,5,10),(5,10,9,6),(5,10,9,14)],
             'next': [(5,10,15,10),(15,10,11,6),(15,10,11,14)]}
    if name == 'dot':
        p.setBrush(QColor(color)); p.drawEllipse(7,7,6,6)
    elif name == 'more':
        for y in (4,10,16): p.drawEllipse(9,y-1,2,2)
    else:
        for coords in paths.get(name, paths['expand']): p.drawLine(*coords)
    p.end(); return QIcon(pix)


class LevelBars(QWidget):
    def __init__(self):
        super().__init__(); self.level = 0; self.setFixedSize(36,28)
        self.setAccessibleName('System audio level'); self.setAccessibleDescription('Audio input level, 0 to 100')
    def paintEvent(self, event):
        p = QPainter(self); p.setPen(Qt.PenStyle.NoPen)
        for i, height in enumerate((8,16,23,14,9)):
            p.setBrush(QColor(OVERLAY['success'] if self.level > i * 20 else OVERLAY['muted']))
            p.drawRoundedRect(2+i*7, (28-height)//2, 3, height, 1.5, 1.5)


class OverlayView(QWidget):
    def __init__(self, owner, compact=False):
        super().__init__(); self.owner = owner; self.compact = compact; self.setObjectName('overlayRoot')
        self.last_content = None; self.announced = None; self.last_epoch = None; self.caret_on = True
        self.setMouseTracking(True); self.installEventFilter(self)
        self.root = QVBoxLayout(self); self.root.setContentsMargins(6,6,6,6); self.root.setSpacing(10)
        toolbar, row = self.panel(44 if compact else 54)
        self.toolbar = toolbar; toolbar.installEventFilter(self)
        mark = QLabel('A'); mark.setObjectName('mark'); mark.setFixedSize(28,28); mark.setAlignment(Qt.AlignmentFlag.AlignCenter)
        row.addWidget(mark)
        self.audio = self.button('Start listening', self.toggle_audio, row)
        self.model = QComboBox(); self.model.setMaximumWidth(140); self.model.setAccessibleName('Gemini model')
        self.model.currentTextChanged.connect(self.select_model); row.addWidget(self.model)
        self.divider = QFrame(); self.divider.setObjectName('divider'); self.divider.setFixedSize(1,24); row.addWidget(self.divider)
        self.answer = self.button('Answer', owner.ask, row); self.answer.setObjectName('primary')
        self.screenshot = self.button('Screenshot', owner.capture_screen, row)
        self.chat_button = self.button('Chat', self.toggle_chat, row)
        self.compact_text = QLabel(''); self.compact_text.setMinimumWidth(0); row.addWidget(self.compact_text,1); self.compact_text.setVisible(compact)
        self.compact_meter = LevelBars(); row.addWidget(self.compact_meter); self.compact_meter.setVisible(compact)
        row.addStretch()
        self.move = self.icon('move', 'Move window (drag)', row); self.move.installEventFilter(self)
        self.compact_button = self.icon('collapse', 'Switch to compact bar', row)
        self.compact_button.clicked.connect(lambda: owner.set_shell('Compact bar'))
        self.expand = self.icon('expand', 'Return to Standard view', row)
        self.expand.clicked.connect(lambda: owner.set_shell('Overlay' if compact else 'Standard'))
        self.more = self.icon('more', 'More options', row)
        menu = QMenu(self.more)
        for title, callback in [('Standard', lambda: owner.set_shell('Standard')),
                                ('Overlay', lambda: owner.set_shell('Overlay')),
                                ('Cancel answer', owner.cancel_answer), ('Export session notes', owner.export_notes),
                                ('Settings', self.settings)]:
            menu.addAction(title, callback)
        top = menu.addAction('Always on top'); top.setCheckable(True); top.setChecked(owner.on_top.isChecked()); top.toggled.connect(owner.on_top.setChecked)
        protected = menu.addAction('Exclude supported screen captures'); protected.setCheckable(True); protected.setChecked(owner.protection.isChecked()); protected.toggled.connect(owner.protection.setChecked)
        self.more.setMenu(menu)
        self.timer_pill = QLabel('00:00'); self.timer_pill.setObjectName('timer'); self.timer_pill.setAccessibleName('Session timer')
        row.addWidget(self.timer_pill)
        listening, row = self.panel(46); self.listening_panel = listening
        self.level = LevelBars(); row.addWidget(self.level)
        self.listening = QLabel('Listening to system audio...'); self.listening.setMinimumWidth(0)
        self.listening.setAccessibleName('Listening status'); self.listening.setTextFormat(Qt.TextFormat.PlainText); row.addWidget(self.listening, 1)
        self.clear_transcript = self.button('Clear', lambda: self.clear('transcript'), row)
        self.transcript = self.icon('expand', 'Expand transcript', row)
        self.transcript.clicked.connect(self.open_transcript)
        self.chat = QLineEdit(); self.chat.setPlaceholderText('Ask a follow-up using your existing context; Enter sends')
        self.chat.setAccessibleName('Follow-up question'); self.chat.returnPressed.connect(self.send_chat)
        self.root.addWidget(self.chat); self.chat.hide()
        panel = QFrame(); panel.setObjectName('panel'); self.answer_panel = panel
        layout = QVBoxLayout(panel); layout.setContentsMargins(12,8,12,8); layout.setSpacing(8)
        header = QHBoxLayout(); self.header = header
        self.previous = self.icon('previous', 'Previous answer', header)
        self.next = self.icon('next', 'Next answer', header)
        self.previous.clicked.connect(lambda: self.navigate(-1)); self.next.clicked.connect(lambda: self.navigate(1))
        self.counter = QLabel('Answer 0 of 0'); header.addWidget(self.counter); header.addStretch()
        self.first_words = QLabel(''); header.addWidget(self.first_words)
        self.clear_answer = self.button('Clear', lambda: self.clear('answer'), header)
        collapse = self.icon('collapse', 'Collapse answer', header); collapse.clicked.connect(self.collapse_answer)
        self.cancel_button = self.button('Cancel answer', owner.cancel_answer, header)
        layout.addLayout(header)
        question_row = QHBoxLayout(); self.question_row = QWidget(); self.question_row.setLayout(question_row)
        self.question = QLabel('Question:'); self.question.setWordWrap(True); self.question.setTextFormat(Qt.TextFormat.PlainText)
        question_row.addWidget(self.question, 1)
        self.copy_question = self.button('Copy', lambda: QApplication.clipboard().setText(self.current_question()), question_row)
        layout.addWidget(self.question_row)
        self.browser = RichAnswer(); self.browser.setAccessibleName('Coach answer'); self.browser.key_first = False
        layout.addWidget(self.browser, 1)
        self.caret = QFrame(self.browser.viewport()); self.caret.setObjectName('caret'); self.caret.setFixedSize(2,20); self.caret.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents); self.caret.hide()
        self.jump = QPushButton('Jump to latest'); self.jump.clicked.connect(self.jump_latest); layout.addWidget(self.jump)
        self.code_row = QWidget(); code_layout = QHBoxLayout(self.code_row); code_layout.setContentsMargins(0,0,0,0)
        self.language = QComboBox(); self.language.setAccessibleName('Code block language'); code_layout.addWidget(self.language)
        self.code_copy = self.button('Copy code', self.copy_code, code_layout); code_layout.addStretch()
        layout.addWidget(self.code_row)
        footer = QHBoxLayout()
        self.status = QLabel('Ready.'); self.status.setWordWrap(True); self.status.setAccessibleName('Answer status'); self.status.setTextFormat(Qt.TextFormat.PlainText)
        footer.addWidget(self.status,1)
        self.fix = self.button('Fix', self.fix_error, footer)
        self.hint = self.button('Hint only', lambda: owner.style.setCurrentIndex(2), footer); self.hint.setCheckable(True)
        self.hint.clicked.disconnect(); self.hint.clicked.connect(lambda checked: owner.style.setCurrentIndex(2 if checked else 0))
        self.explain = self.button('Explain out loud', lambda: owner.style.setCurrentIndex(1), footer); self.explain.setCheckable(True)
        self.explain.clicked.disconnect(); self.explain.clicked.connect(lambda checked: owner.style.setCurrentIndex(1 if checked else 0))
        self.resize_button = self.button('Resize', self.resize_window, footer)
        self.grip = QSizeGrip(self); self.grip.setAccessibleName('Resize window'); footer.addWidget(self.grip)
        layout.addLayout(footer); self.root.addWidget(panel,1)
        self.blink = QTimer(self); self.blink.setInterval(550); self.blink.timeout.connect(self.blink_caret); self.blink.start()
        self.apply_style(); self.sync()

    def panel(self, height):
        panel = QFrame(); panel.setObjectName('panel'); panel.setFixedHeight(height)
        row = QHBoxLayout(panel); row.setContentsMargins(10,4,10,4); row.setSpacing(6)
        self.root.addWidget(panel); return panel, row

    def button(self, text, callback, row):
        button = QPushButton(text); button.setAccessibleName(text); button.setMinimumHeight(28)
        button.clicked.connect(callback); row.addWidget(button); return button

    def icon(self, name, accessible, row):
        button = self.button('', lambda: None, row); button.setAccessibleName(accessible); button.setToolTip(accessible)
        button.setIcon(stroke_icon(name, OVERLAY['text'])); button.setFixedSize(30,30); return button

    def apply_style(self):
        accent = self.owner.overlay_accent.currentText()
        self.setStyleSheet(overlay_styles(accent))
        c = dict(OVERLAY, accent=ACCENTS[accent])
        COLORS['Overlay'] = dict(bg=c['panel'], panel=c['panel'], input=c['raised'], text=c['text'],
            muted=c['muted'], border=c['border'], accent=c['accent'], accent_text=c['ink'], hover=c['raised'],
            answer=c['panel'], code=c['raised'], error=c['white'], error_bg=c['red'])
        families = QFontDatabase.families()
        self.browser.theme = 'Overlay'; self.browser.family = 'Inter' if 'Inter' in families else 'Segoe UI'
        self.code_family = 'JetBrains Mono' if 'JetBrains Mono' in families else 'Consolas'
        self.last_content = None

    def current_entry(self):
        workspace = self.owner.answer_workspace
        return workspace.entries[workspace.selected] if 0 <= workspace.selected < len(workspace.entries) else None

    def current_question(self):
        entry = self.current_entry(); return entry.question if entry else self.owner.question.toPlainText()

    def sync(self):
        o = self.owner; workspace = o.answer_workspace; entry = self.current_entry()
        listening = bool(o.session) and not o.stopping
        active = 'answer' in o.busy
        self.state = 'answering' if active else 'listening' if listening else 'idle'
        self.level.level = o.meter.value(); self.level.update()
        interim = o.interim.text()
        text = interim or (o.transcript_view.turns[-1][1] if o.transcript_view.turns else 'Listening to system audio...' if listening else 'Ready. Press Start to listen.')
        self.listening.setText(self.fontMetrics().elidedText(text, Qt.TextElideMode.ElideRight, max(80,self.width()-200)))
        self.listening.setProperty('muted', bool(interim))
        self.listening.style().unpolish(self.listening); self.listening.style().polish(self.listening)
        self.audio.setText('System audio' if listening else 'Start listening')
        self.audio.setAccessibleName('Stop system audio capture' if listening else 'Start listening')
        self.audio.setEnabled(o.stop_btn.isEnabled() if listening else o.start_btn.isEnabled())
        self.audio.setIcon(stroke_icon('dot', OVERLAY['success'] if listening else OVERLAY['muted']))
        self.timer_pill.setText('• ' + o.elapsed.text().replace('SESSION', '').strip())
        models = [o.google_model.itemText(i) for i in range(o.google_model.count())]
        if o.google_model.currentText() not in models: models.append(o.google_model.currentText())
        self.model.blockSignals(True)
        if [self.model.itemText(i) for i in range(self.model.count())] != models:
            self.model.clear(); self.model.addItems(models)
        self.model.setCurrentText(o.google_model.currentText()); self.model.blockSignals(False)
        self.model.setEnabled(o.google_model.isEnabled())
        self.answer.setEnabled(o.ask_btn.isEnabled()); self.screenshot.setEnabled(o.screenshot_btn.isEnabled())
        self.cancel_button.setEnabled(o.cancel_btn.isEnabled())
        self.previous.setEnabled(workspace.selected > 0); self.next.setEnabled(workspace.selected < len(workspace.entries)-1)
        self.counter.setText(f'Answer {workspace.selected+1} of {len(workspace.entries)}')
        self.question.setText('Question: ' + self.current_question())
        raw = entry.text if entry else ''
        key = (entry.epoch if entry else None,raw,self.owner.answer_font.value(), self.compact)
        if key != self.last_content:
            self.last_content = key
            if self.last_epoch != (entry.epoch if entry else None):
                self.browser.follow = True; self.last_epoch = entry.epoch if entry else None
            self.browser.text_size = 17 if self.compact else o.answer_font.value()
            # Display labels only; the provider text and request prompt are unchanged.
            display = re.sub(r'(?im)^#{1,3} Key points\s*$', '## Key steps', raw)
            if fences(display) and not re.search(r'(?im)^#{1,3} Code', display):
                display = re.sub(r'(?m)^```', '## Code\n```', display, count=1)
            self.browser.render(('## Answer:\n' + display) if display else '')
            self.highlight_code()
            if entry and entry.epoch == o.answer_epoch and o.turn_timing and 'first_render' not in o.turn_timing.stamps:
                o.render_wait = (entry.epoch, o.turn_timing)
            blocks = fences(raw); selected = self.language.currentIndex()
            self.language.clear(); self.language.addItems([b['language'] or 'Code' for b in blocks]); self.language.setCurrentIndex(max(0,selected))
            self.code_row.setVisible(bool(blocks) and not self.compact)
        timing = getattr(entry, 'timing', None)
        measured = o.latency.first_words(timing) if timing else None
        badge = f'First words in {measured/1000:.1f} s' if measured is not None else ''
        self.first_words.setText(badge); self.first_words.setVisible(bool(badge))
        error = not o.status_strip.banner.isHidden()
        state = entry.state if entry else 'idle'
        status = o.status_strip.error.text() if error else 'Streaming...' if active else 'Answer complete. Check it before you use it.' if state == 'done' else 'Answer cancelled.' if state == 'cancelled' else 'Waiting for end of question' if listening else 'Ready.'
        if not error and active and o.fallback_enabled.isChecked():
            status = o.recovery_status.text()
        elif not error and state == 'incomplete':
            status = 'Incomplete draft. Fallback could not finish; check before use.'
        self.status.setText(status + (' · '+badge if self.compact and badge else ''))
        self.fix.setVisible(error)
        self.hint.setChecked(o.style.currentIndex()==2); self.explain.setChecked(o.style.currentIndex()==1)
        self.jump.setVisible(not self.browser.follow or workspace.selected < len(workspace.entries)-1)
        self.responsive_hints()
        if self.compact:
            answering = self.state == 'answering' or bool(entry and entry.text)
            self.answer_panel.setVisible(answering); self.listening_panel.hide()
            self.compact_text.setText(self.fontMetrics().elidedText(self.current_question() if answering else text + (' · Waiting for end of question' if listening else ''), Qt.TextElideMode.ElideRight,max(60,self.width()-340)))
            self.compact_meter.level = self.level.level; self.compact_meter.update()
            self.compact_meter.setVisible(self.state=='listening')
            self.audio.setVisible(self.state=='idle')
            self.counter.setText(self.fontMetrics().elidedText(self.current_question(), Qt.TextElideMode.ElideRight,max(80,self.width()-250)))
            self.timer_pill.setVisible(listening or active)
            self.model.hide(); self.divider.hide(); self.answer.hide(); self.screenshot.hide(); self.chat_button.hide(); self.compact_button.hide()
            self.question_row.setVisible(False); self.hint.hide(); self.explain.hide(); self.resize_button.hide(); self.code_row.hide()
            self.setMinimumHeight(56)
            desired = 240 if answering else 56
            if o.height() < desired or (not answering and o.height()>desired+20): o.resize(o.width(),desired)
        transition = (listening,active,error,state)
        if transition != self.announced:
            self.announced = transition
            try:
                QAccessible.updateAccessibility(QAccessibleAnnouncementEvent(self.status, ("Listening to system audio. " if listening else "Not capturing audio. ") + status))
            except (TypeError, AttributeError):
                self.status.setAccessibleDescription(status)

    def highlight_code(self):
        doc = self.browser.document(); block = doc.begin()
        code_lines = {line for section in fences(self.current_entry().text if self.current_entry() else '') for line in section['code'].splitlines()}
        pattern = re.compile(r'(?P<comment>\#.*|//.*)|(?P<string>"[^"\n]*"|\x27[^\x27\n]*\x27)|(?P<number>\b\d+(?:\.\d+)?\b)|(?P<keyword>\b(?:def|class|return|if|else|for|while|import|from|const|let|function|async|await|public|new|try|except|assert)\b)|(?P<types>\b(?:int|str|float|bool|String|List|None|True|False)\b)|(?P<function>\b\w+(?=\())')
        while block.isValid():
            it = block.begin(); mono = False
            while not it.atEnd():
                frag = it.fragment()
                if frag.isValid() and any('mono' in f.lower() or 'consolas' in f.lower() for f in (frag.charFormat().fontFamilies() or [])):
                    if block.text() in code_lines: mono = True
                    else:
                        cursor = QTextCursor(doc); cursor.setPosition(frag.position()); cursor.setPosition(frag.position()+frag.length(),QTextCursor.MoveMode.KeepAnchor)
                        fmt=QTextCharFormat(); fmt.setFontFamilies([self.code_family]); fmt.setForeground(QColor(OVERLAY['accent'])); fmt.setBackground(QColor(OVERLAY['raised'])); cursor.mergeCharFormat(fmt)
                it += 1
            if mono:
                def apply(start,length,color):
                    cursor = QTextCursor(doc); cursor.setPosition(block.position()+start)
                    cursor.setPosition(block.position()+start+length,QTextCursor.MoveMode.KeepAnchor)
                    fmt = QTextCharFormat(); fmt.setFontFamilies([self.code_family]); fmt.setForeground(QColor(color)); cursor.mergeCharFormat(fmt)
                apply(0,len(block.text()),OVERLAY['accent'])
                for match in pattern.finditer(block.text()):
                    apply(match.start(),len(match.group()),OVERLAY.get(match.lastgroup,OVERLAY['types']))
            block = block.next()

    def responsive_hints(self):
        wide = self.width() >= 1100
        for button,name in ((self.answer,'Answer'),(self.screenshot,'Screenshot'),(self.chat_button,'Chat'),(self.clear_answer,'Clear answer'),(self.clear_transcript,'Clear transcript')):
            hint = self.owner.shortcut_map.get(name,'').replace('Return','Enter')
            button.setToolTip(name + (' · '+hint if hint else ''))
            label = 'Clear' if name.startswith('Clear') else name
            button.setText(label + ('  '+hint if wide and hint else ''))

    def navigate(self, delta):
        self.owner.answer_workspace.select(self.owner.answer_workspace.selected+delta); self.last_content=None; self.sync()
    def jump_latest(self):
        self.owner.answer_workspace.latest(); self.browser.jump(); self.last_content=None; self.sync()
    def toggle_audio(self):
        self.owner.stop_session() if self.owner.session else self.owner.start_session()
    def select_model(self,text): self.owner.google_model.setCurrentText(text)
    def toggle_chat(self):
        self.chat.setVisible(self.chat.isHidden()); self.chat.setFocus()
    def send_chat(self):
        if self.chat.text().strip() and self.owner.ask_btn.isEnabled():
            self.owner.question.setPlainText(self.chat.text()); self.owner.ask(); self.chat.clear()
    def fix_error(self):
        self.owner.set_shell('Standard'); self.owner.fix_setting(self.owner.status_strip.target)
    def settings(self): self.owner.set_shell('Standard'); self.owner.fix_setting('Appearance')
    def open_transcript(self): self.owner.set_shell('Standard'); self.owner.go(2); self.owner.set_preset('Side by side')
    def collapse_answer(self): self.browser.setVisible(self.browser.isHidden())
    def copy_code(self):
        entry=self.current_entry(); blocks=fences(entry.text if entry else '')
        if 0 <= self.language.currentIndex() < len(blocks): QApplication.clipboard().setText(blocks[self.language.currentIndex()]['code'].rstrip('\n'))
    def clear(self,kind):
        if (self.owner.transcript or self.owner.answers or self.current_entry()) and QMessageBox.question(self,'Clear view?', 'Clear this view? Export session notes first if needed. Saved session notes and generation context are retained.') != QMessageBox.StandardButton.Yes: return
        if kind=='answer' and self.current_entry():
            if self.current_entry().epoch == self.owner.answer_epoch and 'answer' in self.owner.busy: self.owner.cancel_answer()
            self.current_entry().text=''; self.last_content=None
        elif kind=='transcript':
            self.listening.setText(''); self.owner.transcript_view.clear(); self.owner.interim.clear()
        self.sync()
    def resize_window(self):
        if not self.owner.windowHandle() or not self.owner.windowHandle().startSystemResize(Qt.Edge.RightEdge | Qt.Edge.BottomEdge):
            self.owner.resize(self.owner.width()+40,self.owner.height()+30)
    def blink_caret(self):
        self.caret_on=not self.caret_on
        cursor = QTextCursor(self.browser.document()); cursor.movePosition(QTextCursor.MoveOperation.End)
        rect = self.browser.cursorRect(cursor)
        self.caret.move(rect.topLeft())
        self.caret.setVisible(self.compact and self.state=='answering' and self.caret_on and self.browser.viewport().rect().contains(rect.topLeft()))
    def eventFilter(self, watched, event):
        if watched is getattr(self,'move',None) and event.type()==QEvent.Type.KeyPress:
            delta = {Qt.Key.Key_Left:(-10,0), Qt.Key.Key_Right:(10,0), Qt.Key.Key_Up:(0,-10), Qt.Key.Key_Down:(0,10)}.get(event.key())
            if delta:
                self.owner.move(self.owner.x()+delta[0],self.owner.y()+delta[1]); return True
        if event.type()==QEvent.Type.MouseButtonPress and event.button()==Qt.MouseButton.LeftButton:
            if watched in (getattr(self,'move',None),getattr(self,'toolbar',None)):
                if self.owner.windowHandle() and self.owner.windowHandle().startSystemMove(): return True
                self.drag_start=event.globalPosition().toPoint()-self.owner.pos(); return True
            if watched is self:
                pos=event.position(); edges=Qt.Edge(0)
                if pos.x()<6: edges |= Qt.Edge.LeftEdge
                if pos.x()>self.width()-6: edges |= Qt.Edge.RightEdge
                if pos.y()<6: edges |= Qt.Edge.TopEdge
                if pos.y()>self.height()-6: edges |= Qt.Edge.BottomEdge
                if edges and self.owner.windowHandle(): return self.owner.windowHandle().startSystemResize(edges)
        if event.type()==QEvent.Type.MouseMove and hasattr(self,'drag_start') and event.buttons() & Qt.MouseButton.LeftButton:
            self.owner.move(event.globalPosition().toPoint()-self.drag_start); return True
        if event.type()==QEvent.Type.MouseButtonRelease and hasattr(self,'drag_start'): del self.drag_start
        return super().eventFilter(watched,event)
