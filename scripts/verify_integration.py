"""Run the integration for real against Home Assistant and check what it does.

Deliberately not an import check. A name referenced inside a function body does
not fail at import, which is how a NameError once reached a release; and a timer
handed a callable Home Assistant never awaits still "registers" fine, which is
how a dead scheduled poll once did. So this runs async_setup, every platform's
async_setup_entry and the timers, and asserts on behaviour.

Requires Python 3.14.2 or later (Home Assistant's own floor), and:

    pip install "homeassistant==2026.9.2" "toyota-na==2.1.1" \\
        SQLAlchemy fnv-hash-fast psutil-home-assistant

The last three are the recorder's requirements, needed for the end-to-end
Activity details check. Run from the repository root:

    python scripts/verify_integration.py

Nothing is written to the repository; everything lives in a temp directory.
Exits non-zero if any check fails.
"""
import asyncio
import logging
import sys
import tempfile
import time
import traceback
import types
from datetime import timedelta
from pathlib import Path
from unittest.mock import patch

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from homeassistant import loader  # noqa: E402
from homeassistant.config_entries import (  # noqa: E402
    ConfigEntries,
    ConfigEntryState,
    OptionsFlowWithReload,
)
from homeassistant.core import (  # noqa: E402
    Context,
    HassJobType,
    HomeAssistant,
    callback,
    get_hassjob_callable_job_type,
)
from homeassistant.helpers import (  # noqa: E402
    device_registry as dr,
    entity_registry as er,
)
from homeassistant.helpers.update_coordinator import CoordinatorEntity  # noqa: E402
import homeassistant.util.dt as dt_util  # noqa: E402

import custom_components.toyota_na as pkg  # noqa: E402
from custom_components.toyota_na import (  # noqa: E402
    PLATFORMS,
    async_scheduled_poll,
    async_setup,
    async_setup_entry,
    config_flow,
    coordinator as coord_mod,
    logbook as toyota_logbook,
)
from custom_components.toyota_na.base_entity import ToyotaNABaseEntity  # noqa: E402
from custom_components.toyota_na.const import (  # noqa: E402
    DOMAIN,
    EVENT_VEHICLE_POLLED,
    EVENT_VEHICLE_REPORT,
)
from custom_components.toyota_na.coordinator import (  # noqa: E402
    CAUSE_TTL_SECONDS,
    ToyotaCoordinator,
    async_fire_cause,
)
from custom_components.toyota_na.oneapi import get_brand  # noqa: E402
from custom_components.toyota_na.patch_base_vehicle import (  # noqa: E402
    ApiVehicleGeneration,
    VehicleFeatures,
)
from custom_components.toyota_na.polling import (  # noqa: E402
    LEGACY_POLLED_AT,
    POLLED_AT,
    async_poll_now,
    fetch_interval,
    poll_due,
    poll_interval,
)

FAILED: list[str] = []
TMP = tempfile.mkdtemp(prefix="toyota_na_verify_")
REAL_SLEEP = asyncio.sleep
LOG = logging.getLogger("verify")


def check(label: str, cond: bool, extra: str = "") -> None:
    print(("  PASS  " if cond else "  FAIL  ") + label + (f"   {extra}" if extra else ""))
    if not cond:
        FAILED.append(label)


def fast_sleep():
    """Skip REFRESH_SETTLE_SECONDS. Captured first, or the patch recurses."""
    return patch(
        "custom_components.toyota_na.polling.asyncio.sleep",
        new=lambda _seconds: REAL_SLEEP(0),
    )


def fake_device_registry():
    """A device registry that knows every vehicle, as device-abc."""
    # Deliberately no async_get_device: it is deprecated from 2026.9, so a call
    # to it creeping back in should fail here rather than pass quietly.
    device = types.SimpleNamespace(id="device-abc")
    registry = types.SimpleNamespace(
        async_get_device_by_identifier=lambda identifier, config_entry_id: device,
    )
    return patch.object(coord_mod.dr, "async_get", return_value=registry)


async def _noop(*_args, **_kwargs):
    return None


