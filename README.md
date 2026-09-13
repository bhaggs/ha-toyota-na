# ha-toyota-na — SubaruConnect for Home Assistant

Home Assistant integration for **SubaruConnect** vehicles in North America: Solterra, Trailseeker, and Uncharted (MY23+).

This is a fork of [widewing/ha-toyota-na](https://github.com/widewing/ha-toyota-na) focused on the Subaru experience. Toyota and Lexus vehicles are still supported, but changes and improvements from this fork have not been tested on those vehicles — see [Toyota vehicles](#toyota-vehicles).

> **Unofficial and reverse-engineered.** Subaru publishes no API documentation. The
> login tenant, brand headers, and account bootstrap were recovered from the
> SubaruConnect Android app by [@adepssimius](https://github.com/adepssimius)
> and [@keithnet](https://github.com/keithnet) — see [Credits](#credits). Subaru
> can change or break any of it without notice.

> [!NOTE]
> This integration is for Subaru's EVs only (those which use the SubaruConnect app). For Subaru's gas and PHEV models, use the official [`subaru`](https://www.home-assistant.io/integrations/subaru/) integration instead.

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

**EV** — battery level, range with and without climate, travelable distance,
charging state, connector state, plug state, charge type, and charge time both as
minutes remaining and as the moment charging finishes.

**Controls**

| Control | What it does |
|---|---|
| Doors | Lock and unlock. |
| Remote start | Climate preconditioning, despite the name — the command the backend takes is `engine-start`. A switch rather than buttons, because the vehicle reports whether it is running and for how much longer. |
| Hazards | Flashes the hazard lights. Momentary: the vehicle stops them after about a minute on its own. |
| Buzzer | A short digital beep from the vehicle's external speaker, for locating it in a parking lot. |
| Horn | Two short chirps of the actual horn. Louder and more attention-getting than the buzzer. |
| Headlights | Turns on the headlights. Momentary, like the hazards — the vehicle turns them off itself. |
| Refresh | Re-reads what the servers already hold. Never contacts the vehicle, so it costs nothing. |
| Poll vehicle | Wakes the telematics unit and tells it to upload fresh state. The only control that touches the vehicle — see [Polling and the 12V battery](#polling-and-the-12v-battery). |

Every control is available both as an entity and as a service.

### Known gaps

- **`Charging type`** still reports a raw integer; `Charging plug` and `Charging
  connector` are decoded.
  ([#3](https://github.com/bhaggs/ha-toyota-na/issues/3))
- **Key fob battery** appears in the app but not here. It was
  advertised in the upstream README for years and never implemented; the data may
  live in the unused `v1/vehiclehealth/*` endpoints.

## Polling and the 12V battery

Two things happen on a timer, and only one of them touches the vehicle.

| | What it does | Cost to the vehicle | Default |
|---|---|---|---|
| **Refresh** | Reads state the servers already hold | Nothing — the vehicle is never contacted | every 10 minutes |
| **Poll vehicle** | Wakes the telematics unit and tells it to upload | Draws on the 12V battery | every 2 hours |

Both are configurable. Go to **Settings → Devices & Services → Toyota / Subaru
(North America) → Configure**, and set either to **0 to turn it off entirely**.

The poll interval is a **staleness floor, not a fixed cadence**: it wakes the
vehicle only if nothing has polled it for that long. The Poll vehicle button and
`toyota_na.poll_vehicle` count, so an automation that polls when you get home
pushes the next scheduled poll back rather than being followed by a second wake
minutes later. With nothing else polling, it behaves exactly like a plain
interval. Each vehicle on the account is tracked separately.

The poll is the one that matters. At the 2-hour default that is about twelve
wakes a day. While the vehicle is charging or running, the DC-DC converter
maintains the 12V and a wake costs effectively nothing — the risk window is a
vehicle parked and unplugged for days at a stretch, which is exactly when a fixed
2-hour cycle is least useful and most harmful. Solterras in particular have a
documented history of 12V complaints.

Turning the poll off does not mean losing data. The Refresh side keeps working,
21MM+ vehicles push updates over a WebSocket when the engine is switched off, and
you can wake the vehicle on your own terms:

```yaml
# Wake the vehicle when you get home, to see whether it got plugged in
triggers:
  - trigger: zone
    entity_id: person.you
    zone: zone.home
    event: enter
actions:
  - action: toyota_na.poll_vehicle
    data:
      vehicle: <device id>
```

`sensor.<your_car>_last_updated` is the vehicle's own report timestamp, so it is
the right thing to test against for "poll only if nothing has come in lately":

```yaml
conditions:
  - condition: template
    value_template: >
      {{ now() - states('sensor.solterra_last_updated') | as_datetime
         > timedelta(hours=24) }}
```

Both controls exist as buttons and as services (`toyota_na.refresh` and
`toyota_na.poll_vehicle`). Home Assistant's built-in
`homeassistant.update_entity` on any of the vehicle's entities is equivalent to
Refresh.

Two further reductions are still open:
[skipping the wake while the vehicle is plugged in, and trimming what each wake
sends](https://github.com/bhaggs/ha-toyota-na/issues/2).

## Troubleshooting

### Debug logging

Settings → Devices & Services → **Toyota / Subaru (North America)** → the
three-dot menu → **Enable debug logging**. Reproduce the problem, then **Disable
debug logging**, and the browser downloads the log. Or in `configuration.yaml`:

```yaml
logger:
  logs:
    custom_components.toyota_na: debug
```

### Nothing is updating on its own

The integration states its schedule once per load, at info level, so this is
visible without enabling debug:

```
Refreshing from Subaru every 0:10:00; polling the vehicle every 2:00:00
Refreshing from Subaru only on request; polling the vehicle only on request
```

A vehicle poll that actually ran also logs at info:

```
Polling 2024 Solterra for fresh state
```

If the schedule line says `only on request`, the interval is set to 0 — see
[Polling and the 12V battery](#polling-and-the-12v-battery).

There is a **second, easily-missed off switch**: Home Assistant's own *Enable
polling for updates*, under the entry's three-dot menu → **System options**. It
silently overrides the refresh interval. When it is off and an interval is set,
you will see:

```
Refreshing is set to every 0:10:00, but Home Assistant's own "Enable polling
for updates" option is off for this entry, so no scheduled refresh will happen.
```

With debug on, you also get a line per cloud read (`Updating vehicle status`)
and the reason a scheduled poll was skipped (`Skipping scheduled poll; last one
was N minutes ago` — the guard that stops a restart loop becoming a wake loop).

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

### Entity IDs and Sensor Names

Sensor naming and entity ID definition were modernized to conform to Home Assistant's current best practices. As such, Home Assistant will dynamically generate entity IDs in the following structure: **area + device + entity**, resulting in an ID like `binary_sensor.garage_2026_solterra_charging`.

This format structure can be changed by going to **Settings → System → Entity ID format**. Note, that this is a system-wide setting rather than a per-integration one.

## Why this works at all

SubaruConnect is not a separate service. It is the same Toyota `ctpa-oneapi`
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

## Toyota vehicles

Still supported but changes made as part of this fork have **not** been tested on Toyota vehicles.

A Toyota and a Subaru account can run side by side in one Home Assistant
instance. Brand is fixed when the client is constructed and each config entry
holds its own tokens, so the two never share auth state, even with the same email
address on both.

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
[@keithnet](https://github.com/keithnet).
