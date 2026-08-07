# ha-toyota-na

## Introduction
This is a Home Assistant integration for Toyota and Subaru North America connected services.

Both brands are supported because they share one backend: SubaruConnect is not a
separate service, it is the same Toyota `ctpa-oneapi` gateway reached through a
different login tenant and a few brand-scoped request headers. You pick the brand
when you add the integration, and everything downstream behaves the same.

> **The Subaru flow is unofficial and reverse-engineered.** Subaru publishes no API
> for this. The brand headers, login tenant, and account-bootstrap call were
> recovered by decompiling the SubaruConnect Android app. Subaru can change or
> break any of it without notice. The Toyota flow is no more official, but it has
> years of community use behind it; the Subaru path does not. Treat it accordingly.

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
* Oil Status
* Key Fob Battery Status
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

Services:
* Lock/Unlock Doors (Remote Subscription Required)
* Remote Start/Stop Engine (Remote Subscription Required)
* Hazards On/Off (Remote Subscription Required)
* Refresh Data

## Subaru support

Applies to the SubaruConnect vehicles that run on the shared backend — Solterra,
Trailseeker, and Uncharted (MY23+). Vehicles on MySubaru/STARLINK are a different
service entirely and are not supported here; use the official `subaru` integration
for those.

Subaru gets the same feature set listed above, not a different one. This is parity
through a shared backend rather than a separate implementation, so whatever works
for a Toyota EV works the same way for a Solterra.

What actually differs per brand lives in one file,
[`oneapi/brands.py`](custom_components/toyota_na/oneapi/brands.py):

| | Toyota | Subaru |
|---|---|---|
| Login tenant | `login.toyotadriverslogin.com` | `login.subarudriverslogin.com` |
| `X-BRAND` / `X-APPBRAND` / `X-Brand-Id` | `T` | `S` |
| User-Agent | `ToyotaOneApp` | `SubaruConnect` |
| `GET v4/account` before vehicle discovery | not needed | required |

The OAuth realm, client ID, API keys, gateway host, GraphQL endpoint, and every
endpoint path are identical across brands.

`X-APPBRAND` is the one that trips people up: without it, Subaru login succeeds and
`v2/vehicle/guid` returns HTTP 200 with an empty list. The `v4/account` call has the
same symptom — it appears to initialize server-side session state that the Subaru
flow needs and the Toyota flow does not.

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

Subaru support rests on APK reverse-engineering done independently by two people who
arrived at matching findings — the `login.subarudriverslogin.com` tenant, the
`X-APPBRAND` header, and the `v4/account` bootstrap. That corroboration is why these
are treated as settled rather than guesswork.
