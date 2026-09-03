<p align="center">
  <img src="docs/assets/cyberbody-banner.svg" alt="cyberbody for Windows" width="100%">
</p>

<p align="center">
  <strong>English</strong> · <a href="README.md">简体中文</a>
</p>

<p align="center">
  <img alt="Windows 10 and 11" src="https://img.shields.io/badge/Windows-10%2022H2%20%7C%2011-0078D4?logo=windows11&logoColor=white">
  <img alt="Python 3.12" src="https://img.shields.io/badge/Python-3.12-3776AB?logo=python&logoColor=white">
  <img alt="Responses-compatible APIs" src="https://img.shields.io/badge/API-Responses--compatible-412991">
  <img alt="MIT License" src="https://img.shields.io/badge/License-MIT-22c55e">
  <img alt="Status Alpha" src="https://img.shields.io/badge/Status-Alpha-f59e0b">
</p>

# cyberbody for Windows

cyberbody is a **human-supervised visual automation agent for Windows**. Describe a task, explicitly bind one target window, and let the application run a controlled loop of screenshot, visual perception, text planning, risk inspection, visible preview, input, and observation.

The agent understands the interface exclusively from **visible pixels**. It does not read UI Automation trees, browser DOMs, or application internals. An image-capable model converts screenshots into structured UI descriptions with coordinates; a separate planner receives text JSON only and proposes the next action. A deterministic local safety layer validates every action before Win32 `SendInput` can execute it.

> [!WARNING]
> cyberbody is alpha software that sends real keyboard and mouse input. Start with the bundled deterministic test window. Do not use it for payments, production administration, elevated applications, or unattended workflows. It is not a sandbox.

## Highlights

- **One-window authorization:** the task pauses when the target loses focus, moves, minimizes, closes, or changes identity.
- **Decoupled models:** screenshots go only to the vision endpoint, so the action planner may be text-only.
- **Visible action previews:** click locations and drag paths are highlighted before execution.
- **Human approval:** destructive, external, financial, permission, upload, and sensitive-data actions stop immediately before impact.
- **Auditable sessions:** raw screenshots, model-sized screenshots, annotated previews, and JSONL events are retained locally.
- **Immediate stop:** the panel, CLI, and global `Ctrl+Shift+F12` shortcut can stop the worker independently of the model.
- **DPI-safe input:** multi-monitor layouts, negative coordinates, and 100%–200% scaling are mapped to physical pixels and revalidated.

## How it works

```mermaid
flowchart LR
    T[Task + bound window] --> S[Visible screenshot]
    S --> C[Vision model]
    C --> J[Structured UI JSON]
    J --> A[Text-only action model]
    A --> P[One proposed action]
    P --> R[Structured risk preflight]
    R --> G[Local safety gate]
    G -->|allow| V[Visible preview]
    G -->|confirm| H[Human approval]
    G -->|handoff| M[Manual step]
    G -->|deny| X[Stop]
    H --> V
    V --> B[Window and coordinate revalidation]
    B --> I[Win32 SendInput]
    I --> S
```

See [docs/architecture.md](docs/architecture.md) for state, coordinate, IPC, and module details.

## Requirements

- Windows 10 22H2 or Windows 11 x64
- Python 3.12 for source development, or the self-contained portable release
- Network access and credentials for both configured endpoints
- An image-capable vision model with JSON Schema output support
- A text-capable action model with JSON Schema output support
- A visible, non-elevated target application

Both endpoints use an OpenAI Responses-compatible `/responses` API. Model availability, compatibility, and limits depend on the configured providers.

## Quick start from source

```powershell
git clone <repository-url>
cd cyberbody
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install -e ".[dev]"
```

Launch the deterministic local test window first:

```powershell
.\.venv\Scripts\cyberbody-test-window.exe
```

Then launch cyberbody:

```powershell
.\.venv\Scripts\cyberbody.exe start
```

Use the crosshair to bind the test window and try:

> Enter “小明” in the name field, drag progress to 80, tick the agreement box, scroll to the bottom, and click Next. Do not click Delete.

## Dual-model endpoints

The supervisor exposes two independent endpoint profiles:

| Endpoint | Input | Output | Required capability |
| --- | --- | --- | --- |
| Vision | Bound-window screenshot | Structured text, elements, bounds, and coordinates | Image input and JSON Schema |
| Action | User task, UI JSON, and recent action history | At most one structured action per round | Text input and JSON Schema |

Leave an API URL empty to use OpenAI, or enter an HTTPS Responses-compatible endpoint. Local model servers may use loopback HTTP. Models, URLs, and non-secret settings are saved to `config.json`. Third-party credentials are scoped by role and a hash of the API URL, so changing a URL requires entering a key for the new endpoint.

Keys are read from `CYBERBODY_VISION_API_KEY` and `CYBERBODY_ACTION_API_KEY`, or endpoint-scoped `cyberbody/VisionAPI/<URL hash>` and `cyberbody/ActionAPI/<URL hash>` Windows Credential Manager entries. OpenAI endpoints may also use `OPENAI_API_KEY` and the legacy `cyberbody/OpenAI` credential. Keys are never accepted as command-line arguments or written to configuration and session logs.

