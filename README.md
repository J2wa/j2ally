# ALLY 2.1 for Windows

A native desktop interview coach using your **Google Gemini** key for answer guidance and **Deepgram** key for live speech transcription. Bring your own resume and job description. The app streams suggestions, key talking points, and supporting resume evidence.

## Get started

1. Download **ALLY.exe** and double-click it on Windows 10/11 x64.
2. The first launch unpacks the bundled runtime into `%LOCALAPPDATA%\AcesIntelligence\ALLY`. Allow about a minute and approximately 400 MB of free disk space. Later launches reuse it.
3. No Python installation is required for ALLY.exe. The first launch uses Windows' built-in PowerShell `Expand-Archive`; it downloads nothing. Managed PCs must permit that command.
4. ALLY is unsigned. Windows may show an unknown-publisher prompt. Screen-share privacy and live APIs must be tested on your own Windows PC.
5. Under **API & audio**, paste a **Google AI Studio / Gemini Developer API** key. Click **Load available models**, select a Gemini text model (a Flash model is a good starting point for low latency), optionally use **Test Gemini (optional)**. Vertex AI credentials are not supported by this endpoint.
6. Paste your **Deepgram** key. Select the speech model, language, and the system output used by your meeting. ALLY captures system audio only. Microphone devices are never selected.
7. Under **Your context**, import a PDF, DOCX, TXT or Markdown resume and paste/import the job description. Review the extracted text. Scanned PDFs need OCR outside this app. Context fields have an 80,000-character limit each.
8. Open **Live coach**, confirm permission to transcribe/use assistance, then click **Test + start coach**. Play speech through your selected headphones/speakers during the four-second test. After one successful test, listening starts automatically. Use assistance in settings that allow it.

Only one successful transcription check is needed per app session for the current Deepgram settings and output device. Stop/start reuses the result. Once the live coach has started, subsequent starts and reconnections do not require another audio test. Temporary connection failures reconnect automatically; invalid credentials or settings need correction. Speech during an outage may be missed. The Google answer test is optional. Manual questions and screenshots work with Google credentials and context without a transcription test.

## New in 2.1

- Resizable panels, a collapsible sidebar, automatic stacked layout for narrow windows, and manual layout selection.
- Adjustable transcript/question divider, show/hide feed, reset layout, and saved window/layout preferences.
- Continuous transcription reconnects without repeating the initial audio check.

## Features introduced in 2.0

- A much larger answer canvas, 22 px text by default, adjustable from 16–32 px. **Focus answer** hides the transcript column.
- **Opacity** at the top right adjusts the entire window from 25–100%. Opacity and answer text size are saved with settings.
- **Screenshot → answer** briefly hides ALLY, captures the monitor containing the app, and sends the PNG to Google together with your resume/job context. Move ALLY to another monitor to capture that display. The image stays in memory and is not saved to disk. The click sends the whole visible monitor; close unrelated private content first. Protected windows may appear blank.
- Quicker turn handling: audio endpointing reduced from 650 to 400 ms and post-turn wait from 1,700 to 450 ms. Answers stream as they arrive. Recent transcript context is capped at 6,000 characters. Gemini 2.5 Flash uses a zero thinking budget; Gemini 3.x Flash/Pro uses low thinking. Other model defaults are retained. Model choice, network, prompt length and provider load still determine actual response time; no measured latency guarantee is claimed.
- Auto-coaching is on by default. The default answer style requests 80–140 words. Select Detailed for longer explanations.

## Interview workflow

- **System audio** captures the interviewer from your selected output device, including headphones. Set your meeting's speaker output to match. Close unrelated audio sources: all audio playing on that device is included. This mode does not capture your microphone unless your own voice is played back through the output.
- Final speech appears in the transcript. Edit the latest question as needed and click **Answer · Ctrl+Enter** or press **Ctrl+Enter** while this app has focus. **Ctrl+L** focuses the question field. Shortcuts are local to this app.
- Turn on **Auto-coach after a spoken turn** to generate automatically after a completed utterance and a short pause. Nearby completed chunks are joined; only one answer request runs at a time. It may also react to statements or split a long question at a pause. Use manual mode when you need precise control.
- Choose a short answer, a detailed answer, talking points, or STAR guidance. Select English, Filipino, Taglish, or type another answer language. Spoken language is configured separately in the Deepgram settings. The speech model must support that language; the streaming test verifies compatibility.
- For follow-ups, Google receives the latest question, up to the latest 6,000 transcript characters, your resume, and the job description. The prompt tells it to avoid inventing personal experience and to identify missing evidence. AI suggestions can still be wrong; check them before speaking. There is no guarantee of an accurate answer to every possible question.
- **Stop listening** closes the audio stream and network connection after collecting final transcript results. It does not cancel a Google answer already in progress; **Cancel answer** does that. Network calls have bounded timeouts, so cancellation can take until the next response chunk or timeout.
- **Export session notes** saves committed transcript text and completed answers to Markdown. Unsaved notes disappear when the app closes. **Save context profile** explicitly saves resume/job text to an unencrypted JSON file with no API keys; keep it private.

## Screen-sharing privacy

