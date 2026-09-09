# CI specifications

- ⚙️ [Dataspecer source code](https://github.com/dataspecer/dataspecer)
- 📦 [Input specifications to be tested](https://github.com/dataspecer/ci-specifications) - this repository
- ✨ [Output repository for published specifications](https://github.com/dataspecer/ci-exports)

This repository contains logic for exporting specifications using Dataspecer Docker image and testing them by running lifting, lowering, schema validation, etc. The results are published to the output repository.

## How to use

Create a new directory in `specifications/` and upload `backup.zip` or `backup/` with the Dataspecer specification. Optionally add a `build.sh` calling `utils/build.sh` or `cron.sh` that fetches the latest specification from a remote source that will be committed to this repository.

## Repository setup

1. Create the destination repository (`ci-exports` by default).
2. In this repository's (`ci-specifications`)
**Settings → Secrets and variables → Actions**, configure:

| Kind | Name | Value |
| --- | --- | --- |
| Secret | `EXPORT_REPOSITORY_TOKEN` | Fine-grained PAT with **Contents: Read and write** on the destination repository |
| Secret | `CRON_REPOSITORY_TOKEN` | Fine-grained PAT with **Contents: Read and write** on this repository; used to push cron updates |
| Secret | `PR_COMMENT_TOKEN` | Fine-grained PAT with **Pull requests: Read and write** on the application repository; required for PR dispatches |
| Variable | `EXPORT_REPOSITORY` | `owner/ci-exports`; defaults to this repository's owner plus `/ci-exports` |
| Variable | `DOCKER_IMAGE_REPOSITORY` | Image repository without a tag, e.g. `ghcr.io/owner/application`; required for pushes |
| Variable | `PUSH_DOCKER_TAGS` | JSON array, defaults to `["branch-main","latest"]` |

For cron updates, create a fine-grained personal access token scoped to this
repository and save it as the `CRON_REPOSITORY_TOKEN` Actions secret above. Branch
rules must allow the token owner to push. The cron workflow uses this PAT so its
commits trigger the push build workflow; pushes using `GITHUB_TOKEN` do not
([GitHub documentation](https://docs.github.com/en/actions/how-tos/write-workflows/choose-when-workflows-run/trigger-a-workflow)).

After the first export, set the destination repository's default branch to
`branch-main` in its settings. The workflow can publish to an initially empty
repository, but does not change repository settings. Branch rules must allow the
export token to create branches and push commits. Use a dedicated export repository:
each publication replaces the branch's entire tracked content with the export.

## Build script contract

For local development, run these from the repository root:

```sh
./cron-all.sh
./build-all.sh
```

`cron-all.sh` runs each specification's `cron.sh` from its own directory and is
also used by the cron workflow. `build-all.sh` runs all builds sequentially
(containers use port 80), using custom scripts or the generic fallback, and writes
to `exports/<specification>/`. Both stop on the first failure. Local scripts do not
commit or push. Builds default to `ghcr.io/dataspecer/ws:branch-main`; use
`DOCKER_TAG=latest ./build-all.sh` or set `DOCKER_IMAGE` to choose another image.

Each immediate subdirectory of `specifications/` is a specification and runs in
its own working directory. The workflow runs
`bash -e build.sh` when present, otherwise `utils/build.sh`.

Scripts receive:

- `DOCKER_IMAGE`: the full public image reference.
- `DOCKER_TAG`: published tag and destination branch name.
- `EXPORT_DIR`: absolute output path for this specification, e.g. `exports/ccmm`.
- Shared scripts in `utils/` on `PATH`, including `cleanup-export.sh`.

Write directly into `$EXPORT_DIR`. Each job has its own workspace. Outputs are
combined by extracting their archives, preserving hidden files, executable bits
and symlinks. Each build must leave at least one regular output file.

The generic builder uploads `backup.zip` if present; otherwise it zips the contents
of `backup/`. The archive must contain one top-level resource directory, whose name
is used as the IRI. It pulls the Docker image without a script timeout, starts it
on localhost port 80, and waits up to 30 seconds for `/health` to return `ok`.
It imports the archive at `/api/resources/import-zip`, downloads
`/api/experimental/output.zip?iri=...`, extracts directly into `$EXPORT_DIR`, and
runs `cleanup-export.sh` there. The container is stopped on exit, including failures.
CCMM’s custom builder then copies its XML samples to `_xml/`, rewrites their
CCMM schema URLs to relative paths, builds `tools/roundtrip`, and runs the harness
on each sample against the export. Reports go to `_roundtrip/<sample-name>/`.

Set `DOCKER_IMAGE_REPOSITORY` to `ghcr.io/dataspecer/ws` for workflow push builds.
For a local CCMM build, start at the repository root:

```sh
export PATH="$PWD/utils:$PATH"
export EXPORT_DIR="$PWD/exports/ccmm"
cd specifications/ccmm
./build.sh
```

The local default image is `ghcr.io/dataspecer/ws:branch-main`; set `DOCKER_IMAGE`
or `DOCKER_TAG` to override it. Matrix size (specifications × tags) cannot exceed
256 jobs.

## Trigger from the application pipeline

Call this after the image is available in the registry. The caller needs a token
with **Actions: Write** on **this** repository; this is separate from the token used
to push exports. `workflow_dispatch` must be present on the default branch.

```bash
GH_TOKEN="$SPECIFICATIONS_DISPATCH_TOKEN" gh api \
  --method POST repos/OWNER/ci-specifications/actions/workflows/build.yml/dispatches \
  --input - <<'JSON'
{
  "ref": "main",
  "inputs": {
    "docker_tag": "pr-123",
    "docker_image": "ghcr.io/OWNER/application@sha256:REPLACE_WITH_PUBLISHED_DIGEST",
    "source_repository": "OWNER/application",
    "source_commit": "FULL_APPLICATION_COMMIT_SHA",
    "source_commit_title": "Fix dataset serialization",
    "pr_number": "123",
    "pr_title": "Fix dataset serialization"
  }
}
JSON
```

`docker_tag`, `docker_image`, `source_commit`, and `source_commit_title` are required.
PR fields and `source_repository` are optional. For PRs, send the latest PR branch
commit SHA and its subject, not the synthetic merge commit. The application Docker
workflow checks out the PR head and reads these with `git rev-parse HEAD` and
`git log -1 --format=%s`. A full commit list is unnecessary. The export commit records that revision, image
reference, optional PR details, specifications SHA, and workflow run URL.

When `pr_number` is supplied, a successful publication creates or updates a report comment on that PR
in `source_repository` (default: `dataspecer/dataspecer`). The comment links to
`https://github.com/dataspecer/ci-exports/compare/branch-main..pr-123` for tag
`pr-123`, using the configured export repository. `branch-main` is the base and
the PR tag is the comparison target. Two dots compare the snapshots directly,
without needing a shared ancestor. Publish `branch-main` at least once before
using these comparisons. The report starts with a short bot introduction and says whether
exports are identical or gives counts of added, removed, and modified files
(including file type changes as modifications). It includes the branch comparison
link and the application commit used to generate the message, and explicitly
reports a missing baseline. The comparison link follows current branch tips.

The workflow's `GITHUB_TOKEN` cannot comment in the separate application repository,
so configure `PR_COMMENT_TOKEN` in this repository. Each successful PR dispatch
updates the same marked comment for its export repository and tag, authored by
the token owner, or creates one if absent. Keep the token owner stable to reuse comments.
Non-PR runs do not post comments.

Prefer an immutable digest reference for dispatches so all jobs build the same
image even if its tag moves. Push runs pull `DOCKER_IMAGE_REPOSITORY:<tag>` for each
configured tag; avoid moving these tags during a run if consistent image identity
across specifications is required.

Every successful publication creates a commit, even for unchanged output. New
commit subjects identify what triggered the build:

- Application dispatch: `Fix dataset serialization (abc1234)`.
- Push to this repository: `[ci-specifications repo] Update CCMM backup (def5678)`.

The hash is the first seven characters of the corresponding source commit SHA.
Full hashes and build metadata remain in the commit body. New
branches are created with `git checkout --orphan` and share no parent with other
tags; existing branches retain their history. GitHub does not guarantee dispatch order.
Pushes never force-update history. A failed build prevents publication for the run.