def collect(append):
    """An event listener that appends each event.

    Must be a real @callback function. A plain lambda gets classified as an
    executor job, and the decorator cannot mark a builtin like list.append.
    """

    @callback
    def _on_event(event):
        append(event)

    return _on_event


# --------------------------------------------------------------------------
# Fakes
# --------------------------------------------------------------------------


def _all_features(report_time: float):
    """Every feature the entity tables reference, with a plausible reading.

    The platforms filter on the vehicle entity type, so a stub with an empty
    features dict silently produces zero entities - which looks like a pass if
    you only assert "no exception".
    """
    from toyota_na.vehicle.entity_types.ToyotaLocation import ToyotaLocation
    from toyota_na.vehicle.entity_types.ToyotaLockableOpening import (
        ToyotaLockableOpening,
    )
    from toyota_na.vehicle.entity_types.ToyotaNumeric import ToyotaNumeric
    from toyota_na.vehicle.entity_types.ToyotaRemoteStart import ToyotaRemoteStart

    from custom_components.toyota_na import const, device_tracker

    features = {}
    for row in const.BINARY_SENSORS:
        features[row["feature"]] = ToyotaLockableOpening(closed=True, locked=True)
    for row in const.SENSORS:
        features[row["feature"]] = ToyotaNumeric(42, "km")
    for row in device_tracker.features_sensors:
        features[row["feature"]] = ToyotaLocation(37.5, -122.3)
    features[VehicleFeatures.RemoteStartStatus] = ToyotaRemoteStart(None, False, 0)
    features[VehicleFeatures.LastTimeStamp] = ToyotaNumeric(report_time, "")
    return features


class FakeVehicle:
    def __init__(self, vin, subscribed=True, report_time=None):
        self.vin = vin
        self.subscribed = subscribed
        self.model_name = "Solterra"
        self.model_year = "2024"
        self.electric = True
        self.generation = ApiVehicleGeneration.MM24
        self.polled = 0
        self.features = _all_features(
            report_time if report_time is not None else time.time() - 7200
        )

    def report(self, when: float) -> None:
        """Change the report time in place, as a real poll's parse does."""
        from toyota_na.vehicle.entity_types.ToyotaNumeric import ToyotaNumeric

        self.features[VehicleFeatures.LastTimeStamp] = ToyotaNumeric(when, "")

    async def poll_vehicle_refresh(self):
        self.polled += 1

    async def send_command(self, command):
        pass


def fake_entry(entry_id="e1", data=None, options=None, disable_polling=False):
    entry = types.SimpleNamespace(
        entry_id=entry_id,
        data=data if data is not None else {},
        options=options if options is not None else {},
        title="Subaru",
        update_listeners=[],
        pref_disable_polling=disable_polling,
        state=ConfigEntryState.SETUP_IN_PROGRESS,
    )
    entry.unloads = []
    entry.async_on_unload = entry.unloads.append
    return entry


def stub_config_entries(hass):
    def update(entry, data=None, **_):
        if data is not None:
            entry.data = data
        return True

    hass.config_entries = types.SimpleNamespace(
        async_update_entry=update, async_forward_entry_setups=_noop
    )


def make_coordinator(hass, entry, vehicles):
    coordinator = ToyotaCoordinator(
        hass,
        LOG,
        config_entry=entry,
        name=DOMAIN,
        update_method=None,
        update_interval=None,
    )
    coordinator.data = vehicles
    coordinator.brand = get_brand("S")
    return coordinator


HASSES: list[HomeAssistant] = []


def new_hass() -> HomeAssistant:
    hass = HomeAssistant(tempfile.mkdtemp(dir=TMP))
    hass.config.skip_pip = True
    HASSES.append(hass)
    return hass


# --------------------------------------------------------------------------
# Sections
# --------------------------------------------------------------------------


