# Codux UI playground

Try the UI changes that Codux adds to Codex, using a short excerpt from a local
conversation. This is a browser rendering, not a running CLI or a general Codex
client. Only the /custom command is implemented. Submitting any other text starts
a seven-second Working preview with a countdown and an explicit simulation label.
It makes no model call, generates no answer, and does not change saved sessions.
The status appears after the cards inside the scrollable conversation. After seven
seconds it becomes a static Worked for 7s surface, still labeled as a preview.
Starting or finishing a preview preserves the reading position when scrolled up.

Below the header, the terminal fills the workspace alongside the sessions and
shortcut guide. Fenced code stays in the answer's text flow without an extra
card, language heading, or nested scroll area.

| Codux feature | How to try it |
| --- | --- |
| Separate question, reply, tool, intermediate, and final-answer styles | Open a local conversation and inspect its cards |
| Tool and intermediate-answer visibility | Change Display in /custom; cycle Progress, Answers only, and All cards with Shift+F4 |
| Folding and card navigation | F4, Ctrl+arrows, Enter, or double-click empty card background |
| Search filters by message type | F3, then Tab in the search box |
| Card colors, padding, width, titles, and initial fold state | /custom; changes preview on the loaded excerpt |
| Working animation speed | /custom > Answer > Working animation |
| Working status preview | Type a message and press Enter; Shift+Enter inserts a new line |

Codex's syntax-theme picker, session-resume command, and agent operations are not
reimplemented. This page does not send prompts, execute tools, or rewind history.
Mermaid's native rendering and real task transitions require testing in the CLI;
Mermaid source is shown as text here. The timed Working simulation is visual only.
Its background uses the native cosine pulse at the selected 1–4 second period.
The text uses Codex's separate shimmer: a 600 ms start delay, then a one-second
sweep every four seconds. Reduced-motion preferences disable both effects.

## Open in your browser

