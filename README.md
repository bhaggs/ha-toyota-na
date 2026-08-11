# ha-toyota-na

## Introduction
This is a Home Assistant integration for Toyota and Subaru North America connected services.

Both brands are supported because they share one backend: SubaruConnect is not a
separate service, it is the same Toyota `ctpa-oneapi` gateway reached through a
different login tenant and a few brand-scoped request headers. You pick the brand
when you add the integration, and everything downstream behaves the same.

> **The Subaru flow is unofficial and reverse-engineered.** Subaru publishes no API
> for this. The brand headers, login tenant, and account-bootstrap call were
> recovered by [@adepssimius](https://github.com/adepssimius) and
> [@keithnet](https://github.com/keithnet) from the SubaruConnect Android app —
> see [Credits](#credits). Subaru can change or
> break any of it without notice. The Toyota flow is no more official, but it has
> years of community use behind it; the Subaru path does not. Treat it accordingly.
>
> Login, vehicle discovery, EV telemetry, and remote commands have all been verified
> end-to-end against a real Solterra.

## Stable
![GitHub release (latest by date)](https://img.shields.io/github/v/release/widewing/ha-toyota-na?style=for-the-badge) ![GitHub Release Date](https://img.shields.io/github/release-date/widewing/ha-toyota-na?style=for-the-badge) ![GitHub Releases](https://img.shields.io/github/downloads/widewing/ha-toyota-na/latest/total?color=purple&label=%20release%20Downloads&style=for-the-badge) 

## Current features
Certain entities and services require the Remote Subscription.

Sensors:
* Door lock status (Remote Subscription Required)
* Window/Moonroof status (Remote Subscription Required)
* Trunk Status (Remote Subscription Required)
* Real time location (Remote Subscription Required)
* Last Parked Location
* Tire Pressure
* Fuel Level
* Odometer
* Last Update
* Last Tire Pressure Update
* Speed
* EV Plug Status
* EV Remaining Charge Time
* EV Travel Distance
* EV Charge Type
* EV Charge Start Time
* EV Charge End Time
* EV Connector Status
* EV Charging Status

Controls and services (all require a Remote Subscription):
* Lock/Unlock Doors (lock entity)
* Remote Start/Stop (switch; reports whether the vehicle is running and for how
  much longer. On an EV this is climate preconditioning)
* Hazards On (momentary; the vehicle auto-offs after ~60s)
* Lights On/Off (17CYPLUS and later)
* Buzzer (17CYPLUS and later)
* Refresh Data

Each is available as an entity on the vehicle's device page and as a service, so
existing automations built on the services keep working. Stateful features are
switches, one-shot commands are buttons.

## Subaru support

Works for vehicles which use the SubaruConnect app–Solterra, Trailseeker, and Uncharted (MY23+).

Vehicles which use the MySubaru app are not supported here; use the official `subaru` integration for those.

Subaru vehicles get the same feature set listed above.

What actually differs per brand lives in one file,
[`oneapi/brands.py`](custom_components/toyota_na/oneapi/brands.py):

| | Toyota | Subaru |
|---|---|---|
| Login tenant | `login.toyotadriverslogin.com` | `login.subarudriverslogin.com` |
| `X-BRAND` / `X-APPBRAND` / `X-Brand-Id` | `T` | `S` |
| User-Agent | `ToyotaOneApp` | `SubaruConnect` |
| `GET v4/account` retry on empty discovery | no | yes |

The OAuth realm, client ID, API keys, gateway host, GraphQL endpoint, and every
endpoint path are identical across brands.

`X-APPBRAND` is the one that trips people up, and it is the one requirement measured
against a live Subaru account: without it, login still succeeds and
`v2/vehicle/guid` returns HTTP 200 with an empty list.

`X-Brand-Id` and the brand User-Agent were both measured as *not* enforced. They are
sent anyway, to match what the real app does, on the theory that looking like the
real client is cheap insurance if the backend ever tightens.

The `v4/account` bootstrap is the interesting one. It was reported as required before
`v2/vehicle/guid` would return anything, but live testing on an active account did
not reproduce that — discovery worked on a fresh session with no bootstrap at all.
The likely explanation is that the call initializes account state once and
permanently, so any account that has used the SubaruConnect app is already
initialized. Rather than guess, the integration calls it only as a retry when
discovery comes back empty: an established account pays nothing, a fresh one still
gets rescued.

### Running both brands at once

A Toyota and a Subaru account can live in the same Home Assistant instance. Brand is
passed to the client at construction, and each config entry holds its own tokens, so
the two never share auth state. If you use the same email address for both, they
still get distinct config entries.

### Troubleshooting

When something breaks, `scripts/validate_brand.py` exercises just login and vehicle
discovery, with no Home Assistant involved:

```bash
pip install aiohttp pyjwt
python scripts/validate_brand.py --brand S --username you@example.com
```

It prints masked VINs and counts only, never full response bodies, so its output is
safe to paste into an issue. `--no-appbrand`, `--no-brand-id`, `--no-bootstrap`, and
`--user-agent` let you isolate which requirement changed if the backend shifts.

## Installation
### HACS
1. Install HACS: https://hacs.xyz/docs/setup/download
2. Search and install "Toyota (North America)" in HACS integration store

### Manual installation:
1. Download this repo by either of the following method
- `git clone https://github.com/widewing/ha-toyota-na`
- Download https://github.com/widewing/ha-toyota-na/archive/refs/heads/master.zip
2. Copy or link this repo into Home Assistant "custome_components" directory
- `ln -s ha-toyota-na/custom_components/toyota_na ~/.homeassistant/custom_components/`

## Configuration
Click "Add integration" from Home Assistant, search "Toyota / Subaru (North America)", click to add.

Select your brand, enter the username and password for that brand's app, then the OTP
sent to your email or phone. Brand defaults to Toyota, so existing setups are
unaffected — upgrading will not touch or re-prompt your current Toyota entries.

After setting up, most information in the Toyota One or SubaruConnect app should be
available in Home Assistant.
![image](https://user-images.githubusercontent.com/4755389/147372481-4d280b6e-6f61-434c-a768-f4a089f009c3.png)

## Credits
Thanks @DurgNomis-drol for making the the original [Toyota Integration](https://github.com/DurgNomis-drol/ha_toyota) and bringing up the discussion thread at https://github.com/DurgNomis-drol/mytoyota/issues/7.

Thanks @visualage for finding the way to authenticate headlessly.

Subaru support is based on the reverse-engineering work done by
[@adepssimius](https://github.com/adepssimius) and
[@keithnet](https://github.com/keithnet).