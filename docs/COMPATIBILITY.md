# Windows compatibility

Codux currently distributes a Windows x64 build. Node.js 22+ is required for npm
installation. Rust, Python, and the source checkout are not required to use it.
Chrome or Edge is optional: only Mermaid image generation needs a browser.

A shell and a terminal are different. PowerShell, Command Prompt, and Git Bash can
launch the same Windows executable. Colors, image protocols, mouse input, and key
delivery depend on the terminal hosting that shell. WSL requires a Linux build;
it is not covered by the Windows package.

## First launch and saved settings

New installations use Base16 Ocean Dark card colors, with the final-answer
background set to None. This palette is independent of the current syntax theme.
Named palettes, adaptive Auto backgrounds, and custom colors remain available
under `/custom`. When color is unavailable, Codux keeps the terminal's own colors;
focus remains indicated by bold text.

These defaults are written once to `codux-ui.json` in `CODEX_HOME` (normally
`~/.codex`). Existing choices are preserved. Use `/custom` > Theme > Default to
apply the Mocha colors with no final-answer background to existing settings;
this changes colors only. Auto remains adaptive when moving between terminals.

The `/custom` header shows **Default** or **Customized**. Choose **Reset to defaults**
to preview all first-install UI settings for the installed version. Enter saves;
Esc restores the previous settings. Reset does not change Codex configuration,
syntax highlighting, login, or conversation history.

Tools start hidden, intermediate answers remain visible while working, and final
answers remain expanded when a conversation is reopened. `/custom` changes
persist. Codux retains the official login, configuration, and conversation store;
it does not import the developer's settings or require a project-local launcher.

## Terminals

| Terminal | Conversation UI | Mermaid Auto |
| --- | --- | --- |
| Windows Terminal | Text/card interface | Requires a Sixel capability reply; otherwise native text |
| VS Code integrated terminal | Text/card interface; editor keybindings can intercept shortcuts | Requires image support enabled, a capability reply, and usable cell dimensions; otherwise native text |
| Git Bash default window (mintty) | Text/card interface; input delivery can involve a Windows console bridge | Requires a capability reply and usable cell dimensions; otherwise native text |
| Older console, remote session, or unknown terminal | Terminal colors and native text are the baseline | Native text when support cannot be confirmed |
| tmux or Zellij | Text interface | Native text; graphics passthrough is not implemented |

This table describes fallback policy, not certification of every terminal version.
The build checks below do not replace an interactive test in each terminal.
Shift+F4, F3, F4, Tab/Shift+Tab and Ctrl+Up/Down must reach the application; some terminal/editor shortcuts
take precedence. See the [README controls](../README.md#customize-and-navigate).

Image support is optional. Codux uses the bounded startup terminal probe to read
the DA1 Sixel capability. It does not enable images from `TERM_PROGRAM` or
`WT_SESSION` alone. A known background and usable geometry are also required.
Unsupported terminals retain Codex text immediately without starting the image
worker. See [Mermaid](MERMAID.md) for explicit overrides and caching.

## Verification and release acceptance

Automated release checks cover:

- An isolated npm prefix containing spaces and Unicode, and an empty `CODEX_HOME`.
- Version output under terminal environment hints, with no terminal escape queries.
- First-run settings, saved-setting reloads, light/dark/unknown palettes, and text contrast.
- Probe replies interleaved with typing and bracketed paste; unrelated input is retained.
- Native text fallback, image sizing/caches, and relocated renderer dependencies.
- Multiline paste, F4 navigation/scroll anchoring, Shift+F4 card display, reset/cancel/persistence, folding/resume, and selection/copy regressions.

Before describing a terminal/version as interactively verified, record the Codux
version, terminal version, shell, theme, font/zoom, and these results:

1. Start with an empty, temporary `CODEX_HOME`; complete the normal sign-in/setup.
   Do not delete or replace the daily configuration. Check first-launch colors,
   then change a `/custom` setting and confirm that it survives a restart.
2. Reopen a test conversation. All final answers must start expanded and completed
   intermediate answers folded. Tools must obey the saved visibility choice.
3. Paste a multiline numbered list once. It must remain one draft and send only
   after an explicit submission. Include non-ASCII text and a long wrapped line.
4. In F4, scroll up/down past the pinned question and resize narrow/wide. Use
   Tab/Shift+Tab to filter selectable types, Ctrl+Up/Down to select a matching card,
   and Enter to fold it. Filtering must not hide cards; rows must not jump backward.
5. Drag through wrapped question and answer text. The highlighted range and copied
   text must agree; single-click focus must not collapse a card.
6. Check light and dark terminal themes, large fonts, and display scaling. Plain
   text and focus must stay readable without requiring a specific color scheme.
7. Test a Mermaid diagram both with images available and unavailable. Missing
   support/browser must retain native text and its original copy/search source.

Record failures and untested combinations explicitly. An npm installation test,
in-memory render test, or a browser playground is not a terminal UI acceptance test.
