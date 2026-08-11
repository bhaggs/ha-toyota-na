# ha-toyota-na — Subaru Connect for Home Assistant

Home Assistant integration for **Subaru Connect** vehicles in North America:
Solterra, Trailseeker, and Uncharted (MY23+).

A fork of [widewing/ha-toyota-na](https://github.com/widewing/ha-toyota-na)
focused on the Subaru experience. Toyota and Lexus vehicles still work exactly as
before — see [Toyota vehicles](#toyota-vehicles).

> **Unofficial and reverse-engineered.** Subaru publishes no API for this. The
> login tenant, brand headers, and account bootstrap were recovered from the
> Subaru Connect Android app by [@adepssimius](https://github.com/adepssimius)
> and [@keithnet](https://github.com/keithnet) — see [Credits](#credits). Subaru
> can change or break any of it without notice.
>
> Login, vehicle discovery, EV telemetry, and remote commands have all been
> verified end-to-end against a real 2026 Solterra.

## Not for MySubaru / STARLINK

If your Subaru uses the **MySubaru** app, this will not work — that is STARLINK,
a different platform. Use the official
[`subaru`](https://www.home-assistant.io/integrations/subaru/) integration
instead.

Subaru Connect is the newer platform used by the models above. If you sign in at
`subarudriverslogin.com`, you are in the right place.

## Why this works at all

Subaru Connect is not a separate service. It is the same Toyota `ctpa-oneapi`
gateway the Toyota app talks to, reached through a different login tenant and a
few brand-scoped request headers — Subaru's connected-services platform is
supplied by Toyota.

So Subaru support here is *parity through a shared backend*, not a separate
implementation. Whatever works for a Toyota EV works the same way for a Solterra, Trailseeker, or Uncharted.

Everything that differs lives in one file,
[`oneapi/brands.py`](custom_components/toyota_na/oneapi/brands.py):

| | Subaru | Toyota |
|---|---|---|
| Login tenant | `login.subarudriverslogin.com` | `login.toyotadriverslogin.com` |
| `X-BRAND` / `X-APPBRAND` / `X-Brand-Id` | `S` | `T` |
| User-Agent | `SubaruConnect` | `ToyotaOneApp` |
| `GET v4/account` retry on empty discovery | yes | no |

The OAuth realm, client ID, API keys, gateway host, GraphQL endpoint, and every
endpoint path are identical across brands.

`X-APPBRAND` is the one that matters: without it, login still succeeds but
`v2/vehicle/guid` returns an empty list. Why each of the others is sent, and what
was measured versus assumed, is documented in the code.

## Installation

Requires [HACS](https://hacs.xyz/docs/setup/download).

1. HACS → ⋮ → **Custom repositories**
2. Add `https://github.com/bhaggs/ha-toyota-na` as an **Integration**
3. Install **Toyota / Subaru (North America)**, then restart Home Assistant
4. **Settings → Devices & Services → Add Integration**, search for
   *Toyota / Subaru (North America)*
5. Choose **Subaru**, sign in, and enter the one-time code sent to your email or
   phone

Releases are versioned `2.7.0-subaru.N`, marking the upstream release this fork
is built on.

## What you get

Most of this requires an active Remote Services subscription.

**Vehicle state** — doors, windows, moonroof, hood, and trunk open/closed; door
and trunk lock state; current and last-parked location; odometer, speed, trip A
and B, fuel level, distance to empty; tire pressures including spare; next
service; last-update timestamps.

**EV** — battery level, range with and without
climate, travelable distance, charging state, connector state, plug state, charge
type, remaining charge time.

**Controls** — lock/unlock; remote start/stop as a switch reporting whether the
vehicle is running and for how much longer (on an EV this is climate
preconditioning); hazards; buzzer; refresh.

Every control is available both as an entity and as a service, so automations
built on the services keep working. Stateful features are switches, one-shot
commands are buttons.

### Known gaps

- **Lights.** The Subaru Connect app has a lights control. Its command string is
  unknown — `light-on` returns HTTP 400 — so there is no button for it yet. See
  [identifying unknown commands](#identifying-unknown-commands).
- **`Charge Type` and `Plug Status`** still report raw integers; `Connector
  Status` is decoded.
  ([#3](https://github.com/bhaggs/ha-toyota-na/issues/3))
- **`Remaining Charge Time`** carries no unit, because whether it reports minutes
  or seconds is unconfirmed. It does correctly report unknown when unplugged.
- **Key fob battery and oil life** appear in the app but not here. They were
  advertised in the upstream README for years and never implemented; the data may
  live in the unused `v1/vehiclehealth/*` endpoints.

## 12V battery safety

Only one thing here touches the vehicle. The 10-minute poll reads cached state
from Toyota's servers and never contacts the car, so it costs nothing. The
**2-hour refresh** wakes the telematics unit, as do the `Refresh Data` button and
the `toyota_na.refresh` service.

That is about 12 wakes a day. While charging or running, the DC-DC converter
maintains the 12V and wakes are effectively free; the risk window is a vehicle
parked and unplugged for a long stretch. Making these intervals configurable is
[#2](https://github.com/bhaggs/ha-toyota-na/issues/2).

## Troubleshooting

### Setup fails, or no vehicles appear

`scripts/validate_brand.py` exercises login and vehicle discovery with no Home
Assistant involved:

```bash
pip install aiohttp pyjwt
python scripts/validate_brand.py --brand S --username you@example.com
```

It prints masked VINs and counts only — never response bodies — so its output is
safe to paste into an issue.

`--matrix` probes every header and bootstrap permutation on a single login, which
matters because each login costs a one-time code. `--no-appbrand`,
`--no-brand-id`, `--no-bootstrap`, and `--user-agent` isolate individual
requirements if the backend shifts.

A successful login with an empty vehicle list almost always means a missing
`X-APPBRAND` header or a skipped account bootstrap.

### Debug logging

```yaml
logger:
  logs:
    custom_components.toyota_na: debug
```

Gateway failures log method, URL, status, and a truncated body. Full response
bodies are never logged at any level — they contain VIN, precise location, and
account details.

### Identifying unknown commands

The gateway's command vocabulary is undocumented and differs between brands. To
test a candidate:

**Developer Tools → Actions → *Send raw command (advanced)***

An unrecognised command returns HTTP 400 and surfaces as an error in the UI. Be
deliberate about what you send — the vocabulary includes things like
`power-window-open`.

## Toyota vehicles

Still fully supported and unchanged. Brand defaults to Toyota, and config entries
created before Subaru support keep working untouched — upgrading will not
re-prompt or reconfigure anything.

A Toyota and a Subaru account can run side by side in one Home Assistant
instance. Brand is fixed when the client is constructed and each config entry
holds its own tokens, so the two never share auth state, even with the same email
address on both.

Several fixes made while building Subaru support apply to Toyota vehicles too:
timestamps rendering as real times rather than epoch integers, request timeouts
so a stalled call cannot wedge the integration, remote start as a stateful
switch, connector status decoding, and the battery level in the device header.

## Credits

[@widewing](https://github.com/widewing) and
[@vanstinator](https://github.com/vanstinator) for
[ha-toyota-na](https://github.com/widewing/ha-toyota-na), which this is built on.

[@DurgNomis-drol](https://github.com/DurgNomis-drol) for the original
[Toyota integration](https://github.com/DurgNomis-drol/ha_toyota) and the
[discussion](https://github.com/DurgNomis-drol/mytoyota/issues/7) that started
it.

[@visualage](https://github.com/visualage) for working out headless
authentication.

Subaru support rests on APK reverse-engineering done independently by
[@adepssimius](https://github.com/adepssimius) and
[@keithnet](https://github.com/keithnet), who arrived at matching findings — the
`login.subarudriverslogin.com` tenant, the `X-APPBRAND` header, and the
`v4/account` bootstrap. This integration only implements what they worked out.