async def s1_setup_and_services():
    hass = new_hass()
    check("async_setup returned True", await async_setup(hass, {}) is True)
    for service in ("refresh", "poll_vehicle", "engine_start", "send_command"):
        check(
            f"service {DOMAIN}.{service} registered",
            hass.services.has_service(DOMAIN, service),
        )
    check(
        "options flow is a real OptionsFlowWithReload",
        issubclass(config_flow.ToyotaNAOptionsFlow, OptionsFlowWithReload),
    )
    check(
        "async_get_options_flow is wired up",
        callable(config_flow.ToyotaNAConfigFlow.async_get_options_flow),
    )
    check(
        "logbook platform describes events",
        callable(getattr(toyota_logbook, "async_describe_events", None)),
    )


async def s2_interval_matrix():
    cases = [
        ({}, timedelta(minutes=10), timedelta(hours=2), "defaults match the old hardcoded values"),
        ({"fetch_interval": 5, "poll_interval": 24}, timedelta(minutes=5), timedelta(hours=24), "explicit"),
        ({"fetch_interval": 0, "poll_interval": 0}, None, None, "0 means never"),
        ({"fetch_interval": "x", "poll_interval": None}, timedelta(minutes=10), timedelta(hours=2), "junk falls back"),
    ]
    logging.getLogger("custom_components.toyota_na.polling").setLevel(logging.ERROR)
    for options, want_fetch, want_poll, label in cases:
        entry = types.SimpleNamespace(options=options)
        check(f"fetch {label}", fetch_interval(entry) == want_fetch, str(fetch_interval(entry)))
        check(f"poll  {label}", poll_interval(entry) == want_poll, str(poll_interval(entry)))


async def s3_platforms():
    hass = new_hass()
    vehicles = [
        FakeVehicle("JF2ZCACC1R8000001"),
        FakeVehicle("JF2ZCACC1R8000002", subscribed=False),
    ]
    entry = fake_entry()
    coordinator = make_coordinator(hass, entry, vehicles)
    hass.data[DOMAIN] = {"e1": {"coordinator": coordinator}}

    counts = {}
    for platform in PLATFORMS:
        module = __import__(f"custom_components.toyota_na.{platform}", fromlist=["x"])
        added = []
        await module.async_setup_entry(
            hass, entry, lambda entities, *a, **k: added.extend(entities)
        )
        counts[platform] = len(added)
    print("   " + ", ".join(f"{k}={v}" for k, v in counts.items()))
    check("every platform produced entities", all(counts.values()), str(counts))


async def s4_buttons():
    hass = new_hass()
    vehicles = [
        FakeVehicle("JF2ZCACC1R8000001"),
        FakeVehicle("JF2ZCACC1R8000002", subscribed=False),
    ]
    entry = fake_entry()
    coordinator = make_coordinator(hass, entry, vehicles)
    hass.data[DOMAIN] = {"e1": {"coordinator": coordinator}}
    from custom_components.toyota_na import button

    buttons = []
    await button.async_setup_entry(hass, entry, lambda e, *a, **k: buttons.extend(e))
    ids = [b.unique_id for b in buttons]
    names = {b.unique_id: b._attr_name for b in buttons}
    check("unique_ids are unique", len(ids) == len(set(ids)), str(len(ids)))
    check("refresh key preserved", "JF2ZCACC1R8000001-refresh" in ids)
    check(
        "poll_vehicle only on the subscribed vehicle",
        "JF2ZCACC1R8000001-poll_vehicle" in ids
        and "JF2ZCACC1R8000002-poll_vehicle" not in ids,
    )
    check("Refresh offered to the unsubscribed vehicle", "JF2ZCACC1R8000002-refresh" in ids)
    check(
        "names are Refresh / Poll vehicle",
        names["JF2ZCACC1R8000001-refresh"] == "Refresh"
        and names["JF2ZCACC1R8000001-poll_vehicle"] == "Poll vehicle",
    )

    print("   -- Refresh press --")
    refresh = next(b for b in buttons if b.unique_id == "JF2ZCACC1R8000001-refresh")
    requested = []

    async def record_refresh():
        requested.append(1)

    coordinator.async_request_refresh = record_refresh
    press = Context(user_id="user-1")
    refresh.async_set_context(press)
    await refresh.async_press()
    check("Refresh wakes no vehicle", sum(v.polled for v in vehicles) == 0)
    check("Refresh requests a cloud fetch", requested == [1])
    check(
        "Refresh holds the press as the pending cause",
        coordinator.pending_causes.get("JF2ZCACC1R8000001", (None,))[0] is press,
    )


