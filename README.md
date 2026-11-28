# Codux

A patched Codex CLI with a clearer conversation layout and configurable terminal UI.

- Separate presentation for questions, replies, tools, progress, and final answers.
- Configurable colors, spacing, visibility, and folding through `/custom`.
- Card navigation and search filtered by message type.
- Mermaid images in supported terminals, with Codex text fallback.

[Try the browser playground](https://eun0571.github.io/codux/) — no installation or login required. Open a local Codex session file or folder to try card styles, folding, navigation, and `/custom`. Files stay in your browser. See the [playground guide](docs/PLAYGROUND.md) for details.

Codux builds a separate `codux` executable from a pinned official Codex commit. This repository contains the UI patch and build inputs; upstream source is fetched during the build.

The official `codex` installation stays available. Codux shares its login, configuration, and conversation history through `CODEX_HOME`, and stores UI preferences separately in `codux-ui.json`.

## Install and keep up to date

Currently available for Windows x64. Install Node.js 22+ first.

```sh
npm install -g @neulkeukeu/codux
codux
```

npm installs the compiled application for your platform. You do not need Rust or a local source build. Check the installed version with `codux --version`.

PowerShell, Command Prompt, and Git Bash launch the same executable. Terminal features vary; see [compatibility and first-run defaults](docs/COMPATIBILITY.md).

Codux checks for updates in the background at startup. Checks are cached for 20 hours, and a newly discovered version is offered on the next launch. Accepting the prompt closes Codux and lets npm update it. For an immediate check and update:

```sh
codux update
```

You can also run `npm install -g @neulkeukeu/codux@latest`. On Windows, close other Codux sessions and its background server before updating.

## Build from source

Build locally to develop Codux or try changes that have not been published. Windows builds require Git, Python 3.12+, Node.js 22+, Rustup, MSVC C++ Build Tools, the Windows SDK, CMake, and Chrome or Edge for renderer checks. See [build setup](docs/DEVELOPMENT.md) for prerequisites.

From the repository root:

```powershell
python scripts/setup_runtime.py
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/build.ps1 -Profile release
```

The builder fetches the pinned upstream commit, verifies and applies the patch, runs regression checks, and assembles the executable with its required helpers and resources. Run the executable path printed when the build finishes. Use `-Profile dev-small` for local development. Source builds are updated by rebuilding.

## Customize and navigate

Use `/custom` to adjust the conversation UI. Preferences persist across sessions. Its header identifies default or customized settings. **Reset to defaults** previews this version's first-install UI; Enter saves and Esc restores your previous settings. New installations use Base16 Ocean Dark card colors with no final-answer background. Tools are hidden by default. Reopening a session expands all final answers and folds intermediate answers.

Edit styles by card. Within an element, **Apply to** targets the current card, selected cards, or all five card types. Only that element changes; Enter saves and Esc restores the preview.

Use `/statusline` and enable **daemon-version** to show the connected local background server's version. It is separate from `codux --version`, and is omitted when no local daemon version is available.

Enable **five-hour-reset** or **weekly-reset** in `/statusline` to show the server-reported usage reset date and time in your local time zone. These can be combined with the existing remaining-usage items and are omitted when reset information is unavailable.

| Control | Action |
| --- | --- |
| `/custom` | Change card colors, spacing, visibility, and folding |
| F3 | Search, with Tab to switch message types |
| F4 | Enter or leave conversation browsing |
| Up/Down in F4 | Scroll |
| Left in F4 | Open agents from an empty prompt; otherwise move the prompt cursor |
| Tab / Shift+Tab in F4 | Filter selectable card types |
| Ctrl+Up/Down in F4 | Select a matching card and align its bottom above the prompt |
| Enter in F4 | Fold or unfold the selected card; reveal it first if off-screen |
| Shift+F4 | Choose visible cards |
| Ctrl+End | Return to the latest message |
| Ctrl+E in F4 | Confirm rewinding to and editing an original question |

Shift+F4 opens a checklist for **Tools**, **Intermediate answers**, and **Clarification Q&A**. Space, Enter, or a click toggles a row and saves immediately; Esc closes the menu. Original questions, final answers, notices, and unanswered input forms stay visible. By default, tools are hidden and the other two categories are shown. The same checklist is available under `/custom → Card display`. Explicit custom keybindings are preserved; `tui.keymap.global.open_transcript` opens this menu.

Final answers written in Plan mode carry a magenta **PLAN** label, including when folded. The label describes how the answer was written; it does not claim that the plan was implemented. Local resume restores saved clarification exchanges where the session record contains both the question and the answer.

In F4, Tab cycles All, Questions/replies, Tools, Intermediate, and Final answers; Shift+Tab cycles backward. This filters keyboard selection without hiding or folding cards. Ctrl+Up/Down moves through visible cards of the selected type. F3 search uses its own independent filter.

Ctrl+E edits the selected original question in an idle, writable session with an empty prompt. It asks before removing that turn and later turns; files on disk are unchanged. If editing is unavailable, a dialog explains why and keeps your draft.

Esc closes menus, search, or F4 browsing; from a scrolled composer it returns to the latest message. It does not interrupt a task by default. Use Ctrl+C for task controls. Double Esc no longer enters transcript browsing. An explicit `tui.keymap.chat.interrupt_turn` setting can still assign a dedicated interrupt key.

Mermaid images require Chrome or Edge; renderer libraries are bundled. Choose **Auto** or **Codex text** in `/custom`. See [Mermaid rendering](docs/MERMAID.md) for terminal support and caching.

## Updating upstream

[Release activity](https://github.com/eun0571/codux/actions/workflows/publish-npm.yml) shows application publication. [Update checks](https://github.com/eun0571/codux/actions/workflows/track-upstream.yml) track official Codex; [playground deployment](https://github.com/eun0571/codux/actions/workflows/playground.yml) updates only the website. See [how to read the results](docs/RELEASE.md#read-github-actions), including npm processing delays.

[`upstream.lock.json`](upstream.lock.json) records the exact Codex commit, Rust toolchain, patch, and checksums used by a build. Updating the official `codex` installation does not change Codux's pinned source.

The [upstream tracker](.github/workflows/track-upstream.yml) checks official stable releases every six hours. When the patch applies cleanly, it prepares an update PR with refreshed pins, checksums, and a proposed Codux version. Windows regression tests, a release build, and an isolated npm installation check run against that PR. Patch conflicts require a manual port.

Updates are reviewed before merging. After the repository's [npm publishing setup](docs/RELEASE.md#enable-automated-publication), merging a release version change builds and verifies it again, then publishes the native package followed by the command package. Failed checks leave the existing npm release available. Automatic publication is disabled until that setup is complete.

The [native build workflow](.github/workflows/native-build.yml) can also be started manually. Windows x64 is the required automated target; Linux and macOS remain experimental. See [upstream maintenance](docs/DEVELOPMENT.md#updating-the-pinned-upstream) for conflict handling and checks before merging.

Merged `port/codex-*` and `automation/codex-*` branches are removed automatically when their heads still match the merged PR. Branches with new commits or open PRs are kept. The tracker waits while an upstream update PR is under review.

## License and attribution

Independent project, not an official OpenAI release. Licensed under [Apache-2.0](LICENSE); upstream and dependency notices are retained in [NOTICE](NOTICE).

The pinned-source and patch workflow was inspired by [codex-statusline](https://github.com/GordonBeeming/codex-statusline).