The **Exclude this app from supported screen captures** option is enabled by default. It calls the Windows `SetWindowDisplayAffinity(WDA_EXCLUDEFROMCAPTURE)` API on the main window and other Qt top-level windows, including app-created file dialogs. It verifies that Windows accepted the requested affinity and shows its status in settings. The option also applies again when the app's native window changes (for example when toggling always-on-top).

**This is best effort, not guaranteed invisibility.** Microsoft documents that affinity protects only a specific set of operating-system capture paths. Behavior varies by meeting app, capture mode, OS version, and graphics setup. Verify from a second participant/device or the actual shared view before relying on it. Share the meeting/presentation window rather than the entire desktop when possible. This app does not conceal processes, bypass proctoring, or prevent cameras/external capture from seeing your display.

## Keys, privacy, and cost

- Keys are masked and held in memory by default. Nothing is sent to an application backend: Google receives generation requests directly, and Deepgram receives audio directly over TLS. Proxy settings on your PC may affect networking.
- **Remember API keys** stores them in `%LOCALAPPDATA%\ALLY\settings.json`, encrypted with Windows DPAPI for your Windows user account. Unchecking this option removes saved encrypted keys immediately. Other settings are saved when you click Save or close the app. Context and transcripts are not stored in this settings file.
- DPAPI does not protect against another program running as your logged-in user. Do not share your API keys or add them to the source tree.
- No raw audio files, debug logs, analytics or crash uploads are written by the app. Transcripts and answers remain in memory unless exported. Provider-side retention, quotas, billing and data policies still apply.
- API tests are real, billable requests. Live transcription and every generated answer use your provider account. Automatic coaching can create more requests. Answer requests are not automatically retried. Live transcription automatically reconnects after temporary interruptions, which may create new billable streams.

## Build a standalone executable

**ALLY.exe is a self-contained Windows x64 launcher** carrying the Windows Python runtime and the application's dependencies. First launch extracts the bundle to your local application-data folder, then opens the native desktop app. It does not install a system-wide Python runtime. The bundled `source` folder contains the source code and third-party package metadata/license files remain with their packages.

For a conventional PyInstaller single-file build on your own Windows PC, install Python 3.12 x64, run Setup.cmd in the source folder, then Build-EXE.cmd. This produces `dist\ALLY.exe`. The included Windows workflow does the same. Neither build is code-signed.

To uninstall, close ALLY, delete ALLY.exe and `%LOCALAPPDATA%\AcesIntelligence\ALLY`. To remove saved settings/keys too, delete `%LOCALAPPDATA%\ALLY`. Context profiles and exported notes are stored wherever you chose to save them.

## Troubleshooting

| Symptom | What to check |
| --- | --- |
| Start listening is disabled | API keys, a selected Gemini model, system output, resume + job text within size limits, and the permission checkbox. The start button runs the single audio check if needed. |
| Speech test recognizes nothing | Play speech, not music or silence. Match the capture device to the meeting's output. Microphones are not captured. |
| Test fails after changing headphones | Refresh audio devices, select the new output, and retest. Bluetooth devices can switch audio profiles when a meeting starts; test with the meeting open. |
| HTTP 401 / 403 | Check the API key, service access, region, and billing. Google AI Studio keys and Vertex AI credentials are different. |
| HTTP 404 / model error | Reload the Google model list; verify Deepgram model/language support. Models can be retired. |
| HTTP 429 | Check account quota/rate limits and billing. Wait before retrying; use manual coaching to reduce requests. |
| Network / WebSocket error | Check firewall, VPN, proxy and TLS inspection. Allow HTTPS to `generativelanguage.googleapis.com` and WSS to `api.deepgram.com`. The live coach automatically reconnects after temporary disconnections. |
| Audio overflow | Close heavy applications if interruptions repeat. The coach reconnects after overflow; speech during interruptions may be lost. |
| The app appears in a screen share | Capture exclusion is not supported by that capture path. Verify the toggle/status and use window sharing or a separate device. |
| Scanned resume imports blank | Paste the resume text or apply OCR first. |
| Launch does nothing | Run Launch-Debug.cmd; check that Setup completed and Python 3.12 x64 is installed. |

## Developer verification

```
python -m pip install -r requirements-dev.txt
python -m pytest -q
```

Tests mock paid APIs and audio hardware and exercise request formatting, streaming parsing, model pagination, test invalidation, utterance assembly, audio lifecycle, window protection plumbing, context imports, and UI state. The UI was checked in a Linux offscreen Qt environment and the Windows launcher was cross-compiled and its PE structure/bundled contents checked. This environment cannot run Windows executables. Native launch, the Windows audio driver, capture behavior, DPAPI and paid-provider tests require verification on your Windows PC. No live provider success is claimed until you run the in-app tests.

## Provider and platform references

- Gemini model discovery: https://ai.google.dev/api/models
- Gemini generation and streaming: https://ai.google.dev/api/generate-content
- Deepgram streaming: https://developers.deepgram.com/reference/speech-to-text/listen-streaming
- Windows capture affinity: https://learn.microsoft.com/en-us/windows/win32/api/winuser/nf-winuser-setwindowdisplayaffinity
- Windows WASAPI audio library: https://github.com/s0d3s/PyAudioWPatch

Version 2.1.0. Source is included for review and modification. Dependencies retain their respective licenses.