async def s5_scheduled_poll_guard():
    hass = new_hass()
    stub_config_entries(hass)
    vehicles = [FakeVehicle("VIN0000000000001"), FakeVehicle("VIN0000000000002", subscribed=False)]
    entry = fake_entry(options={"poll_interval": 2})
    coordinator = make_coordinator(hass, entry, vehicles)
    coordinator.async_request_refresh = _noop
    hass.data[DOMAIN] = {"e1": {"coordinator": coordinator}}

    with fast_sleep(), fake_device_registry():
        await async_scheduled_poll(hass, entry)
        check("subscribed vehicle polled once", vehicles[0].polled == 1)
        check("unsubscribed vehicle skipped", vehicles[1].polled == 0)
        recorded = entry.data.get(POLLED_AT) or {}
        check("poll recorded per-VIN", vehicles[0].vin in recorded, str(recorded))
        check("unsubscribed vehicle not recorded", vehicles[1].vin not in recorded)
        await async_scheduled_poll(hass, entry)
        check("immediate second poll is skipped", vehicles[0].polled == 1)
        entry.data = {POLLED_AT: {v: t - 2 * 3600 for v, t in recorded.items()}}
        await async_scheduled_poll(hass, entry)
        check("poll happens once actually due", vehicles[0].polled == 2)

    never = fake_entry(options={"poll_interval": 0})
    vehicles[0].polled = 0
    await async_scheduled_poll(hass, never)
    check("poll interval 0 never polls", vehicles[0].polled == 0)


async def _run_setup(hass, options, disable_polling=False):
    tracked, actions = [], []
    entry = fake_entry(
        entry_id="e9",
        data={"brand": "S", "tokens": {}},
        options=options,
        disable_polling=disable_polling,
    )
    vehicles = [FakeVehicle("JF2ZCACC1R8000009")]
    stub_config_entries(hass)
    hass.data.setdefault(DOMAIN, {})

    def spy(_hass, action, interval, **_kw):
        tracked.append(interval)
        actions.append(action)
        return lambda: None

    async def fake_get_vehicles(_client):
        return vehicles

    with patch.object(pkg, "async_track_time_interval", spy), patch.object(
        pkg, "get_vehicles", fake_get_vehicles
    ), patch.object(pkg.OneAuth, "check_tokens", _noop), patch.object(
        pkg.ToyotaWebSocketHandler, "start", _noop
    ):
        ok = await async_setup_entry(hass, entry)
    return ok, tracked, actions, entry, vehicles


