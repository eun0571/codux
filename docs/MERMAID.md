# Mermaid diagrams

Codux uses official Mermaid 12.2.0 to generate SVG and PNG locally. Install Node.js on PATH and Chrome or Edge. Renderer libraries are included; Python and external rendering services are not required.

In `/custom`, choose **Auto** or **Codex text** under Answers > Mermaid. Auto uses images when generation and terminal image support are available; otherwise it keeps Codex's native text output. Codex text skips the custom image renderer. If Codex itself cannot render a diagram's syntax, its normal fallback remains visible.

Images match the answer background and use a light or dark Redux theme. Existing saved image styling is preserved. Display size is capped at 1.2 times the original SVG size. Narrow cards use 25%, 50%, 75%, or 100% of that cap. Top-level TB/TD flowcharts display as LR; copying and searching retain the original source.

SVG, PNG, and terminal encodings are cached locally (`%LOCALAPPDATA%\Codux\cache\mermaid` on Windows). Matching diagrams reuse these files across sessions. `CODUX_MERMAID_CACHE` overrides the cache location. `CODUX_MERMAID_PROTOCOL=off` disables inline graphics and uses Codex text. `CODUX_MERMAID_BROWSER` can specify an installed browser's absolute executable path.

The package includes only the minified Mermaid browser distribution and runtime dependencies for Puppeteer Core and beautiful-mermaid. Source maps, type declarations, development tests, duplicate distributions, Node.js, and browsers are excluded. Dependency licenses are retained.

Build dependencies are installed with `python scripts/setup_runtime.py` from pinned npm lockfiles. Product packaging verifies the staged runtime file hashes.
