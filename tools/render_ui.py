"""Render synthetic UI examples offscreen. No API calls or private context."""
import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from pathlib import Path
import tempfile
from PySide6.QtWidgets import QApplication
from compass import ui


def main():
    output = Path(__file__).resolve().parents[1] / 'docs/screenshots'
    output.mkdir(parents=True, exist_ok=True)
    app = QApplication([])
    ui.MainWindow.refresh_devices = lambda _: None
    with tempfile.TemporaryDirectory() as preferences:
        os.environ['LOCALAPPDATA'] = preferences
        window = ui.MainWindow(app)
        window.resize(1440, 1180)
        window.show(); window.go(2); window.set_preset('Side by side')
        window.transcript_view.appendPlainText('[14:32:08] How would you test a new API?')
        window.transcript_view.finish_turn('How would you test a new API?')
        window.transcript_view.appendPlainText('[14:33:12] How would you investigate intermittent failures?')
        window.transcript_view.finish_turn('How would you investigate intermittent failures?')
        window.question.setPlainText('How would you investigate intermittent failures?')
        window.question_state.setText('Latest detected question · edit before answering')
        workspace = window.answer_workspace
        workspace.begin(1, 'How would you test a new API?', 0)
        workspace.update_answer(1, 'I would cover expected behavior, edge cases, and failure responses.', 'done')
        workspace.begin(2, 'How would you investigate intermittent failures?', 1)
        workspace.update_answer(2, 'I would **reproduce the failure**, isolate the conditions, and verify the fix.\n\n## Key points\n- Capture **logs and request IDs**.\n- Compare passing and failing inputs.\n- Add a regression check.\n\n## Example check\n```python\nassert response.status_code == 200\nassert "result" in response.json()\n```\n\n## Resume evidence / confirm\nConfirm the tools and project examples you have used.', 'done')
        workspace.latest(); window.status_strip.set_answer('done')
        window.footer.setText('Synthetic demo · no API keys or private documents · no network calls')
        for theme, filename in [('Dark', 'dark.png'), ('Light', 'light.png'), ('High contrast', 'high-contrast.png')]:
            window.theme_choice.setCurrentText(theme)
            for _ in range(4): app.processEvents()
            workspace.browser.verticalScrollBar().setValue(0)
            window.grab().save(str(output / filename))
        window.theme_choice.setCurrentText('Dark'); window.go(4)
        window.settings_search.setText('appearance')
        for _ in range(3): app.processEvents()
        window.grab().save(str(output / 'settings.png'))
        window.go(2); window.mini_action.setChecked(True)
        for _ in range(3): app.processEvents()
        window.mini_browser.verticalScrollBar().setValue(0)
        window.grab().save(str(output / 'mini-bar.png'))
        window.mini_action.setChecked(False)
        window.closed = True; window.close(); app.processEvents()


if __name__ == '__main__':
    main()