async def s6_setup_entry_wiring():
    hass = new_hass()
    fired = []
    for event_type in (EVENT_VEHICLE_POLLED, EVENT_VEHICLE_REPORT):
        hass.bus.async_listen(event_type, collect(fired.append))

    ok, tracked, _, entry_on, _ = await _run_setup(hass, {"poll_interval": 3})
    coordinator = hass.data[DOMAIN]["e9"]["coordinator"]
    await hass.async_block_till_done()
    check("async_setup_entry returned True", ok is True)
    check("coordinator is a ToyotaCoordinator", isinstance(coordinator, ToyotaCoordinator))
    check("poll timer at the configured interval", tracked == [timedelta(hours=3)], str(tracked))
    check("coordinator got the config entry", coordinator.config_entry is entry_on)
    check("fetch interval applied", coordinator.update_interval == timedelta(minutes=10))
    check("loading the integration fires no cause event", fired == [], str(fired))

    _, tracked_off, _, entry_off, _ = await _run_setup(hass, {"poll_interval": 0, "fetch_interval": 0})
    check("poll 0 schedules no timer", tracked_off == [])
    check(
        "fetch 0 leaves the coordinator unscheduled",
        hass.data[DOMAIN]["e9"]["coordinator"].update_interval is None,
    )
    check(
        "timer registered for cleanup on unload",
        len(entry_on.unloads) - len(entry_off.unloads) == 1,
        f"with={len(entry_on.unloads)} without={len(entry_off.unloads)}",
    )
    check("entry has no update listeners", entry_on.update_listeners == [])

    print("   -- the timer callable is one HA will actually await --")
    _, _, actions, _, vehicles = await _run_setup(hass, {"poll_interval": 3})
    action = actions[0]
    check(
        "poll callable is a coroutine function, not a lambda",
        get_hassjob_callable_job_type(action) is HassJobType.Coroutinefunction,
    )
    hass.data[DOMAIN]["e9"]["coordinator"].async_request_refresh = _noop
    with fast_sleep(), fake_device_registry():
        await action(None)
    check("invoking it polls the vehicle", vehicles[0].polled == 1, f"polled={vehicles[0].polled}")

    print("   -- setup states the schedule, and flags HA's polling override --")

    class Capture(logging.Handler):
        def __init__(self):
            super().__init__()
            self.records = []

        def emit(self, record):
            self.records.append((record.levelname, record.getMessage()))

    capture = Capture()
    package_log = logging.getLogger("custom_components.toyota_na")
    package_log.addHandler(capture)
    package_log.setLevel(logging.DEBUG)
    try:
        await _run_setup(hass, {"fetch_interval": 10, "poll_interval": 3})
        check(
            "logs the configured schedule",
            any("every 0:10:00" in m and "every 3:00:00" in m for _, m in capture.records),
        )
        capture.records.clear()
        await _run_setup(hass, {"fetch_interval": 0, "poll_interval": 0})
        check("says 'only on request' when both are off", any("only on request" in m for _, m in capture.records))
        capture.records.clear()
        await _run_setup(hass, {"fetch_interval": 10}, disable_polling=True)
        check(
            "warns when HA's own polling toggle is off",
            any(level == "WARNING" and "Enable polling for updates" in m for level, m in capture.records),
        )
    finally:
        package_log.removeHandler(capture)


async def s7_staleness_floor():
    hass = new_hass()
    stub_config_entries(hass)
    a, b = FakeVehicle("VINAAAAAAAAAAAAA"), FakeVehicle("VINBBBBBBBBBBBBB")
    entry = fake_entry(options={"poll_interval": 2})
    coordinator = make_coordinator(hass, entry, [a, b])
    coordinator.async_request_refresh = _noop
    hass.data[DOMAIN] = {"e1": {"coordinator": coordinator}}

    with fast_sleep(), fake_device_registry():
        await async_poll_now(hass, entry, coordinator, [a], context=Context())
        check("manual poll wakes A", a.polled == 1)
        check("manual poll defers A's schedule", not poll_due(entry, a.vin, timedelta(hours=2)))
        check("...but not B's", poll_due(entry, b.vin, timedelta(hours=2)))
        a.polled = b.polled = 0
        await async_scheduled_poll(hass, entry)
        check("scheduled poll skips the just-polled car", a.polled == 0)
        check("scheduled poll still wakes the stale one", b.polled == 1)

        c = FakeVehicle("VINCCCCCCCCCCCCC")

        async def unreachable():
            raise RuntimeError("telematics unreachable")

        c.poll_vehicle_refresh = unreachable
        logging.getLogger("custom_components.toyota_na.polling").setLevel(logging.ERROR)
        check("failed wake returns False", await async_poll_now(hass, entry, coordinator, [c]) is False)
        check("failed wake records nothing", poll_due(entry, c.vin, timedelta(hours=2)))
        check("failed wake registers no cause", c.vin not in coordinator.pending_causes)

    legacy = fake_entry(data={LEGACY_POLLED_AT: time.time()})
    check("legacy entry-wide timestamp still defers", not poll_due(legacy, a.vin, timedelta(hours=2)))
    stale = fake_entry(data={LEGACY_POLLED_AT: time.time() - 3 * 3600})
    check("legacy timestamp older than the interval is due", poll_due(stale, a.vin, timedelta(hours=2)))


