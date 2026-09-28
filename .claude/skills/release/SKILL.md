---
name: release
description: Cut a ha-toyota-na release - changelog, manifest version, verification, tag, GitHub release, and a check of the published zip. Use only when the maintainer asks to cut, publish or promote a release.
argument-hint: "[prerelease]"
disable-model-invocation: true
---

# Cut a release

Publishing a release reaches every HACS user, so confirm with the maintainer
before step 5 and stop on any failure. Pass `--repo bhaggs/ha-toyota-na` to
every `gh` command; without it `gh` targets the upstream parent.

With the argument `prerelease`, publish with `--prerelease`. Never put `beta`
or similar in the version: `2.7.0-subaru.16-beta.1` sorts below `.15`.

## 1. Work out the version

```sh
gh release list --repo bhaggs/ha-toyota-na --limit 3
git status -sb
```

The new version is the latest `2.7.0-subaru.N` plus one. The tree must be clean
and on `master`, level with `origin/master`. Anything uncommitted is the
maintainer's to commit or discard first.

## 2. Changelog

In `CHANGELOG.md`, rename `## [Unreleased]` to
`## [2.7.0-subaru.N] - YYYY-MM-DD` (today's date) and put a fresh
`## [Unreleased]` above it containing `Nothing yet.`

If `Unreleased` was empty, stop: there is nothing to release.

Entries cover code changes only. Remove any README or docs entries, and any
contributor credit. Don't add a "Pre-release" line; the GitHub flag says so.

## 3. Manifest version

Set `"version"` in `custom_components/toyota_na/manifest.json` to
`2.7.0-subaru.N`. The file is CRLF: edit it in place, and confirm with
`git diff` that only that line changed.

If the release depends on a newer Home Assistant API, raise `hacs.json`'s
`homeassistant` minimum to the version that introduced it.

## 4. Verify

Run `scripts/verify_integration.py` as described in CLAUDE.md. Every check must
pass. Report failures to the maintainer rather than working around them.

## 5. Confirm, commit, tag

Show the maintainer the version, the changelog section that will become the
notes, and whether it is a prerelease. Wait for their go-ahead. Then:

```sh
git commit -am "Release 2.7.0-subaru.N"
git tag v2.7.0-subaru.N
git push origin master v2.7.0-subaru.N
```

## 6. Publish

Write the notes to a file in the scratchpad: the changelog section body,
without its `## [...]` heading. If the release needs action from people
upgrading (a breaking change, a re-add, a raised minimum), open with a short
blockquote saying what to do.

```sh
gh release create v2.7.0-subaru.N --repo bhaggs/ha-toyota-na \
  --title v2.7.0-subaru.N --notes-file <notes> [--prerelease]
```

The title is the bare version. No `@`-mentions anywhere in the notes.

## 7. Check what was published

The `Release` workflow builds and attaches `ha_toyota_na.zip`. Wait for it:

```sh
gh run list --repo bhaggs/ha-toyota-na --workflow release.yml --limit 1
gh run watch <run-id> --repo bhaggs/ha-toyota-na --exit-status
```

Then download the asset and confirm it's the right build:

```sh
gh release download v2.7.0-subaru.N --repo bhaggs/ha-toyota-na \
  --pattern ha_toyota_na.zip --dir <scratchpad>
unzip -p <scratchpad>/ha_toyota_na.zip manifest.json | grep '"version"'
unzip -l <scratchpad>/ha_toyota_na.zip | grep -c '\.py$'
```

The version must match the tag, and the files must sit at the zip root, not
under `custom_components/`. Finally, read the published release back with
`gh release view` and check the title, the prerelease flag, and that the notes
contain no leftover pre-release wording.

## Promoting a prerelease

To promote an existing prerelease, don't rebuild it:

```sh
gh release edit v2.7.0-subaru.N --repo bhaggs/ha-toyota-na --prerelease=false --latest
```

Then remove any prerelease wording from both the release notes and
`CHANGELOG.md`.
