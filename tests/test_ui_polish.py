import json

import pytest
from PySide6.QtCore import Qt, QUrl
from PySide6.QtGui import QFont

from test_ui import window, seed
from conftest import pump
from compass.reading import AnswerWorkspace, RichAnswer, key_points_first
from compass.themes import COLORS
from compass.ui import MainWindow


def test_themes_palette_and_reading_font(window, app):
    seed(window)
    original = window.config()
    for name in ('Light', 'Dark', 'High contrast', 'Follow Windows'):
        window.theme_choice.setCurrentText(name)
        app.processEvents()
        assert window.theme_name in COLORS
        assert app.palette().window().color().name() == COLORS[window.theme_name]['bg']
        assert window.answer_view.theme == window.theme_name
    window.font_choice.setCurrentFont(QFont('DejaVu Sans'))
    assert window.answer_view.family == window.font_choice.currentFont().family()
    assert window.config() == original


def test_view_presets_preferences_and_restore(window, app):
    window.go(2)
    for name, orientation, visible in [('Side by side', Qt.Orientation.Horizontal, True),
                                      ('Stacked', Qt.Orientation.Vertical, True),
                                      ('Focus', Qt.Orientation.Horizontal, False)]:
        window.set_preset(name)
        app.processEvents()
        if name != 'Focus':
            assert window.coach_splitter.orientation() == orientation
        assert window.transcript_panel.isVisible() == visible
    window.theme_choice.setCurrentText('Dark')
    window.compact_action.setChecked(True)
    window.answer_workspace.key_first.setChecked(False)
    window.save_settings()
    data = json.loads(window.config_path.read_text())
    assert data['view_preset'] == 'Focus' and data['compact'] is True
    assert data['theme'] == 'Dark' and data['key_points_first'] is False
    w = MainWindow(app)
    try:
        pump(app, lambda: not w.busy)
        assert w.layout_mode.currentText() == 'Focus'
        assert w.theme_choice.currentText() == 'Dark'
        assert w.compact_action.isChecked()
        assert not w.answer_workspace.key_first.isChecked()
    finally:
        w.closed = True; w.close()


def test_answer_history_keeps_reader_position_and_new_stream(app):
    workspace = AnswerWorkspace()
    workspace.resize(900, 500); workspace.show(); app.processEvents()
    workspace.begin(1, 'First question', 0)
    workspace.update_answer(1, 'First **answer**', 'done')
    workspace.begin(2, 'Second question', 1)
    workspace.update_answer(2, 'Second answer', 'streaming')
    assert workspace.selected == 0
    assert 'First answer' in workspace.browser.toPlainText()
    assert workspace.jump_latest.isVisible()
    workspace.latest()
    assert workspace.selected == 1 and 'Second answer' in workspace.browser.toPlainText()
    workspace.previous.click()
    assert workspace.selected == 0
    workspace.next.click()
    assert workspace.selected == 1
    workspace.history.setCurrentIndex(0)
    workspace.cancel(2, discard=True)
    assert 'First answer' in workspace.browser.toPlainText()
    workspace.close()


def test_formatted_stream_code_copy_and_summary(app):
    workspace = AnswerWorkspace(); workspace.show()
    markdown = 'A direct **opening**.\n\n## Details\nMore detail.\n\n## Key points\n- **Test** carefully\n- Verify results\n\n```python\nprint("hello")\n```\n'
    workspace.begin(1, 'How would you test?')
    workspace.update_answer(1, markdown)
    app.processEvents()
    text = workspace.browser.toPlainText()
    assert text.index('Key points') < text.index('Details')
    assert '**' not in text
    assert 'monospace' in workspace.browser.toHtml()  # Qt normalizes pre blocks on HTML export
    assert 'font-weight:700' in workspace.browser.toHtml() or 'font-weight:600' in workspace.browser.toHtml()
    assert workspace.copy_code.isVisible()
    workspace.copy_code.click()
    assert app.clipboard().text() == 'print("hello")'
    workspace.browser.copy_anchor(QUrl('ally-code:0'))
    assert app.clipboard().text() == 'print("hello")'
    workspace.close()