[Open the playground](https://eun0571.github.io/codux/). No installation, source
checkout, account, or model access is required.

Choose **Open sessions** for a Codex rollout `.jsonl` file, or **Open folder** for
your sessions folder. The default location is `%USERPROFILE%\.codex\sessions`
on Windows and `~/.codex/sessions` on macOS or Linux. If you use `CODEX_HOME`,
choose its `sessions` folder instead.

The Sessions sidebar includes a short guide to the default location. On Windows,
look in `C:\Users\<your username>\.codex\sessions`. Select a dated subfolder or a
rollout `.jsonl` file inside it. File selection uses your browser's standard picker.

The website reads only the files you select, inside your browser. Conversation
contents are not uploaded. A hosted website cannot discover your local sessions
automatically. Use a desktop browser for the full keyboard controls.

## Local preview

With Python 3.12+ and Node.js 22+:

    python scripts/serve_playground.py

This builds the web files, opens <http://127.0.0.1:8765>, and automatically finds
saved conversations under CODEX_HOME/sessions or ~/.codex/sessions.
No file picker, Rust build, model login, or npm install is required for this mode.
The server runs independently of Codex and stops with Ctrl+C. It does not register
a startup service.

The most recent conversation opens first. The **Sessions** sidebar shows the
conversation list; titles, project names, and dates help identify a session. The last selected
conversation is remembered for the current browser tab.

For a different home or an occupied port:

    python scripts/serve_playground.py --codex-home PATH_TO_CODEX_HOME --port 8766

Use --no-browser to start without opening a tab.

## Excerpt size and navigation

Loading a conversation no longer loads its entire history.

- Each request reads at most 1 MiB from the source file, starting near its end.
- The server returns at most 160 display records and 256 KiB of projected JSONL.
- The browser retains at most 40 message/tool items and 32,000 text characters.
- Individual tool text is limited to 2,000 characters; other messages to 8,000.
  Shortened text is marked in the preview.
- **Earlier**, **Newer**, and **Latest** replace the current excerpt. They do not
  append more history to the document.

Search includes hidden and folded cards **within the current excerpt**, not the
entire session. Copying a card copies its displayed excerpt. A window may begin
mid-turn; some message or tool relationships can cross the loaded boundary.
Malformed records or records larger than the bounded source window may be omitted,
with an indication above the preview. The original file remains unchanged.

The version in the page header identifies the preview build. Its tooltip gives
the pinned upstream version. A rollout's historical cli_version is not a
running application version and is not displayed as one.

## Controls and layout

The terminal frame contains the conversation, /custom, F3 search, the composer,
and browsing status. The surrounding page provides conversation selection,
excerpt navigation, a short feature guide, and preview-environment controls.
Typing / in the composer opens command suggestions above the prompt. Tab completes
/custom; Enter opens it, including from a matching prefix such as /cu. Clicking the
suggestion also opens it. Esc dismisses suggestions without clearing the draft.
Only /custom is implemented; other text starts the local Working preview.

Click inside the terminal before using shortcuts:

| Control | Action |
| --- | --- |
| /, then Tab | Complete /custom in the prompt; Enter opens settings |
| F4 | Enter or leave card browsing |
| Up / Down, Page Up / Page Down | Scroll while browsing |
| Ctrl+arrows | Select another card |
| Enter | Reveal the selected card, then fold or unfold it |
| F3 | Search this excerpt |
| Tab / Shift+Tab in search | Switch message type |
| Enter in search | Accept the current match and return to reading |
| Ctrl+P / Ctrl+N in search | Older / newer matching card |
| Shift+F4 | Cycle card display: Progress → Answers only → All cards |
| Ctrl+End | Return to the bottom of this excerpt |
| Esc | Close the current menu, search, or browsing layer |
| ? in an empty prompt | Show the in-terminal shortcut guide |
| Ctrl+C during Working preview | Stop the preview; text selections still copy normally |

Click a card to activate it, double-click its empty background to fold it, or drag
text and use Ctrl+C to copy. Search opens below the prompt, with filter and
navigation hints in the terminal footer. The sidebar contains a short feature
overview; contextual controls stay inside the terminal preview.
Native rewind is not replaced with a different browser action.

The footer follows native Codux's idle, Find, and Browsing layouts. Browser-only
scope is labeled Preview or excerpt instead of inventing live context usage.
Only the session list scrolls in the sidebar; its shortcut overview stays visible.
During the Working preview, new drafts are kept and /custom is unavailable until
the preview finishes or is stopped. Esc never cancels this simulated task.

/custom uses the shipped native color/default catalog. Esc returns to the previous
menu selection; reopening the command starts at its root. Card display and
Reset to defaults are available from its root, as in Codux.
Theme > Default uses Base16 Ocean Dark card colors with no final-answer background,
matching a new native installation. Existing saved preferences remain intact.
Theme changes card background colors only; text contrast is derived automatically.
Padding, width, folding, display settings, and Codex syntax colors are unchanged.

Card editing stays organized by Question, Tools, and Answer. In a style element,
**Apply to** chooses **Current card**, **Selected cards**, or **All cards**.
For example, open Question > Prompt style > Padding > Horizontal, choose All cards,
then choose 1 column. Only horizontal padding is copied; every card keeps its own
background, vertical padding, title, alignment, and visibility. Selected cards can
include any combination of Question, Reply, Tools, Intermediate answer, and Final
answer, including hidden cards. Choose at least one card before continuing.
Values preview together, Enter saves, and Esc restores all affected cards.
Target selection is temporary within that style branch (such as Padding); returning
to the card menu resets it to the current card. Display, Theme, and Working animation retain their
existing scopes.

## Data and settings

The local server binds only to 127.0.0.1, restricts reads to discovered rollouts,
and rejects cross-origin API requests. It does not read authentication files or
contact a model provider. Session text stays in memory and is never published.

The first local visit imports compatible styles from codux-ui.json.
Further changes are stored only in browser preferences. **/custom > Reset to
defaults** previews and restores the shipped defaults; Esc cancels the preview.
These changes never write native settings. The last selected session's opaque ID is
kept in tab storage, not the conversation contents.

## Static hosting

A static site cannot discover local files automatically. The same assets support
manual file or directory selection; large files are also read in bounded excerpts.

    python scripts/build_playground.py
    python -m http.server 8765 --bind 127.0.0.1 --directory .build/playground

For GitHub Pages, select **Settings > Pages > Source > GitHub Actions**.
The Playground workflow automatically validates and deploys relevant changes on
the default branch. It can also be started manually from the Actions tab.
The Playground workflow deploys only the nine static web assets. PRs build without
deploying. No sessions, native binaries, or local server are uploaded.
The public playground is hosted at <https://eun0571.github.io/codux/>.

## Maintenance

palettes.js is exported by the native TUI catalog test. catalog.json records
source hashes and the upstream commit; a stale catalog fails the web build.

    python scripts/build_playground.py --catalog-test-exe PATH_TO_CURRENT_CODEX_TUI_TEST_EXECUTABLE

The site builder runs the JavaScript importer/navigation checks and Python local
server tests, including bounded pagination. These tests use synthetic records.
Review browser behavior separately after native menu or navigation changes; the
web page does not use the Rust terminal renderer.
