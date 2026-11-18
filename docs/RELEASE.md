# npm releases

GitHub stores the source. npm distributes the compiled application and handles updates. GitHub Releases and ZIP downloads are not required.

`release.json` defines the Codux version, npm package, and dist-tag. Its optional `repository` field is the GitHub `owner/project` shown on npm; use `null` until the repository is ready. `upstream.lock.json` pins Codex and the patch. Published versions are immutable: increment the version for every changed release.

## Prepare

After a successful native release build:

```sh
python scripts/audit_public.py
python scripts/package_npm.py --package dist/<package_version>-release --smoke
```

Use the output directory printed by the build; additional targets include their target triple. Packaging verifies the binary, renderer resources, and actual image generation. `--smoke` installs through a disposable local npm registry and checks the command, update lookup, and relocated renderer. It does not publish or change the user's global installation.

`dist/npm/<version>/` contains the small `@neulkeukeu/codux` command package, one native package per verified platform, and `SHA256SUMS.txt`. Native packages include binaries, helpers, renderer libraries, and licenses. Node.js and a browser are not bundled. Installation does not compile code or run download scripts.

For additional platforms, run the manual GitHub Actions workflow. It builds and verifies native packages, then assembles the command package from passing targets. Artifacts stay in Actions. A successful build still requires interactive testing on each supported OS. Before publishing additional platforms, extend the automated release matrix to keep shipping them; the publisher rejects updates that drop an already published platform.

## Publish

Authenticate locally with `npm login` as the package owner. Publish each native archive first, then the command archive:

```sh
npm publish <native-package.tgz> --access public --tag latest
npm publish <command-package.tgz> --access public --tag latest
```

Verify installation from npm before removing the unpublished notice from README. Keep credentials out of the repository. The npm account or organization owns the package scope independently of the GitHub account.

## Enable automated publication

The workflows are included, but automatic npm publication is off until repository and npm setup is complete:

1. Set `release.json`'s `repository` to the real public `owner/project`. Keep the npm scope tied to its npm owner; it need not match the GitHub owner. Build and publish the initial packages manually as above so each package exists on npm.
2. For **both** `@neulkeukeu/codux-win32-x64` and `@neulkeukeu/codux`, configure an npm trusted publisher with the GitHub owner, repository, workflow filename **`publish-npm.yml`**, and environment **`npm`**. Permit direct publishing if npm offers a staging-only setting. Repeat for every future native package. The package repository URL must match this repository.
3. Create the GitHub environment `npm`. Set the repository Actions variable **`CODUX_NPM_PUBLISH_ENABLED`** to **`true`**. No npm token is stored in GitHub; the publish job uses OIDC on a GitHub-hosted runner. Node 24 and npm 11.5.1+ are required by this workflow. See [npm trusted publishing](https://docs.npmjs.com/trusted-publishers/).
4. Increment `release.json.version` in a reviewed PR. Merging it into the default branch starts a fresh Windows release build, renderer verification, and isolated npm install/update check. Only a successful build reaches the publish job. Changing repository metadata without increasing the version does not publish.

The publisher verifies `SHA256SUMS.txt`, archive metadata, pinned build inputs, and command dependencies. It uploads native packages first and the command package last. Until the command package is published, users continue to see the previous release. Artifacts and logs remain in Actions; a GitHub Release or ZIP is not needed.

To start a release manually, select **1. Release to npm**, choose the default branch, and enter the exact checked-in version. Leave `resume_run` empty for a new build. This uses the same build and validation gates. Publication must already be enabled.

If a publish step fails, rerun **failed jobs** in the same run to reuse its verified artifacts. An already published archive is skipped only when its version, checksum, and dist-tag match exactly. A rebuilt archive may have different bytes even for the same source; never overwrite an npm version. Bump the release version before rebuilding a partly published release. Fix patch/build failures before retrying; they do not publish any package.

For a local inspection of downloaded `npm-release-candidate` artifacts:

```sh
python scripts/publish_npm.py --artifacts <artifact-directory>
```

This only validates and lists publication order. Adding `--publish` uploads using the current npm identity, so use it only for a deliberate release.

npm may accept an upload before making it publicly available. The publisher waits up to ten minutes for each archive's version, dist-tag, and checksum before publishing the next package. CI saves a receipt for every accepted upload. If processing takes longer, the result summary says **Waiting for npm - NOT published**, with a warning and a pending `Codux / npm <version>` commit status. This is not a publication failure or a completed release. Authentication, network outages, checksum mismatches, build failures and other errors still fail normally.

The existing six-hour maintenance workflow rechecks pending releases without creating additional polling runs when nothing is pending. To recheck sooner, run **1. Release to npm** with the exact version and the previous run ID in `resume_run`. It restores the verified archives and upload receipt, skips the build, checks accepted uploads without uploading them again, then publishes any remaining packages in dependency order. Receipts must match the exact archive checksums and current release inputs. Expired artifacts or changed release inputs require manual inspection. The automatic retry does not apply retroactively to old runs without upload receipts.

For local publication, retain the upload receipt with the archives:

```sh
python scripts/publish_npm.py --artifacts <artifact-directory> --publish --state publication.json
```

Repeat the same command and receipt to resume. If all uploads completed and only verification remains, use:

```sh
python scripts/publish_npm.py --artifacts <artifact-directory> --verify-only
```

An unavailable version is reported separately from a checksum mismatch. Do not rebuild or increment the version just to retry a pending registry check.

If publication stopped while waiting for a native package, the command package has not been uploaded yet. Resume with the same archives and receipt; identical published archives are skipped before the remaining uploads. `--verify-only` never uploads the remaining command package.

## Read GitHub Actions

Open **1. Release to npm** for the installed application's delivery state. Each run has versioned build jobs and a final **Release result** summary. **Published** means every native package and the command package are public with matching checksums and tags. **Waiting for npm** means the upload was accepted but delivery is incomplete. The workflow may finish green after safely deferring a pending upload; use the result summary and npm commit status, not the green workflow icon alone.

| Workflow | Purpose |
| --- | --- |
| 1. Release to npm | Build, verify, publish, or resume a release |
| 2. Codex updates and release status | Check stable Codex every six hours, prepare an update PR, and recheck pending npm publication |
| 3. Browser playground | Check and deploy the website independently of npm |
| Checks - Pull request | Validate proposed changes without publishing |
| Checks - Native packages | Shared build checks; manual platform verification without publishing |

An update candidate passing checks is not a published release: it still needs review and merge. Playground deployment does not update the installed application. Historical runs are preserved; an old failed run does not describe the current release. Artifacts are build archives, logs and upload receipts, not additional releases, and normally do not need downloading.

## Update

Users install with `npm install -g @neulkeukeu/codux` and update with `codux update` or `npm install -g @neulkeukeu/codux@latest`. Startup checks use npm metadata. Accepting an update closes the native process before the launcher invokes npm. On Windows, close other Codux sessions and its background server before upgrading. Local or custom-prefix installs must use their original npm prefix.