def test_scroll_up_pauses_and_jump_resumes(app):
    browser = RichAnswer(); browser.resize(700, 240); browser.show()
    body = '\n\n'.join(f'Paragraph {i} with a longer answer.' for i in range(80))
    browser.render(body); app.processEvents(); browser.jump()
    bar = browser.verticalScrollBar()
    assert bar.maximum() > 0 and bar.value() == bar.maximum()
    bar.setValue(bar.maximum() // 3)  # same valueChanged route used by scrollbar drag
    assert not browser.follow
    position = bar.value()
    browser.render(body + '\n\nMore words arrive.'); app.processEvents()
    assert not browser.follow and bar.value() == position
    browser.jump(); app.processEvents()
    assert browser.follow and bar.value() == bar.maximum()
    browser.close()


def test_banner_plain_language_fix_and_stale_errors(window, app):
    window.on_failed('google_test', 'HTTP 401: rejected')
    assert not window.status_strip.banner.isHidden()
    assert 'Check the API key' in window.status_strip.error.text()
    window.status_strip.fix.click()
    assert window.stack.currentIndex() == 4
    assert window.settings_search.text() == 'API & audio'
    window.status_strip.dismiss.click()
    assert window.status_strip.banner.isHidden()
    window.on_failed('answer:99999', 'stale failure')
    assert window.status_strip.banner.isHidden()


def test_settings_search_sections(window):
    window.go(4)
    window.settings_search.setText('opacity')
    visible = [terms for panel, terms in window.settings_sections if not panel.isHidden()]
    assert len(visible) == 1 and 'appearance' in visible[0]
    window.settings_search.setText('no_such_setting')
    assert not window.no_settings.isHidden()
    window.settings_search.clear()
    assert all(not panel.isHidden() for panel, _ in window.settings_sections)


def test_transcript_reask_and_answer_link(window, app, monkeypatch):
    seed(window)
    window.on_event('final', 'How do you review a model?')
    called = []
    monkeypatch.setattr(window, 'generate', lambda question: called.append(question))
    window.transcript_view.clicked(QUrl('ally-turn:0'))
    assert called == ['How do you review a model?']
    assert window.selected_turn == 0
    assert 'Answering this turn' in window.transcript_view.toPlainText()
    assert 'edit' in window.question_state.text().lower()


def test_mini_bar_restores_full_window_and_capture(window, app, monkeypatch):
    calls = []
    monkeypatch.setattr('compass.ui.set_capture_protection', lambda hwnd, enabled: (calls.append((hwnd, enabled)) or (True, 'OK')))
    window.resize(1200, 800); app.processEvents()
    before = (window.width(), window.height())
    window.mini_action.setChecked(True); app.processEvents()
    assert window.mini and window.minimumWidth() == 320
    assert not window.statusBar().isVisible()
    assert calls
    window.mini_action.setChecked(False); app.processEvents()
    assert not window.mini and window.statusBar().isVisible()
    assert (window.width(), window.height()) == before
    window.theme_choice.setCurrentText('High contrast')
    window.on_top.setChecked(True); app.processEvents()
    assert calls[-1][1] is True


def test_follow_windows_respects_contrast_and_theme():
    from types import SimpleNamespace
    from compass.themes import resolved_theme
    accessibility = SimpleNamespace(contrastPreference=lambda: SimpleNamespace(name='HighContrast'))
    hints = SimpleNamespace(accessibility=lambda: accessibility, colorScheme=lambda: Qt.ColorScheme.Light)
    app = SimpleNamespace(styleHints=lambda: hints)
    assert resolved_theme('Follow Windows', app) == 'High contrast'
    assert resolved_theme('Dark', app) == 'Dark'


def test_final_segments_form_one_visual_turn(window):
    window.on_event('final', 'Tell me about')
    window.on_event('final', 'your QA experience?')
    window.on_event('utterance', 'Tell me about your QA experience?')
    assert len(window.transcript_view.turns) == 1
    window.on_event('final', 'What would you improve?')
    window.on_event('utterance', 'What would you improve?')
    assert len(window.transcript_view.turns) == 2