Example compatible model split:

```text
Vision URL: https://api.deepseek.com
Vision model: deepseek-v4-flash-vision-exp
Action URL: https://api.deepseek.com
Action model: deepseek-v4-flash
```

## CLI

```powershell
cyberbody.exe start
cyberbody.exe run --task "Open settings in the bound window, but do not submit anything"
cyberbody.exe status
cyberbody.exe stop
```

`run` opens the supervisor panel and pre-fills a task. Window authorization and the Start button always remain explicit human steps. The single-instance local command channel is restricted to the current Windows user and never accepts API keys.

## Safety decisions

| Decision | Behavior | Examples |
| --- | --- | --- |
| `allow` | Preview, then execute | Reversible navigation and ordinary selection |
| `confirm` | Wait immediately before impact | Delete, send, publish, upload, payment, permission, sensitive input |
| `handoff` | The user performs the step manually | Final password change and security-warning boundaries |
| `deny` | Stop and record the reason | Prompt injection, out-of-scope action, safety bypass |

The deterministic local policy may always raise the model's risk level. Rejecting a confirmation produces no corresponding input event.

## Supported boundaries

- One visible, foreground, standard-user window per task.
- Visible owned modal dialogs are allowed only when they belong to the bound process.
- Stale coordinates are discarded after the window moves or resizes.
- The agent pauses when another application gains focus.
- Administrator windows, UAC secure desktop, lock screen, DRM content, exclusive fullscreen games, and anti-cheat environments are unsupported.
- Cross-application and unattended remote operation are intentionally unsupported.

## Privacy

Screenshots and task-related prompts are sent to the configured vision endpoint. The action endpoint receives the user task, the vision model's text JSON, and recent action history, but not the screenshot. Provider-side handling and retention depend on both services you configure. Local sessions are written to:

```text
%LOCALAPPDATA%\cyberbody\sessions\<session-id>
```

Sessions can contain sensitive pixels. They are retained for seven days by default, can be exported as an unencrypted ZIP, and rely on Windows user-directory permissions rather than application-layer encryption. cyberbody contains no project-owned telemetry or advertising analytics.

Read [docs/privacy.md](docs/privacy.md) before using personal or business data, and never attach a raw session archive to a public issue.

## Quality checks

```powershell
.\scripts\quality.ps1
```

The quality gate runs Ruff lint and formatting, mypy, Bandit, pytest with branch coverage, and a repository privacy scan for high-confidence secrets and personal paths.

## Portable build

```powershell
.\scripts\build.ps1
```

Exit every running cyberbody instance before building; Windows otherwise locks DLL/PYD files in the portable directory.

Artifacts:

```text
dist\cyberbody\cyberbody.exe
dist\cyberbody-Windows-x64.zip
dist\cyberbody-Windows-x64.zip.sha256
```

The portable directory includes Python and its runtime dependencies. Current builds are unsigned and may trigger Windows SmartScreen. See [docs/releasing.md](docs/releasing.md) for the clean-machine release checklist.

For repository settings, branch protection, naming, and demo preparation, see the [GitHub launch checklist](docs/github-launch.md).

## Project layout

```text
src/cyberbody/
├── api.py          Dual-model perception/planning loop and structured preflight
├── capture.py      Visible-pixel capture and model scaling
├── controller.py   State machine, limits, and worker thread
├── input.py        Win32 SendInput and Unicode typing
├── safety.py       Deterministic local risk policy
├── storage.py      Sessions, screenshots, export, and retention
├── ui.py           PySide6 supervisor panel and overlays
└── windows.py      Window identity, DPI, ownership, and bounds
```

## Contributing and security

- Contribution guide: [CONTRIBUTING.md](CONTRIBUTING.md)
- Security policy: [SECURITY.md](SECURITY.md)
- Support guidance: [SUPPORT.md](SUPPORT.md)
- Release history: [CHANGELOG.md](CHANGELOG.md)

Please report vulnerabilities privately. Do not publish real credentials, personal screenshots, or exploit details in an issue.

## References

- [OpenAI Responses API](https://developers.openai.com/api/reference/resources/responses)
- [OpenAI image inputs](https://developers.openai.com/api/docs/guides/images-vision)
- [OpenAI structured outputs](https://developers.openai.com/api/docs/guides/structured-outputs)
- [DeepSeek Vision](https://api-docs.deepseek.com/guides/vision/)
- [DeepSeek Responses API](https://api-docs.deepseek.com/guides/responses_api/)
- [OpenAI Python SDK](https://github.com/openai/openai-python)

Compatibility, capabilities, pricing, and limits may change. Verify them in each configured provider's current documentation and account dashboard. Accepting a third-party endpoint does not imply endorsement or support between cyberbody and that provider.

## License

[MIT License](LICENSE) © 2026 cyberbody contributors.

cyberbody is an independent open-source project and is not affiliated with, endorsed by, or sponsored by OpenAI or Microsoft. Users are responsible for complying with applicable law, service terms, and organizational policy.
