import json
from PySide6.QtCore import Qt
from PySide6.QtGui import QKeySequence
from test_ui import window, seed
from conftest import pump
from compass.overlay import fences, DEFAULT_SHORTCUTS
from compass.themes import OVERLAY, ACCENTS


def test_incremental_fences():
    for suffix in ('', 'r', 'return 1\n', 'return 1\n```'):
        result=fences('Opening.\n```python\n'+suffix)
        assert len(result)==1 and result[0]['language']=='python'
        assert result[0]['complete']==suffix.endswith('```')
    assert fences('`inline`')==[]


def test_overlay_views_and_geometry_persistence(window,app):
    window.set_shell('Overlay'); app.processEvents()
    assert window.windowFlags() & Qt.WindowType.FramelessWindowHint
    assert window.overlay.toolbar.height()==54
    window.resize(820,600); window.save_settings()
    data=json.loads(window.config_path.read_text())
    assert data['shell_mode']=='Overlay' and data['shell_geometries']['Overlay'][2:]==[820,600]
    window.set_shell('Compact bar'); app.processEvents()
    assert window.overlay.compact and window.overlay.state=='idle'
    window.set_shell('Standard'); app.processEvents()
    assert not window.windowFlags() & Qt.WindowType.FramelessWindowHint
    assert window.centralWidget() is window.standard_shell


def test_compact_states_and_real_meter(window,app):
    window.set_shell('Compact bar'); overlay=window.overlay
    assert overlay.state=='idle'
    window.session=object(); window.meter.setValue(65); window.interim.setText('How would you')
    overlay.sync()
    assert overlay.state=='listening' and overlay.level.level==65
    assert 'How would you' in overlay.compact_text.text()
    window.busy.add('answer'); window.answer_workspace.begin(1,'How would you test?')
    window.answer_workspace.update_answer(1,'A partial answer','streaming'); overlay.sync()
    assert overlay.state=='answering' and 'partial answer' in overlay.browser.toPlainText()
    window.busy.clear(); window.session=None


def test_history_and_scrolling_overlay(window,app):
    w=window.answer_workspace
    w.begin(1,'First'); w.update_answer(1,'\n\n'.join('First answer '+str(i) for i in range(80)),'done')
    window.set_shell('Overlay'); app.processEvents(); o=window.overlay; o.sync(); o.browser.jump()
    bar=o.browser.verticalScrollBar(); bar.setValue(bar.maximum()//3)
    assert not o.browser.follow
    w.begin(2,'Second'); w.update_answer(2,'Second response'); o.sync()
    assert 'First answer' in o.browser.toPlainText() and not o.browser.follow
    o.jump_latest(); assert 'Second response' in o.browser.toPlainText()
    o.navigate(-1); assert 'First answer' in o.browser.toPlainText()


def test_shortcuts_remapping_local_and_conflicts(window):
    assert window.set_shortcut('Screenshot','Ctrl+Alt+S')
    assert any(s.key()==QKeySequence('Ctrl+Alt+S') for s in window.shortcuts)
    assert all(s.context()==Qt.ShortcutContext.WindowShortcut for s in window.shortcuts)
    assert not window.set_shortcut('Chat','Ctrl+Alt+S')
    window.save_settings(); assert json.loads(window.config_path.read_text())['shortcuts']['Screenshot']=='Ctrl+Alt+S'


def test_capture_reapplied_after_native_changes(window,app,monkeypatch):
    calls=[]
    monkeypatch.setattr('compass.ui.set_capture_protection',lambda hwnd,on:(calls.append((hwnd,on)) or (True,'OK')))
    for mode in ('Overlay','Compact bar','Standard'):
        previous=len(calls); window.set_shell(mode); app.processEvents(); assert len(calls)>previous and calls[-1][1]
    previous=len(calls); window.on_top.setChecked(True); app.processEvents(); assert len(calls)>previous


def test_overlay_display_does_not_mutate_prompt_or_context(window,app):
    seed(window); config=window.config(); transcript=list(window.transcript)
    window.set_shell('Overlay'); o=window.overlay
    window.answer_workspace.begin(1,'Question')
    window.answer_workspace.update_answer(1,'Direct answer.\n\n## Key points\n- Use `inputs`.\n\n```python\ndef f(x):\n return 3 # note\n')
    o.sync(); assert 'Key steps' in o.browser.toPlainText() and 'Code' in o.browser.toPlainText()
    o.code_copy.click(); assert 'def f(x)' in app.clipboard().text()
    assert window.config()==config and window.transcript==transcript


def test_first_words_uses_overlay_paint(window,app):
    window.set_shell('Overlay')
    window.turn_timing=window.latency.new('manual')
    window.latency.mark(window.turn_timing,'auto_triggered')
    window.answer_epoch=1
    window.answer_workspace.begin(1,'How would you test?')
    window.answer_workspace.entries[-1].timing=window.turn_timing
    window.answer_workspace.update_answer(1,'I would test the boundaries.','streaming')
    window.overlay.sync()
    pump(app,lambda:'first_render' in window.turn_timing.stamps)
    window.overlay.sync()
    assert window.overlay.first_words.text().startswith('First words in ')