async def s8_cause_routing():
    hass = new_hass()
    stub_config_entries(hass)
    base = time.time() - 7200
    a = FakeVehicle("VINAAAAAAAAAAAAA", report_time=base)
    b = FakeVehicle("VINBBBBBBBBBBBBB", report_time=base)
    entry = fake_entry()
    coordinator = make_coordinator(hass, entry, None)

    async def fetch():
        return [a, b]

    coordinator.update_method = fetch
    dispatches: list[dict] = []
    coordinator.async_add_listener(lambda: dispatches.append(dict(coordinator.update_contexts)))
    polled_events, report_events = [], []
    hass.bus.async_listen(EVENT_VEHICLE_POLLED, collect(polled_events.append))
    hass.bus.async_listen(EVENT_VEHICLE_REPORT, collect(report_events.append))

    async def refresh():
        await coordinator.async_refresh()
        await hass.async_block_till_done()
        return dispatches[-1]

    with fast_sleep(), fake_device_registry():
        contexts = await refresh()
        check("first refresh fires nothing", not polled_events and not report_events)
        check("first refresh applies no context", contexts == {})

        contexts = await refresh()
        check("unchanged report fires nothing", not report_events)
        check("unchanged report applies no context", contexts == {})

        print("   -- scheduled poll --")
        coordinator.async_request_refresh = _noop
        await async_poll_now(hass, entry, coordinator, [a], scheduled=True)
        await hass.async_block_till_done()
        check("scheduled poll fires one polled event", len(polled_events) == 1)
        event = polled_events[0]
        check("event data is the device id only", dict(event.data) == {"device_id": "device-abc"}, str(event.data))
        check("no VIN anywhere in the event data", a.vin not in repr(event.data))
        check(
            "the immediate dispatch carries the poll's context",
            dispatches[-1].get(a.vin) is event.context,
        )
        check("...for that vehicle only", b.vin not in dispatches[-1])
        check("update_contexts emptied after dispatch", coordinator.update_contexts == {})
        coordinator.async_set_updated_data([a, b])
        check("a second dispatch reapplies nothing", dispatches[-1] == {})

        contexts = await refresh()
        check("an early refresh with no new report leaves the cause pending", a.vin in coordinator.pending_causes)
        check("...and fires no report event", not report_events)

        a.report(time.time())
        contexts = await refresh()
        check("the refresh that brings the report credits the poll", contexts.get(a.vin) is event.context)
        check("...and consumes the pending cause", a.vin not in coordinator.pending_causes)
        check("...without a report event", not report_events)

        print("   -- button or service press --")
        press = Context(user_id="user-1")
        await async_poll_now(hass, entry, coordinator, [a], context=press)
        await hass.async_block_till_done()
        check("a press fires no polled event of our own", len(polled_events) == 1)
        check("the immediate dispatch carries the press", dispatches[-1].get(a.vin) is press)
        a.report(time.time() + 1)
        contexts = await refresh()
        check("the report is credited to the press, not the settle-expired entity", contexts.get(a.vin) is press)

        print("   -- the vehicle reports on its own --")
        b.report(time.time())
        contexts = await refresh()
        check("a report event fires for B", len(report_events) == 1)
        check("B's update carries that event's context", contexts.get(b.vin) is report_events[0].context)
        check("A is untouched", a.vin not in contexts)

        print("   -- windows and clocks --")
        stale = Context(user_id="user-2")
        coordinator.pending_causes[a.vin] = (stale, time.time() - CAUSE_TTL_SECONDS - 1)
        a.report(time.time() + 2)
        contexts = await refresh()
        check("a cause past its window is not credited", contexts.get(a.vin) is not stale)
        check("...a report event is used instead", contexts.get(a.vin) is report_events[-1].context)

        later = Context(user_id="user-3")
        coordinator.async_set_cause([a.vin], later)
        a.report(a.features[VehicleFeatures.LastTimeStamp].value + 1)  # still newer than last seen...
        a.report(time.time() - 3600)  # ...but made an hour before the cause was set
        coordinator._report_times[a.vin] = time.time() - 3601
        contexts = await refresh()
        check("a report older than the cause is not credited to it", contexts.get(a.vin) is not later)
        check("...and the cause keeps waiting for its own report", coordinator.pending_causes.get(a.vin, (None,))[0] is later)

    print("   -- the entity applies it at write time --")
    entity = ToyotaNABaseEntity(coordinator, "last_updated", "Last updated", a.vin)
    other = ToyotaNABaseEntity(coordinator, "last_updated", "Last updated", b.vin)
    seen = []
    entity.async_set_context = seen.append
    other.async_set_context = seen.append
    marker = Context()
    coordinator.update_contexts = {a.vin: marker}
    with patch.object(CoordinatorEntity, "_handle_coordinator_update", lambda self: None):
        entity._handle_coordinator_update()
        other._handle_coordinator_update()
    check("the matching vehicle's entity sets the context", seen == [marker], str(seen))


