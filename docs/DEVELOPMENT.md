# Build

Windows prerequisites: Git, Python 3.12+, Node.js 22+, Rustup, MSVC C++ Build Tools, the Windows SDK, CMake, and Chrome or Edge. Dependencies require network access.

```powershell
git config --global core.longpaths true
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/setup-windows.ps1 -InstallCppBuildTools
python scripts/setup_runtime.py
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/build.ps1 -Profile release
```

The first command enables long paths in your user-level Git configuration. Cargo's
V8 dependency includes deeply nested submodules; a setting on the Codex source
checkout alone does not apply to them. No administrator terminal is required.

`upstream.lock.json` pins Codex, Rust, the patch, and file checksums. `release.json` defines the independent Codux version and npm package name. The build checks the patch, runs embedded Rust regression tests, assembles native helpers, and verifies database migration checksums. Only a successful package updates `.build/current.json`. Existing packages are never overwritten.

Use a new patch revision for changed code. See [Packaging](RELEASE.md) to prepare npm archives. Locally built executables are updated by rebuilding; npm installations use `codux update`.

Use the [Windows compatibility acceptance checks](COMPATIBILITY.md#verification-and-release-acceptance)
before declaring a terminal verified. Automated tests run without the maintainer's
UI settings; installed-package checks use a fresh home and a prefix containing
spaces and Unicode. Interactive terminal results must be recorded separately.

## Other native hosts

The manual **Verify native npm packages** workflow can run on Windows x64, Linux x64 (glibc), and macOS Apple Silicon. Linux and macOS are experimental until the workflow passes on those hosts. macOS Intel packaging is supported by the packaging script but is not in the initial workflow matrix. Alpine/musl and Windows ARM64 are not supported.

On GitHub, open Actions, select the workflow, choose Run workflow, and select a platform or `all`. Each host builds its own executable, tests it, renders sample diagrams, and installs the result through a disposable local npm registry. The final artifact includes only targets that passed. This manual build does not publish; publication uses a separate workflow. The job needs sufficient memory and disk for two Rust build profiles; a larger runner may be needed if hosted runner limits are reached.

On a native Linux/macOS development host, install the pinned Rust toolchain, Node.js, Python, a C++ toolchain, CMake, pkg-config, and Chrome/Chromium. Linux also needs libcap, ALSA, and OpenSSL development packages. Run `python scripts/ci_build.py` to perform the same build and checks.

## Updating the pinned upstream

The **Track Codex upstream** workflow runs every six hours or on manual dispatch. It reads the latest official stable release, ignores older/current versions, and waits if an upstream PR is already open. Enable **Allow GitHub Actions to create and approve pull requests** in the repository's Actions settings so it can open PRs. The workflow creates PRs but does not approve or merge them. Scheduled runs require the workflow on the default branch; GitHub may delay schedules or disable them in inactive public repositories.

Candidate preparation uses a fresh `.build/upstream-port-*` checkout. It resolves the tag to a commit, applies the existing patch, reads the new Rust toolchain, and regenerates the patch and both sets of file hashes. A reverse/reapply check verifies the exact bytes. Only after those checks pass does it update the patch, `upstream.lock.json`, and `release.json`. It increments the internal patch revision and the Codux patch release number. SQL migration newline handling is preserved. No conflict is resolved automatically.

The tracker runs the reusable Windows build directly: verification does not depend on a token-created PR triggering another workflow. Results appear as **Codux / Windows native** on the PR commit. Human PR edits run the PR workflow. Fork PRs receive the ordinary Actions checks without a privileged status-writing job. Require review and this check in the default branch rules; the tracker never merges automatically. Before merging, test multiline paste, F4 scrolling, folding, resume, and Mermaid in a real terminal. A passing build cannot verify how every terminal displays the UI.

To prepare a cleanly applying update locally:

```sh
python scripts/prepare_upstream.py rust-v<version>
```

The command updates local build inputs but neither creates a PR nor publishes. Check the resulting diff before committing. Both the checkout and a regenerated patch remain under `.build` for inspection.

On a conflict, inspect the failed run and its `upstream-report` artifact, port the patch manually in a separate checkout, and regenerate the pin and hashes. Preserve the database migration checks. Do not merely replace the version or commit. If validation fails after PR creation, fix that branch and push a new commit; human updates are tested again. Closing an unwanted candidate prevents it from being recreated from the same base commit. If PR creation fails after branch creation, open a PR from that `automation/codex-*` branch manually. The existing npm release is unchanged throughout.

After merge, a release version change starts the [publication flow](RELEASE.md#enable-automated-publication) when enabled. Upstream Codex versions, internal patch revisions, and published Codux versions remain independent.

## Public files

The explicit source allowlist is in `scripts/public_source.py`. `.gitignore` excludes local preview tools, standalone development tests, screenshots, logs, settings, session exports, caches, compiled output, and legacy ZIP tools. Public documentation and code use English. Local development notes may use other languages.

`python scripts/audit_public.py` checks the allowlist, patch checksum, and public text. Build regression tests embedded in the patch and npm installation checks remain because the release build runs them.

To prepare a clean repository folder, run `python scripts/audit_public.py --stage .local/github-source`. The destination must not already exist. It contains only the audited public files, with no Git history or build artifacts. Set `repository` in `release.json` to the new `owner/project` when known; it is optional npm metadata and does not control updates.
