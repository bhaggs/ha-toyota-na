# Changelog

All notable changes to this fork are documented here. The format is based on
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/). Each version links to
its GitHub release, which carries the full notes — the reasoning, the log lines
to look for, and any upgrade steps.

Versions read `2.7.0-subaru.N`: upstream `widewing/ha-toyota-na` **2.7.0**, plus
this fork's increment. The suffix is deliberate, so a future upstream 2.8.0 can
be different code without colliding. For history before the fork, see
[upstream's releases](https://github.com/widewing/ha-toyota-na/releases).

## [Unreleased]

Nothing yet.

## [2.7.0-subaru.18] - 2026-09-19

### Added

- Activity details names what caused each update (Home Assistant 2026.9):
  *Scheduled poll vehicle*, *Cloud refresh*, or the person or automation that
  asked. Reports the vehicle sends on its own are described as picked up, never
  given a reason — the gateway does not say why a vehicle reported.

### Changed

- **Minimum Home Assistant is now 2026.8.0.** The device lookup uses an API added
  in 2026.8; the one it replaces breaks in 2027.8. The previous claim of 2025.8.0
  was already wrong — services have needed 2025.10.0 since v2.6.10.
- The poll interval is a staleness floor: the vehicle is woken only if nothing has
  polled it for that long, and a button press or service call counts. An
  automation polling on arrival no longer gets a second wake minutes later.
- Poll times are tracked per VIN, so polling one vehicle no longer defers another
  on the same account.
- The Refresh option recommends about 5 minutes as a minimum, as a precaution
  against the servers' rate limiting.

### Fixed

- A poll the servers refuse no longer counts as a poll. Every error in the refresh
  path was swallowed, so a refused poll — usually rate limiting — was recorded as
  successful, pushed the next scheduled poll back, and reported success on the
  button.
- Poll timestamps are a real epoch again. `datetime.utcnow().timestamp()` is not
  one, and drifted by an hour at each daylight-saving change.

## [2.7.0-subaru.17] - 2026-09-13

*Pre-release.*

### Added

- Both intervals are configurable through an options flow, either settable to 0
  for never. Defaults match the values that were hardcoded before.
- The schedule is logged once at startup, and Home Assistant's own *Enable polling
  for updates* option — a second, easily-missed off switch — now warns when it
  silently overrides the refresh interval.

### Changed

- **Breaking: Refresh and Poll vehicle swapped meaning**, as buttons and as
  services, to match the MySubaru integration. **Refresh** reads the servers;
  **Poll vehicle** wakes the car. Anything calling `toyota_na.refresh` to wake a
  vehicle needs `toyota_na.poll_vehicle` instead.
- Minimum Home Assistant raised to 2025.8.0.

### Fixed

- Re-cut after the first build: the scheduled poll never ran at all, because the
  timer was given a callable Home Assistant does not await.

## [2.7.0-subaru.16] - 2026-08-28

### Fixed

- Only demand a new sign-in when the credentials are actually rejected. Any
  non-200 from the token endpoint was treated as a credentials failure, so a
  momentary 5xx raised an *authentication expired* repair and asked for a one-time
  code. Rejections and outages are now told apart, and both are logged.

## [2.7.0-subaru.15] - 2026-08-26

### Added

- **Horn** and **Headlights** buttons.

### Changed

- The command vocabulary is recorded from what was actually tried on a Solterra —
  accepted, accepted with no effect, and rejected — rather than from an inherited
  list.
- `send_command` reports what the gateway replied, since failures arrive inside
  200 responses as well as by status code.

## [2.7.0-subaru.14] - 2026-08-25

### Fixed

- **Charging finishes** no longer slides forward. It anchors to the vehicle's own
  reading instead of being recomputed from the clock on every poll.

## [2.7.0-subaru.13] - 2026-08-18

### Added

- The charging sensors keep their raw code as an attribute, so an unmapped value
  is still visible.

### Changed

- Charging type is wired up ready for mapping.

## [2.7.0-subaru.12] - 2026-08-18

### Changed

- Charging type no longer records statistics, which produces a repair notice on
  upgrade.

### Fixed

- **Charging plug** and **Charging connector** draw a proper history again. An
  empty-string unit had left their charts blank.

## [2.7.0-subaru.11] - 2026-08-18

### Added

- **Charging finishes**, the charge-time reading expressed as the moment it lands
  on, so dashboards show "in 3 hours" rather than "180 min".

## [2.7.0-subaru.10] - 2026-08-17

### Changed

- **Charging plug** reads words instead of a raw number.
- **Charging time remaining** is in minutes, confirmed against a real charge.

## [2.7.0-subaru.9] - 2026-08-16

### Changed

- **Breaking: delete and re-add the integration.**
- Entity names follow Home Assistant convention, so the device name is no longer
  repeated in every entity.
- Identity no longer depends on the label: entities carry a stable key, so
  renaming one stops orphaning it.

## [2.7.0-subaru.8] - 2026-08-11

### Fixed

- Setup failing in `.7`. A name referenced inside a function body does not fail at
  import, so the checks of the day did not catch it.

## [2.7.0-subaru.7] - 2026-08-11

### Added

- `toyota_na.send_command`, for identifying commands the integration does not yet
  know.

### Changed

- Hazards renamed; whole numbers lose their trailing `.0`.
- README rewritten around Subaru.

### Removed

- The Lights buttons: the commands are rejected by the gateway.

## [2.7.0-subaru.6] - 2026-08-11

### Added

- More remote-command buttons.
- EV status codes are decoded into readable values.

### Changed

- **Breaking: remote start is a switch** rather than two buttons, since the
  vehicle reports whether it is running.
- Hazards became one button instead of two.

## [2.7.0-subaru.5] - 2026-08-11

### Added

- The remote commands became buttons, so they appear on the device page rather
  than existing only as services.

## [2.7.0-subaru.4] - 2026-08-11

### Changed

- EV battery level appears in the device header; Next Service moved to
  diagnostics.

### Fixed

- Entities no longer go unavailable and stay that way. Requests had no timeout, so
  one stalled request wedged the integration until a reload.
- Timestamp sensors show times instead of raw epoch numbers.
- EV travelable distance gained its unit.

## [2.7.0-subaru.3] - 2026-08-10

### Added

- `scripts/validate_brand.py` gained `--two-phase`, reproducing the split-session
  flow Home Assistant actually uses.

### Fixed

- The ForgeRock affinity cookie is preserved across the OTP step. The login spans
  two calls, each of which opened its own session, so the second could land on a
  node that had never issued the session — rejecting a valid code.

## [2.7.0-subaru.2] - 2026-08-10

### Added

- `scripts/validate_brand.py` gained `--matrix`, probing every header and
  bootstrap permutation on a single login.

### Changed

- Live testing confirmed `X-APPBRAND` is what gates Subaru vehicle discovery, and
  that the `v4/account` bootstrap is not needed on an established account — it now
  fires only as a retry when discovery comes back empty.

### Fixed

- Subaru setup failing with a generic "unknown error" after the OTP step. The flow
  assumed an `email` claim, which Subaru's tenant does not return; accounts now
  fall back to the account GUID.
- The release workflow lacked `contents: write`, so earlier assets had to be
  attached by hand.

## [2.7.0-subaru.1] - 2026-08-08

First release of this fork, built on upstream v2.7.0.

### Added

- **SubaruConnect support** — Solterra, Trailseeker and Uncharted (MY23+), which
  run on the same Toyota `ctpa-oneapi` gateway behind a different login tenant and
  a few brand headers. The brand is chosen when adding the integration.
  MySubaru/STARLINK vehicles are a different service and need the official
  `subaru` integration.

### Changed

- Auth and client are vendored under `oneapi/` with the brand passed at
  construction, replacing an import-time mutation that would have made a Toyota
  and a Subaru entry overwrite each other's login endpoints.
- Existing Toyota users are unaffected: brand defaults to Toyota, and Toyota keeps
  its original unique id, so no entry is orphaned.