async def s9_logbook_end_to_end():
    """The contract Activity details actually reads: context_* on a logbook row."""
    from homeassistant.components.logbook import _process_logbook_platform
    from homeassistant.components.logbook.helpers import async_determine_event_types
    from homeassistant.components.logbook.models import LogbookConfig
    from homeassistant.components.logbook.processor import EventProcessor
    from homeassistant.helpers.recorder import get_instance
    from homeassistant.setup import async_setup_component

    hass = new_hass()
    # As bootstrap.py does. Without the frame helper, a deprecated Home Assistant
    # API called from the integration raises here instead of being reported the
    # way a real install reports it.
    from homeassistant.helpers import frame

    frame.async_setup(hass)
    loader.async_setup(hass)
    hass.config_entries = ConfigEntries(hass, {})
    await hass.config_entries.async_initialize()
    # The same bring-up bootstrap.py performs: the device registry is set up
    # first, then every registry loads, since they reference one another.
    from homeassistant.helpers import (
        area_registry,
        category_registry,
        floor_registry,
        issue_registry,
        label_registry,
    )

    dr.async_setup(hass)
    await asyncio.gather(
        area_registry.async_load(hass, load_empty=True),
        category_registry.async_load(hass, load_empty=True),
        dr.async_load(hass, load_empty=True),
        er.async_load(hass, load_empty=True),
        floor_registry.async_load(hass, load_empty=True),
        issue_registry.async_load(hass, load_empty=True),
        label_registry.async_load(hass, load_empty=True),
    )
    # bootstrap.py does this before any component is set up; the recorder reads
    # the data it creates while constructing itself.
    from homeassistant.helpers.recorder import async_initialize_recorder

    async_initialize_recorder(hass)
    database = Path(hass.config.config_dir) / "verify.db"
    check(
        "recorder set up on SQLite",
        await async_setup_component(
            hass, "recorder", {"recorder": {"db_url": f"sqlite:///{database}", "commit_interval": 0}}
        ),
    )
    await hass.async_start()
    recorder = get_instance(hass)
    await recorder.async_block_till_done()

    hass.data["logbook"] = LogbookConfig({})
    _process_logbook_platform(hass, DOMAIN, toyota_logbook)

    entity_id = "sensor.solterra_last_updated"
    vin = "JF2ZCACC1R8000001"
    start = dt_util.utcnow() - timedelta(minutes=5)

    # A deprecated Home Assistant API called from the integration is reported by
    # the frame helper as a warning naming it. The unit sections patch the device
    # registry out, so this is the only place such a call can surface.
    class FrameReports(logging.Handler):
        def __init__(self):
            super().__init__(logging.WARNING)
            self.messages = []

        def emit(self, record):
            self.messages.append(record.getMessage())

    reports = FrameReports()
    frame_log = logging.getLogger("homeassistant.helpers.frame")
    frame_log.addHandler(reports)
    try:
        hass.states.async_set(entity_id, "initial")
        hass.states.async_set(
            entity_id,
            "polled",
            context=async_fire_cause(hass, "entry-e2e", EVENT_VEHICLE_POLLED, vin),
        )
        hass.states.async_set(
            entity_id,
            "reported",
            context=async_fire_cause(hass, "entry-e2e", EVENT_VEHICLE_REPORT, vin),
        )
        # A press as Home Assistant actually delivers one: a service call, which
        # records a call_service event under the caller's context. User ids are
        # UUID hex; the recorder silently drops anything else.
        hass.services.async_register("button", "press", _noop)
        press = Context(user_id="1f2e3d4c5b6a79881f2e3d4c5b6a7988")
        await hass.services.async_call("button", "press", {}, blocking=True, context=press)
        hass.states.async_set(entity_id, "pressed", context=press)
        hass.states.async_set(entity_id, "uncaused")
        await hass.async_block_till_done()
        await recorder.async_block_till_done()
    finally:
        frame_log.removeHandler(reports)
    ours = [message for message in reports.messages if DOMAIN in message]
    check("no deprecated Home Assistant API reported against the integration", not ours, str(ours))

    processor = EventProcessor(
        hass, async_determine_event_types(hass, [entity_id], None), [entity_id], None, None, False, True
    )
    rows = await recorder.async_add_executor_job(
        processor.get_events, start, dt_util.utcnow() + timedelta(minutes=5)
    )
    by_state = {row.get("state"): row for row in rows if row.get("entity_id") == entity_id}

    polled = by_state.get("polled", {})
    check("scheduled poll row: context_name", polled.get("context_name") == "Scheduled vehicle poll", str(polled))
    check("scheduled poll row: context_domain", polled.get("context_domain") == DOMAIN)
    check("scheduled poll row: context_event_type", polled.get("context_event_type") == EVENT_VEHICLE_POLLED)
    reported = by_state.get("reported", {})
    check("vehicle report row: context_name", reported.get("context_name") == "New report from the vehicle", str(reported))
    check("vehicle report row: context_domain", reported.get("context_domain") == DOMAIN)
    # What Activity details reads to show "By <person> - Action used: Press".
    pressed = by_state.get("pressed", {})
    check(
        "press row: context_user_id is the person who pressed",
        pressed.get("context_user_id") == press.user_id,
        str(pressed),
    )
    check("press row: context_event_type is the service call", pressed.get("context_event_type") == "call_service")
    check(
        "press row: context_domain and context_service name the press",
        pressed.get("context_domain") == "button" and pressed.get("context_service") == "press",
    )
    uncaused = by_state.get("uncaused", {})
    check(
        "uncaused row carries no cause (the old behaviour)",
        "uncaused" in by_state and not uncaused.get("context_name") and not uncaused.get("context_user_id"),
        str(uncaused),
    )


SECTIONS = [
    ("1. async_setup, services, options flow", s1_setup_and_services),
    ("2. interval options matrix", s2_interval_matrix),
    ("3. every platform sets up", s3_platforms),
    ("4. buttons, and the Refresh press", s4_buttons),
    ("5. scheduled poll guard", s5_scheduled_poll_guard),
    ("6. async_setup_entry wiring, timer, logging", s6_setup_entry_wiring),
    ("7. poll interval as a staleness floor", s7_staleness_floor),
    ("8. cause routing for Activity details", s8_cause_routing),
    ("9. Activity details end to end, through the recorder and logbook", s9_logbook_end_to_end),
]


async def main() -> int:
    from homeassistant.const import __version__

    print(f"Home Assistant {__version__}, Python {sys.version.split()[0]}")
    for title, section in SECTIONS:
        print(f"\n== {title} ==")
        try:
            await section()
        except Exception:
            FAILED.append(f"{title} (crashed)")
            traceback.print_exc()
    for hass in HASSES:
        try:
            await hass.async_stop()
        except Exception:
            pass

    print()
    if FAILED:
        print(f"FAILED ({len(FAILED)}):")
        for label in FAILED:
            print(f"  - {label}")
        return 1
    print("all checks passed")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
