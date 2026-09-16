# Changelog

All notable changes to cyberbody are documented in this file. The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the project uses [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## Unreleased

### Added

- Branded four-hand keyboard icon for the Qt window, taskbar, packaged executable, and Windows shell sizes from 16 to 256 pixels.
- Native Computer Use engine using the formal `computer` tool, stateful Responses loop, batched actions, and safety-check acknowledgements.
- Agent workspace UI with a large live viewport, embedded action markers, activity timeline, execution-mode switcher, and focused takeover controls.
- Automatic compatibility migration: existing configurations retain dual-model behavior while new installations default to native mode.
- Independent vision and text-action model profiles with separate API URLs and credentials.
- Structured screenshot perception so the action planner no longer requires image support.
- GitHub Actions quality, security, dependency-audit, and Windows release workflows.
- Contributor, security, privacy, architecture, release, and bilingual README documentation.
- Automated repository privacy audit for high-confidence secrets and personal paths.

### Changed

- Restored the native computer-tool loop as the recommended engine while preserving dual-model execution as an explicit compatibility mode.
- Replaced the coupled native computer-tool loop with one-action-per-observation planning.
- Migrated legacy single-model configuration to both model roles on first load.
- Declared x64-safe Win32 function signatures to prevent handle truncation.
- Strengthened embedded-secret redaction and invalid-config recovery.
- Restricted authorized owned dialogs to the bound target process.
- Escaped untrusted log content before rendering it in the Qt panel.

## 0.1.0 - 2026-08-26

### Added

- Supervised Windows side panel with natural-language tasks and crosshair window binding.
- OpenAI Responses API loop using the GA `computer` tool and `gpt-5.6` default model.
- Visible-pixel capture, DPI-aware coordinate mapping, action preview overlay, and Win32 `SendInput` execution.
- Confirmation, handoff, and denial policies for high-impact actions and prompt injection.
- Emergency stop, single-instance local IPC, session logs, screenshot retention, ZIP export, and cleanup.
- Deterministic local automation test window and initial unit test suite.
