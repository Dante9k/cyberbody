# Changelog

All notable changes to cyberbody are documented in this file. The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the project uses [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## Unreleased

### Added

- GitHub Actions quality, security, dependency-audit, and Windows release workflows.
- Contributor, security, privacy, architecture, release, and bilingual README documentation.
- Automated repository privacy audit for high-confidence secrets and personal paths.

### Changed

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
