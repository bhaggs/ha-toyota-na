# ha-toyota-na

Home Assistant custom integration for **SubaruConnect** EVs (Solterra,
Trailseeker, Uncharted, MY23+), forked from `widewing/ha-toyota-na`. Toyota and
Lexus still load, but nothing in this fork is tested on them. The domain stays
`toyota_na`. Versions are `2.7.0-subaru.N`.

SubaruConnect is Toyota's `ctpa-oneapi` gateway reached through a different
ForgeRock tenant and brand headers. Subaru EVs report generation `21MM`, and
every remote command works over the older `/oneapi/` command endpoint.

## Layout

- `custom_components/toyota_na/oneapi/`: auth and client, **vendored** so the
  brand is passed at construction. Everything brand-specific lives in
  `oneapi/brands.py`. Never hardcode `X-BRAND` or a login URL elsewhere.
- `patch_*.py`: replacement classes monkey-patched onto the `toyota-na==2.1.1`
  pip package by `__init__.py` at import time. Upstream's architecture, left as
  is; they hold no brand state.
- `ev_codes.py`: decodes EV status integers from observed readings. Imports
  nothing from Home Assistant. Unknown codes pass through unchanged and are
  logged once.
- `coordinator.py`, `logbook.py`: Activity details causes (HA 2026.9).
- `polling.py`: refresh and poll intervals. The poll interval is a staleness
  floor, tracked per VIN.

## Rules

**Entity keys are permanent.** `unique_id` is `{vin}-{key}`. The display name is
separate and free to change; changing a key orphans the entity.

**Privacy.** Mask VINs to the last four in logs (`...1234`). Never log response
bodies at warning level; they carry VIN, location and account details. Event
data carries `device_id` only, never a VIN. Anything keyed by VIN in
`config_entry.data` must be re-keyed in `diagnostics.py`, because
`async_redact_data` redacts values, not keys.

**Line endings are mixed per file.** `__init__.py`, `base_entity.py`,
`binary_sensor.py`, `config_flow.py`, `sensor.py` and `manifest.json` are CRLF;
everything else is LF. `.gitattributes` stops Git converting them and
`.editorconfig` tells editors which to write; keep both lists in step with this
one. Preserve them. In scripts, use `newline=""` on read and
write: a plain round trip rewrites a CRLF file as LF, and a multi-line `\n`
match silently finds nothing.

**Timer callbacks must be `async def`**, never a lambda returning a coroutine.
Home Assistant runs a lambda as an executor job and drops the coroutine, so the
timer fires and nothing happens.

**Check Home Assistant APIs against `home-assistant/core` source**, not memory.
`hacs.json`'s `homeassistant` minimum (currently 2026.8.0) must match the real
floor of the APIs used.

## Verify

Importing the module proves nothing: names inside function bodies don't fail at
import. Run the harness, which sets up every platform, fires the timers and
checks the logbook end to end:

```sh
uv venv -p 3.14 /tmp/ha-venv
uv pip install -p /tmp/ha-venv "homeassistant==2026.9.3" "toyota-na==2.1.1" \
    SQLAlchemy fnv-hash-fast psutil-home-assistant
/tmp/ha-venv/bin/python scripts/verify_integration.py
```

Every check must pass before a release. Add checks for new behaviour there.

## Git and GitHub

- `gh` defaults to the upstream parent repo. Always pass
  `--repo bhaggs/ha-toyota-na` to `gh pr` and `gh issue`.
- Commits go to `master`. Don't commit until the maintainer has reviewed.
- Never `@`-mention people in commits, PRs, issues or release notes; it notifies
  them. Credit by plain name. Profile links in the README are fine.

## Changelog and releases

Cut releases with the `/release` skill (`.claude/skills/release/`), which runs
these steps in order.

- `CHANGELOG.md` follows Keep a Changelog 1.1.0: `## [Unreleased]`, then
  `## [2.7.0-subaru.N] - YYYY-MM-DD` with `### Added / Changed / Fixed /
  Removed`, breaking changes first in their group. Add to `Unreleased` as work
  lands.
- Changelog entries and release notes cover **code changes only**: no README or
  docs edits, and no repeated contributor credit.
- Release titles are the bare version (`v2.7.0-subaru.N`); the notes explain.
- `gh release create --repo bhaggs/ha-toyota-na` triggers
  `.github/workflows/release.yml`, which builds `ha_toyota_na.zip`. Check the
  published asset, not just the tag.
- Gate a risky release with `--prerelease`, never a version suffix:
  `2.7.0-subaru.16-beta.1` sorts below `.15` in HACS. Bump
  `manifest.json`'s `version` to match the tag.
