"""Smart TRV climate entity."""

from __future__ import annotations

from collections import deque
from datetime import datetime, timedelta
import logging
from typing import Any

from homeassistant.components.climate import (
    ATTR_CURRENT_TEMPERATURE,
    ATTR_HVAC_ACTION,
    ATTR_HVAC_MODES,
    ATTR_MAX_TEMP,
    ATTR_MIN_TEMP,
    ATTR_PRESET_MODE,
    ATTR_PRESET_MODES,
    ClimateEntity,
    ClimateEntityFeature,
    HVACAction,
    HVACMode,
)
from homeassistant.config_entries import ConfigEntry, ConfigEntryState
from homeassistant.const import (
    ATTR_ENTITY_ID,
    ATTR_TEMPERATURE,
    CONF_NAME,
    STATE_ON,
    STATE_UNAVAILABLE,
    STATE_UNKNOWN,
    UnitOfTemperature,
)
from homeassistant.core import (
    CALLBACK_TYPE,
    Event,
    EventStateChangedData,
    HomeAssistant,
    callback,
)
from homeassistant.helpers import entity_platform, entity_registry as er
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.dispatcher import async_dispatcher_connect, async_dispatcher_send
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.event import (
    async_call_later,
    async_track_state_change_event,
    async_track_time_interval,
)
from homeassistant.helpers.restore_state import RestoreEntity
from homeassistant.util import dt as dt_util

from .const import (
    ATTR_ERROR,
    ATTR_INTEGRAL,
    ATTR_TRV_SETPOINT,
    ATTR_WINDOW_OPEN,
    CONF_KI,
    CONF_KP,
    CONF_AUTO_TUNE,
    CONF_HEATS_ROOMS,
    CONF_OUTDOOR_GAIN,
    CONF_OUTDOOR_SENSOR,
    CONF_PREHEAT,
    CONF_PRESENCE,
    CONF_RETURN_TIME,
    CONF_SUMMER,
    CONF_SUN,
    CONF_NIGHT_ENTITY,
    CONF_ROOM_SENSOR,
    CONF_TRVS,
    CONF_WINDOW_CLOSE_DELAY,
    CONF_WINDOW_OPEN_DELAY,
    CONF_WINDOWS,
    DEFAULT_INTERVAL,
    DEFAULT_KI,
    DEFAULT_KP,
    DEFAULT_MAX_BOOST,
    BATTERY_LOW,
    DEFAULT_AUTO_TUNE,
    DEFAULT_MAX_CUT,
    DEFAULT_OUTDOOR_GAIN,
    DEFAULT_PREHEAT,
    DEFAULT_SUMMER,
    DEFAULT_SUN,
    DEFAULT_TRV_STEP,
    DEFAULT_WINDOW_CLOSE_DELAY,
    DEFAULT_WINDOW_OPEN_DELAY,
    DOMAIN,
    SIGNAL_SETTINGS,
    SIGNAL_UPDATE,
    STATUS_HEATING,
    STATUS_IDLE,
    STATUS_NO_SENSOR,
    STATUS_OFF,
    STATUS_WINDOW,
    TRV_MAX_TEMP,
    TRV_OFFLINE_MINUTES,
    TRV_STALE_HOURS,
    TRV_MIN_TEMP,
)
from .controller import PIController
from .learning import (
    MAX_PREHEAT_HOURS,
    SUN_LEAD_HOURS,
    AutoTuner,
    HeatRateLearner,
    PreheatTiming,
    SunProfile,
    preheat_hours,
)
from .diagnostics_text import explain, language, preheat_text, problem_text

_LOGGER = logging.getLogger(__name__)

# Re-send a setpoint the TRV hasn't confirmed after this long (Zigbee messages do get lost).
RESEND_AFTER = timedelta(minutes=10)
# Longest gap fed into the integral, so a long outage doesn't cause a jump.
MAX_DT_HOURS = 0.5

# A room warming this much within the window is a shower or cooking, not the radiator.
SPIKE_WINDOW = timedelta(minutes=15)
SPIKE_RISE = 0.6
SPIKE_PAUSE = timedelta(minutes=60)
HUMIDITY_RISE = 8.0  # %-points within SPIKE_WINDOW: someone is showering
# A wood stove or similar: after a spike the room stays warmer than the day target for hours.
# Nothing learned until it has cooled back says anything about the radiator.
HEAT_SOURCE_ABOVE = 0.5  # °C above the day target...
HEAT_SOURCE_RISE = 1.0  # ...and this much warmer than before the sudden heat...
HEAT_SOURCE_LASTS = timedelta(minutes=45)  # ...this long after it began: a shower has faded by then
HEAT_SOURCE_END = 0.2  # °C above the day target: the extra heat is gone...
HEAT_SOURCE_SETTLE = timedelta(minutes=30)  # ...once it has stayed there this long
HEAT_SOURCE_MAX = timedelta(hours=24)  # since the last sudden heat: never pause learning for good
# Away and holiday.
AWAY_DELAY = timedelta(minutes=30)  # a trip to the shop doesn't lower the heating
RETURN_GRACE = timedelta(hours=12)  # after the holiday return time, expect someone home
# Summer: heating off once it has been warm outside for a day, on again when it cools.
SUMMER_ON = 16.0  # °C, 24 h average outdoors...
SUMMER_HOLD = timedelta(hours=24)  # ...for this long
SUMMER_OFF = 14.0  # °C, 24 h average: the heating season is back
EXERCISE_EVERY = timedelta(days=7)  # open and close each valve so it doesn't seize
EXERCISE_FOR = timedelta(minutes=10)
EXERCISE_HOURS = (10, 16)  # local time, while someone may hear it rather than at night
# Sun: how sunny it is, from the weather entity's condition.
SUN_CONDITIONS = {"sunny": 1.0, "partlycloudy": 0.5}

ATTR_DAY_TEMPERATURE = "day_temperature"
ATTR_NIGHT_ACTIVE = "night_active"
ATTR_PREHEATING = "preheating"
ATTR_HEAT_RATE = "heat_rate"
ATTR_HEAT_RATE_SAMPLES = "heat_rate_samples"
ATTR_PREHEAT_LEAD = "preheat_lead_minutes"  # radiator warm-up before the room starts to warm
ATTR_PREHEAT_FACTOR = "preheat_factor"
ATTR_PREHEAT_LEARNING = "preheat_learning"
ATTR_LAST_PREHEAT = "last_preheat"
ATTR_HEAT_SOURCE = "heat_source"
ATTR_HEAT_FROM_ROOM = "heat_from_room"
PREHEAT_REACHED = 0.1  # °C below the target counts as warm
ATTR_KP = "kp"
ATTR_KI = "ki"
ATTR_TUNED_FROM = "tuned_from"  # the configured Kp/Ki the tuned values started from
ATTR_LAST_TUNING = "last_tuning"
ATTR_OUTDOOR_FF = "outdoor_ff"
ATTR_AWAY = "away"
ATTR_SUMMER = "summer"
ATTR_OUTDOOR_AVG = "outdoor_24h"
ATTR_WARM_SINCE = "warm_since"
ATTR_LAST_EXERCISE = "last_valve_exercise"
ATTR_SUN_PROFILE = "sun_profile"
ATTR_SUN_REDUCTION = "sun_reduction"
ATTR_HEATING_TODAY = "heating_hours_today"
ATTR_HEATING_TOTAL = "heating_hours_total"
ATTR_HEATING_DAY = "heating_day"


def _parse_time(value: Any) -> datetime | None:
    if isinstance(value, str):
        value = dt_util.parse_datetime(value)
    return value if isinstance(value, datetime) else None


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    async_add_entities([SmartTRVClimate(entry)])
    platform = entity_platform.async_get_current_platform()
    platform.async_register_entity_service("reset_integral", None, "async_reset_integral")


# Home Assistant 2026.11+ names climate temperatures native_*; earlier versions don't.
_NATIVE_CLIMATE = hasattr(ClimateEntity, "native_current_temperature")


class SmartTRVClimate(ClimateEntity, RestoreEntity):
    _attr_has_entity_name = True
    _attr_name = None
    _attr_hvac_modes = [HVACMode.HEAT, HVACMode.OFF]
    _attr_supported_features = (
        ClimateEntityFeature.TARGET_TEMPERATURE
        | ClimateEntityFeature.TURN_ON
        | ClimateEntityFeature.TURN_OFF
    )
    _attr_target_temperature_step = 0.1
    _attr_min_temp = TRV_MIN_TEMP
    _attr_max_temp = TRV_MAX_TEMP

    def __init__(self, entry: ConfigEntry) -> None:
        conf = {**entry.data, **entry.options}
        self._entry = entry
        self._room_sensor: str = conf[CONF_ROOM_SENSOR]
        self._trvs: list[str] = list(conf[CONF_TRVS])
        self._windows: list[str] = list(conf.get(CONF_WINDOWS, []))
        self._night_entity: str | None = conf.get(CONF_NIGHT_ENTITY)
        self._open_delay = float(conf.get(CONF_WINDOW_OPEN_DELAY, DEFAULT_WINDOW_OPEN_DELAY))
        self._close_delay = float(conf.get(CONF_WINDOW_CLOSE_DELAY, DEFAULT_WINDOW_CLOSE_DELAY))
        # Heating goes off for an open window only after the open delay, back on after the close delay.
        self._window_off = False
        self._window_timer: CALLBACK_TYPE | None = None
        self._window_pending: str | None = None  # "off" or "on" while a delay runs
        self._window_deadline: datetime | None = None
        # Fixed, tested values: these are not settings any more (an old stored max_boost of 2
        # kept a lukewarm room under target). The TRV step is read from the TRVs themselves.
        self._interval = timedelta(minutes=DEFAULT_INTERVAL)
        self._pi = PIController(
            kp=conf.get(CONF_KP, DEFAULT_KP),
            ki=conf.get(CONF_KI, DEFAULT_KI),
            max_boost=DEFAULT_MAX_BOOST,
            max_cut=DEFAULT_MAX_CUT,
            step=DEFAULT_TRV_STEP,
            hysteresis=DEFAULT_TRV_STEP,
            min_temp=TRV_MIN_TEMP,
            max_temp=TRV_MAX_TEMP,
        )
        self._attr_unique_id = entry.entry_id
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)}, name=conf[CONF_NAME], model="PI controller"
        )
        self._attr_hvac_mode = HVACMode.HEAT
        self._day_target = 21.0
        self._room_temp: float | None = None
        self._seeded = False
        self._last_run: datetime | None = None
        self._trv_setpoint: float | None = None
        self._last_sent: dict[str, tuple[float, datetime]] = {}
        self._trvs_off = False
        self._full_open_since: datetime | None = None
        self._full_open_trv_start: float | None = None
        # The mirror image: told to close, but the radiator stays hot (valve doesn't shut).
        self._closed_since: datetime | None = None
        self._closed_trv_start: float | None = None
        # Sudden heat (shower, cooking): recent room readings, and when learning resumes.
        self._room_history: deque[tuple[datetime, float]] = deque()
        self._humidity_history: deque[tuple[datetime, float]] = deque()
        self._humidity_sensor: str | None = None  # found on the room sensor's device
        self._spike_until: datetime | None = None
        self._humidity_until: datetime | None = None  # a shower, not a stove
        self._spike_start: tuple[datetime, float] | None = None  # when it began, room before it
        self._heat_source_seen: datetime | None = None  # last sudden heat from a heat source
        self._heat_source_gone: datetime | None = None  # back near the target since
        self._room_heat_seen: datetime | None = None  # another room's stove last burned
        self._room_heat_gone: datetime | None = None  # it's out, and we're back near the target
        # TRVs still reporting another setpoint than we sent, after a resend: trv -> (sent, reported)
        self._rejected: dict[str, tuple[float, float]] = {}

        # Outdoor compensation: a feedforward that rises before the room has cooled.
        self._outdoor_sensor: str | None = conf.get(CONF_OUTDOOR_SENSOR)
        self._outdoor_gain = float(conf.get(CONF_OUTDOOR_GAIN, DEFAULT_OUTDOOR_GAIN))
        self._ff = 0.0
        self._restored_ff: float | None = None
        self._ff_migrated = True  # set False when a restored integral was learned without it

        # Preheat: end the night early enough that the room is warm when it ends.
        self._preheat_enabled = bool(conf.get(CONF_PREHEAT, DEFAULT_PREHEAT))
        self._heat_rate = HeatRateLearner()
        self._preheat_for: datetime | None = None  # the night end we are preheating for
        self._preheat_timing = PreheatTiming()
        # The running preheat: when it started, whether it was capped, when the room got warm,
        # and whether a window or a shower spoiled it as a lesson.
        self._preheat_run: dict[str, Any] | None = None
        self._last_preheat: str | None = None

        # Away and holiday: nobody home lowers the room; a known return time is preheated for.
        self._presence: str | None = conf.get(CONF_PRESENCE)
        self._return_entity: str | None = conf.get(CONF_RETURN_TIME)
        # Summer: off while it's warm outside, with a weekly valve exercise. Needs outdoors.
        self._summer_enabled = bool(conf.get(CONF_SUMMER, DEFAULT_SUMMER)) and bool(self._outdoor_sensor)
        self._summer = False
        self._outdoor_avg: float | None = None  # 24 h average
        self._summer_clock: datetime | None = None
        self._warm_since: datetime | None = None
        self._last_exercise: datetime | None = None
        self._exercise_until: datetime | None = None
        # Sun: learned per hour of the day, used when the weather says it's sunny.
        self._sun_enabled = bool(conf.get(CONF_SUN, DEFAULT_SUN))
        self._sun = SunProfile()
        self._sun_ff = 0.0
        # What each control step did about the sun: (time, how sunny, TRV already shut).
        self._sun_history: deque[tuple[datetime, float, bool]] = deque()
        # Heating time, to compare rooms and days.
        self._heating_today = 0.0
        self._heating_total = 0.0
        self._heating_day: str | None = None
        self._heating_clock: datetime | None = None
        self._was_heating = False

        # Auto-tuning starts from the configured Kp/Ki and nudges them once a day.
        self._opt_gains = [self._pi.kp, self._pi.ki]
        self._tuner = (
            AutoTuner(kp=self._pi.kp, ki=self._pi.ki)
            if conf.get(CONF_AUTO_TUNE, DEFAULT_AUTO_TUNE)
            else None
        )
        self._last_target: float | None = None

        # TRV health: battery sensors found through the device registry; trv -> problem text.
        self._battery_entities: dict[str, str] = {}
        self._position_entities: dict[str, str] = {}  # valve opening in %, e.g. TRV602
        self._calibration_entities: dict[str, str] = {}  # Z2M local_temperature_calibration
        self._problems: dict[str, str] = {}
        self._started = dt_util.utcnow()

    # ----------------------------------------------------------------- lifecycle

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()

        if (last := await self.async_get_last_state()) is not None:
            if last.state in (HVACMode.HEAT, HVACMode.OFF):
                self._attr_hvac_mode = HVACMode(last.state)
            # Older versions only stored the (then always day) target as "temperature".
            day = last.attributes.get(ATTR_DAY_TEMPERATURE, last.attributes.get(ATTR_TEMPERATURE))
            if day is not None:
                self._day_target = float(day)
            if (integral := last.attributes.get(ATTR_INTEGRAL)) is not None:
                self._pi.integral = float(integral)
                self._seeded = True
                # Learned before outdoor compensation existed: take the feedforward out once.
                self._restored_ff = last.attributes.get(ATTR_OUTDOOR_FF)
                self._ff_migrated = self._restored_ff is not None
            if (rate := last.attributes.get(ATTR_HEAT_RATE)) is not None:
                self._heat_rate.rate = float(rate)
                self._heat_rate.samples = int(last.attributes.get(ATTR_HEAT_RATE_SAMPLES) or 1)
            if isinstance(model := last.attributes.get(ATTR_PREHEAT_LEARNING), dict):
                self._heat_rate.load(model)
            if (factor := last.attributes.get(ATTR_PREHEAT_FACTOR)) is not None:
                self._preheat_timing.factor = float(factor)
            self._last_preheat = last.attributes.get(ATTR_LAST_PREHEAT)
            if last.attributes.get(ATTR_HEAT_SOURCE):
                self._heat_source_seen = dt_util.utcnow()  # a restart doesn't put the stove out
            if last.attributes.get(ATTR_HEAT_FROM_ROOM):
                self._room_heat_seen = dt_util.utcnow()
            attrs = last.attributes
            self._summer = bool(attrs.get(ATTR_SUMMER))
            if isinstance(attrs.get(ATTR_OUTDOOR_AVG), (int, float)):
                self._outdoor_avg = float(attrs[ATTR_OUTDOOR_AVG])
            self._warm_since = _parse_time(attrs.get(ATTR_WARM_SINCE))
            self._last_exercise = _parse_time(attrs.get(ATTR_LAST_EXERCISE))
            self._sun.load(attrs.get(ATTR_SUN_PROFILE))
            self._heating_total = float(attrs.get(ATTR_HEATING_TOTAL) or 0.0)
            self._heating_today = float(attrs.get(ATTR_HEATING_TODAY) or 0.0)
            self._heating_day = attrs.get(ATTR_HEATING_DAY)
            # Keep tuned gains only while the configured ones are unchanged.
            if (
                self._tuner is not None
                and last.attributes.get(ATTR_TUNED_FROM) == self._opt_gains
                and last.attributes.get(ATTR_KP) is not None
            ):
                self._tuner.kp = self._pi.kp = float(last.attributes[ATTR_KP])
                self._tuner.ki = self._pi.ki = float(last.attributes[ATTR_KI])
                self._tuner.last_change = last.attributes.get(ATTR_LAST_TUNING)

        self._find_battery_entities()
        self._find_humidity_sensor()
        self._detect_trv_step()
        self._room_temp = self._read_float(self._room_sensor)
        self._window_off = self._any_window_open()  # already open at startup: no delay
        self.async_on_remove(self._cancel_window_timer)

        self.async_on_remove(
            async_track_state_change_event(
                self.hass,
                [
                    self._room_sensor,
                    *self._windows,
                    *filter(
                        None,
                        [self._night_entity, self._humidity_sensor, self._presence, self._return_entity],
                    ),
                ],
                self._async_input_changed,
            )
        )
        self.async_on_remove(
            async_dispatcher_connect(
                self.hass, SIGNAL_SETTINGS.format(self._entry.entry_id), self._async_settings_changed
            )
        )
        self.async_on_remove(
            async_track_state_change_event(
                self.hass,
                # battery drops and valve moves show at once
                [*self._trvs, *self._battery_entities.values(), *self._position_entities.values()],
                self._async_trv_changed,
            )
        )
        self.async_on_remove(
            async_track_time_interval(self.hass, self._async_tick, self._interval)
        )
        self.hass.async_create_task(self._async_control())

    # ------------------------------------------------------------------ handlers

    @callback
    def _async_input_changed(self, event: Event[EventStateChangedData]) -> None:
        if event.data["entity_id"] == self._room_sensor:
            # Only show the new reading; the controller runs on the timer. Running it on every
            # sensor update made the TRV motor move every few minutes.
            self._room_temp = self._read_float(self._room_sensor)
            self._check_spike(dt_util.utcnow(), self._room_temp)
            self._publish()
            return
        if event.data["entity_id"] == self._humidity_sensor:
            self._check_humidity(dt_util.utcnow(), self._read_float(self._humidity_sensor))
            return
        if event.data["entity_id"] in self._windows:
            self._async_window_changed()
            return
        self.hass.async_create_task(self._async_control())  # night, presence or return: act now

    @callback
    def _async_window_changed(self) -> None:
        open_now = self._any_window_open()
        self._cancel_window_timer()
        if open_now == self._window_off:
            self._publish()  # e.g. the door closed again before the open delay ran out
            return
        delay = self._open_delay if open_now else self._close_delay
        if delay <= 0:
            self._apply_window(open_now)
            return
        self._window_pending = "off" if open_now else "on"
        self._window_deadline = dt_util.utcnow() + timedelta(seconds=delay)
        self._window_timer = async_call_later(self.hass, delay, self._async_window_timer_done)
        self._publish()

    @callback
    def _async_window_timer_done(self, _now: datetime) -> None:
        self._window_timer = None
        self._apply_window(self._any_window_open())

    @callback
    def _apply_window(self, open_: bool) -> None:
        self._window_pending = None
        self._window_deadline = None
        self._window_off = open_
        self.hass.async_create_task(self._async_control())

    @callback
    def _cancel_window_timer(self) -> None:
        if self._window_timer is not None:
            self._window_timer()
            self._window_timer = None
        self._window_pending = None
        self._window_deadline = None

    @callback
    def _async_settings_changed(self) -> None:
        self.hass.async_create_task(self._async_control())

    @callback
    def _async_trv_changed(self, event: Event[EventStateChangedData]) -> None:
        # Only refresh hvac_action and diagnostics; control runs on room sensor and timer.
        self._publish()

    async def _async_tick(self, _now: datetime) -> None:
        await self._async_control()

    # ------------------------------------------------------------------- control

    async def _async_control(self) -> None:
        now = dt_util.utcnow()
        room = self._room_temp

        self._count_heating(now)
        self._update_summer(now)
        if self._exercise_due(now):
            await self._async_exercise(now)
            self._publish()
            return
        if self._attr_hvac_mode == HVACMode.OFF or self._window_open or self._summer:
            self._last_run = now  # freeze the integral while not heating
            self._full_open_since = None
            self._closed_since = None
            if self._preheat_run is not None:
                self._preheat_run["disturbed"] = True
            await self._async_turn_trvs_off()
            self._publish()
            return

        self._update_preheat(now)
        # Keep a recent baseline even when the sensors are quiet, so a jump is measured from it.
        self._check_spike(now, room)
        if self._humidity_sensor:
            self._check_humidity(now, self._read_float(self._humidity_sensor))
        target = self._goal()
        if room is None:
            self._publish()  # TRVs keep their last setpoint
            return

        if not self._seeded:
            self._pi.seed(self._first_trv_temperature(), room)
            self._seeded = True

        dt_hours = 0.0
        if self._last_run is not None:
            dt_hours = min((now - self._last_run).total_seconds() / 3600, MAX_DT_HOURS)
        self._last_run = now

        self._detect_trv_step()  # TRVs may come up after us (MQTT discovery)
        self._ff = self._outdoor_feedforward(target)
        if not self._ff_migrated and self._outdoor_sensor:
            self._pi.integral -= self._ff  # it already contained this load; avoid a jump
            self._ff_migrated = True

        sun = self._sunshine() if self._lowered is None and self._preheat_for is None else 0.0
        self._sun_ff = self._sun.reduction(self._local_hour(now), sun)
        self._trv_setpoint = self._pi.update(
            target, room, dt_hours, self._average_trv_temperature(), self._ff - self._sun_ff,
            self._valve_position(),
            # Overshoot in the sun is for the sun profile to learn, not the radiator offset.
            learn=not self._learning_paused(now) and not (sun > 0 and room > target),
        )
        self._learn(now, room, target, dt_hours)
        self._sun_history.append((now, sun, self._pi.valve_saturated and self._pi.error < 0))
        while now - self._sun_history[0][0] > timedelta(hours=SUN_LEAD_HOURS + 0.5):
            self._sun_history.popleft()
        # Track how long the TRV has been asked for full heat, and what it read then: a radiator
        # that warms makes the TRV's reading rise, wherever it sits (even in cold air by a window).
        if self._pi.valve_saturated and self._pi.error > 0:
            if self._full_open_since is None:
                self._full_open_since = now
                self._full_open_trv_start = self._average_trv_temperature()
        else:
            self._full_open_since = None
        if self._pi.valve_saturated and self._pi.error < 0:
            if self._closed_since is None:
                self._closed_since = now
                self._closed_trv_start = self._average_trv_temperature()
        else:
            self._closed_since = None
        _LOGGER.debug(
            "%s: room=%.2f target=%.2f error=%.2f integral=%.2f -> TRV %.1f",
            self.entity_id, room, target,
            self._pi.error, self._pi.integral, self._trv_setpoint,
        )
        await self._async_push_to_trvs(self._trv_setpoint, now)
        self._publish()

    async def _async_push_to_trvs(self, setpoint: float, now: datetime) -> None:
        self._trvs_off = False
        for trv in self._trvs:
            state = self.hass.states.get(trv)
            if state is None or state.state in (STATE_UNAVAILABLE, STATE_UNKNOWN):
                continue

            # Only wake a TRV that is off. Others may report "auto" while heating to our setpoint
            # (TRV602 does in preset manual); forcing "heat" on them every run just flips the
            # state back and forth and spends battery on a Zigbee command each time.
            modes = state.attributes.get(ATTR_HVAC_MODES) or [HVACMode.HEAT, HVACMode.OFF]
            if state.state == HVACMode.OFF and HVACMode.HEAT in modes:
                await self._call("set_hvac_mode", trv, hvac_mode=HVACMode.HEAT)

            # "auto" follows the TRV's own schedule and overrides us; "manual" also leaves
            # a preset "off" used while a window was open.
            presets = state.attributes.get(ATTR_PRESET_MODES) or []
            if "manual" in presets and state.attributes.get(ATTR_PRESET_MODE) != "manual":
                await self._call("set_preset_mode", trv, preset_mode="manual")

            reported = state.attributes.get(ATTR_TEMPERATURE)
            if reported is not None and abs(float(reported) - setpoint) < 0.05:
                self._rejected.pop(trv, None)
                continue
            last = self._last_sent.get(trv)
            if last is not None and last[0] == setpoint and now - last[1] < RESEND_AFTER:
                continue  # sent already, waiting for the TRV to report back
            if last is not None and last[0] == setpoint and reported is not None:
                # Sent a while ago and the TRV still shows a lower setpoint: it is refusing it,
                # e.g. a TRV602 whose max_temperature is below what we ask for. A TRV that
                # stays a bit higher (slow to report a decrease) does no harm: no warning.
                if float(reported) <= setpoint - 0.25:
                    self._rejected[trv] = (setpoint, float(reported))
                else:
                    self._rejected.pop(trv, None)
            await self._call("set_temperature", trv, temperature=setpoint)
            self._last_sent[trv] = (setpoint, now)

    async def _async_turn_trvs_off(self) -> None:
        if self._trvs_off:
            return
        for trv in self._trvs:
            state = self.hass.states.get(trv)
            if state is None or state.state in (HVACMode.OFF, STATE_UNAVAILABLE, STATE_UNKNOWN):
                continue
            # Use whatever "off" the TRV has: preset (TRV602, which also lists hvac modes it
            # can't really set), hvac mode (TV02), or its lowest setpoint.
            modes = state.attributes.get(ATTR_HVAC_MODES) or [HVACMode.HEAT, HVACMode.OFF]
            presets = state.attributes.get(ATTR_PRESET_MODES) or []
            if "off" in presets:
                if state.attributes.get(ATTR_PRESET_MODE) != "off":
                    await self._call("set_preset_mode", trv, preset_mode="off")
            elif HVACMode.OFF in modes:
                await self._call("set_hvac_mode", trv, hvac_mode=HVACMode.OFF)
            else:
                low = state.attributes.get(ATTR_MIN_TEMP, TRV_MIN_TEMP)
                await self._call("set_temperature", trv, temperature=low)
        self._last_sent.clear()
        self._rejected.clear()
        self._pi.output = None  # start from a fresh setpoint when heating resumes
        self._trvs_off = True

    async def _call(self, service: str, entity_id: str, **data: Any) -> None:
        try:
            await self.hass.services.async_call(
                "climate", service, {ATTR_ENTITY_ID: entity_id, **data}, blocking=True
            )
        except Exception as err:  # noqa: BLE001 - one flaky TRV must not stop the others
            _LOGGER.warning("%s: %s on %s failed: %s", self.entity_id, service, entity_id, err)

    @callback
    def _publish(self) -> None:
        """Write our state and hand the latest numbers to the diagnostic sensors."""
        self._problems = self._check_trvs()
        self.async_write_ha_state()
        self._entry.runtime_data.diag = self._diagnostics()
        async_dispatcher_send(self.hass, SIGNAL_UPDATE.format(self._entry.entry_id))

    def _diagnostics(self) -> dict[str, Any]:
        trv_temp = self._average_trv_temperature()
        if self._attr_hvac_mode == HVACMode.OFF or (self._summer and self._exercise_until is None):
            status = STATUS_OFF
        elif self._window_open:
            status = STATUS_WINDOW
        elif self._room_temp is None:
            status = STATUS_NO_SENSOR
        elif self.hvac_action == HVACAction.HEATING:
            status = STATUS_HEATING
        else:
            status = STATUS_IDLE
        diag = {
            "status": status,
            "trv_setpoint": self._trv_setpoint,
            "trv_temperature": trv_temp,
            "trv_temperatures": self._trv_temperatures(),
            "valve_position": self._valve_position(),
            "calibrations": {
                trv: value
                for trv, entity in self._calibration_entities.items()
                if (value := self._read_float(entity)) is not None
            },
            "calibration_known": bool(self._calibration_entities),
            "full_open_trv_rise": (
                round(trv_temp - self._full_open_trv_start, 1)
                if self._full_open_since and trv_temp is not None
                and self._full_open_trv_start is not None
                else None
            ),
            "rejected": dict(self._rejected),
            "window_pending": self._window_pending,
            "window_seconds_left": (
                max(0, round((self._window_deadline - dt_util.utcnow()).total_seconds()))
                if self._window_deadline
                else None
            ),
            "error": round(self._pi.error, 2),
            "p_term": round(self._pi.kp * self._pi.error, 2),
            "integral": round(self._pi.integral, 2),
            "heat_source": self._heat_source_seen is not None,
            "heat_from_room": self._room_heat_seen is not None,
            # What preheat has learned (diagnostic sensors).
            "preheat_lead": round(self._heat_rate.dead_time * 60),
            "heat_rate": round(self._preheat_rate(), 2),
            "preheat_factor": round(self._preheat_timing.factor, 2),
            "last_preheat": self._last_preheat,
            "night_active": self._night_active,
            "preheat_until": self._fmt_time(self._preheat_for) if self._preheat_for else None,
            "preheat_home": self._preheat_for is not None and self._lowered == "holiday",
            "away": self._away_active,
            "holiday_until": (
                self._fmt_time(self._return_time())
                if self._away_active and self._lowered == "holiday"
                else None
            ),
            "summer": self._summer,
            "exercising": self._exercise_until is not None,
            "sun_reduction": self._sun_ff,
            "heating_today": round(self._heating_today, 2),
            "heating_total": round(self._heating_total, 2),
            "day_target": self._day_target,
            "outdoor_ff": self._ff,
            "problems": self._problems,
            "learning_paused_until": (
                dt_util.as_local(self._spike_until).strftime("%H:%M")
                if self._spike_until is not None and self._learning_paused(dt_util.utcnow())
                else None
            ),
            "closed_hours": (
                round((dt_util.utcnow() - self._closed_since).total_seconds() / 3600, 1)
                if self._closed_since
                else 0.0
            ),
            "closed_trv_drop": (
                round(self._closed_trv_start - trv_temp, 1)
                if self._closed_since and trv_temp is not None
                and self._closed_trv_start is not None
                else None
            ),
            "full_open_hours": (
                round((dt_util.utcnow() - self._full_open_since).total_seconds() / 3600, 1)
                if self._full_open_since
                else 0.0
            ),
        }
        diag["explanation"] = explain(diag, self._room_temp, self._goal(), self._lang)
        return diag

    # ------------------------------------------------------------------- helpers

    @property
    def _night_scheduled(self) -> bool:
        return (
            self._night_entity is not None
            and (s := self.hass.states.get(self._night_entity)) is not None
            and s.state == STATE_ON
        )

    @property
    def _night_active(self) -> bool:
        """Night temperature in use: night scheduled and not preheating for the morning."""
        return self._lowered == "night" and self._preheat_for is None

    @property
    def _away_active(self) -> bool:
        """Away temperature in use: nobody home, and not preheating for the return."""
        return self._lowered in ("away", "holiday") and self._preheat_for is None

    @property
    def _lowered(self) -> str | None:
        """Why the room is lowered, ignoring preheat: "holiday", "away", "night" or None."""
        if (away := self._away_state(dt_util.utcnow())) is not None:
            return away
        return "night" if self._night_scheduled else None

    def _comfort_at(self) -> datetime | None:
        """When the lowered period ends, if known: what preheat aims for."""
        lowered = self._lowered
        if lowered == "holiday":
            return self._return_time()
        if lowered == "night":
            return self._night_end()
        return None

    def _someone_home(self) -> bool:
        if self._presence is None or (s := self.hass.states.get(self._presence)) is None:
            return True
        if s.state in (STATE_UNAVAILABLE, STATE_UNKNOWN):
            return True  # don't let the house go cold on a sensor hiccup
        if self._presence.startswith("zone."):
            try:
                return float(s.state) > 0  # zone.home counts the people at home
            except ValueError:
                return True
        return s.state in ("home", STATE_ON)

    def _return_time(self) -> datetime | None:
        """Back home from a holiday, from an input_datetime (local time)."""
        if self._return_entity is None or (s := self.hass.states.get(self._return_entity)) is None:
            return None
        when = dt_util.parse_datetime(s.state)
        if when is None:
            return None
        if when.tzinfo is None:
            when = when.replace(tzinfo=dt_util.get_default_time_zone())
        return dt_util.as_utc(when)

    def _away_state(self, now: datetime) -> str | None:
        """"holiday" (away, return time ahead), "away", or None while someone is home."""
        if self._presence is None or self._someone_home():
            return None
        state = self.hass.states.get(self._presence)
        if state is None or now - state.last_changed < AWAY_DELAY:
            return None
        back = self._return_time()
        if back is not None and now >= back:
            if now - back < RETURN_GRACE:
                return None  # expected home any moment: keep it warm
            back = None  # an old return time
        return "holiday" if back is not None else "away"

    def _fmt_time(self, when: datetime | None) -> str | None:
        if when is None:
            return None
        local = dt_util.as_local(when)
        if local.date() == dt_util.as_local(dt_util.utcnow()).date():
            return local.strftime("%H:%M")
        return local.strftime("%d/%m %H:%M")

    @staticmethod
    def _local_hour(now: datetime) -> float:
        local = dt_util.as_local(now)
        return local.hour + local.minute / 60

    def _sunshine(self) -> float:
        """0-1 from the weather now (sunny 1, partly cloudy 0.5), only with the sun up."""
        if not self._sun_enabled:
            return 0.0
        if (sun := self.hass.states.get("sun.sun")) is not None and sun.state != "above_horizon":
            return 0.0
        weather = sorted(self.hass.states.async_all("weather"), key=lambda s: s.entity_id)
        return SUN_CONDITIONS.get(weather[0].state, 0.0) if weather else 0.0

    def _update_summer(self, now: datetime) -> None:
        """Summer once the 24 h outdoor average has stayed over 16 °C for a day; off under 14 °C."""
        if not self._summer_enabled:
            self._summer = False
            return
        if (outdoor := self._outdoor()) is None:
            return
        if self._outdoor_avg is None:
            self._outdoor_avg = outdoor
        elif self._summer_clock is not None:
            hours = min((now - self._summer_clock).total_seconds() / 3600, 1.0)
            self._outdoor_avg += (outdoor - self._outdoor_avg) * hours / 24
        self._summer_clock = now
        if self._outdoor_avg >= SUMMER_ON:
            self._warm_since = self._warm_since or now
            if not self._summer and now - self._warm_since >= SUMMER_HOLD:
                self._summer = True
                _LOGGER.info("%s: summer, heating off", self.entity_id)
        else:
            self._warm_since = None
        if self._summer and self._outdoor_avg < SUMMER_OFF:
            self._summer = False
            _LOGGER.info("%s: heating season again", self.entity_id)

    def _exercise_due(self, now: datetime) -> bool:
        """Weekly in summer: open each valve for a few minutes so it doesn't seize."""
        if self._exercise_until is not None:
            if now < self._exercise_until:
                return True
            self._exercise_until = None
            self._trvs_off = False  # close them again
            return False
        if (
            not self._summer
            or self._window_open
            or self._attr_hvac_mode == HVACMode.OFF
            or not EXERCISE_HOURS[0] <= dt_util.as_local(now).hour < EXERCISE_HOURS[1]
            or (self._last_exercise is not None and now - self._last_exercise < EXERCISE_EVERY)
        ):
            return False
        self._last_exercise = now
        self._exercise_until = now + EXERCISE_FOR
        _LOGGER.info("%s: exercising the valves", self.entity_id)
        return True

    async def _async_exercise(self, now: datetime) -> None:
        highest = [
            float(m)
            for trv in self._trvs
            if (s := self.hass.states.get(trv)) is not None
            and (m := s.attributes.get(ATTR_MAX_TEMP)) is not None
        ]
        await self._async_push_to_trvs(min([TRV_MAX_TEMP, *highest]), now)

    def _count_heating(self, now: datetime) -> None:
        """Add up the time the room heats, today (reset at midnight) and in total."""
        today = dt_util.as_local(now).date().isoformat()
        if self._heating_day != today:
            self._heating_day, self._heating_today = today, 0.0
        if self._was_heating and self._heating_clock is not None:
            hours = min((now - self._heating_clock).total_seconds() / 3600, MAX_DT_HOURS)
            self._heating_today += hours
            self._heating_total += hours
        self._heating_clock = now
        self._was_heating = self.hvac_action == HVACAction.HEATING

    def _night_end(self) -> datetime | None:
        """When the night ends, if the night entity says (a schedule has next_event)."""
        if self._night_entity is None or (s := self.hass.states.get(self._night_entity)) is None:
            return None
        nxt = s.attributes.get("next_event")
        if isinstance(nxt, str):
            nxt = dt_util.parse_datetime(nxt)
        return nxt if isinstance(nxt, datetime) else None

    def _outdoor(self) -> float | None:
        return self._read_float(self._outdoor_sensor) if self._outdoor_sensor else None

    def _preheat_rate(self) -> float:
        return self._heat_rate.rate_at(self._outdoor())

    def _follow_preheat(self, now: datetime) -> None:
        """Watch the running preheat, and learn from it when the night has ended."""
        run = self._preheat_run
        if run is None:
            return
        room = self._room_temp
        if self._learning_paused(now):
            run["disturbed"] = True
        if self._preheat_for is not None and now < self._preheat_for:
            if room is not None and run["reached"] is None and room >= self._day_target - PREHEAT_REACHED:
                run["reached"] = now
            return
        self._preheat_run = None
        if run["disturbed"] or run["capped"] or room is None or run["end"] is None:
            return
        if now < run["end"] or now - run["end"] > timedelta(minutes=30):
            # Stopped before the night ended (preheat or schedule changed), or we weren't
            # running when it ended (restart, mode off): nothing to learn.
            return
        ran = (run["end"] - run["start"]).total_seconds() / 3600
        short_by = max(0.0, self._day_target - room)
        early = (
            (run["end"] - run["reached"]).total_seconds() / 3600 if run["reached"] is not None else 0.0
        )
        result = self._preheat_timing.learn(ran, short_by, early, self._preheat_rate())
        if result is not None:
            self._last_preheat = preheat_text(*result, self._lang)
            _LOGGER.info(
                "%s: %s (factor %.2f)", self.entity_id, self._last_preheat, self._preheat_timing.factor
            )

    def _update_preheat(self, now: datetime) -> None:
        self._follow_preheat(now)
        nxt = self._comfort_at()
        if not self._preheat_enabled or nxt is None or now >= nxt:
            self._preheat_for = None
            return
        if self._preheat_for == nxt:
            return  # latched: keep going even though the room is getting warmer
        room = self._room_temp
        if room is None:
            return
        rate = self._preheat_rate()
        hours = preheat_hours(
            rate, room, self._day_target, self._heat_rate.dead_time, self._preheat_timing.factor
        )
        if hours > 0 and now >= nxt - timedelta(hours=hours):
            self._preheat_for = nxt
            self._preheat_run = {
                "start": now,
                "end": nxt,
                "capped": hours >= MAX_PREHEAT_HOURS - 1e-6,
                "reached": None,
                "disturbed": self._window_open or self._learning_paused(now),
            }
            _LOGGER.info(
                "%s: preheating %.1f h before the night ends (%.0f min radiator warm-up, "
                "%.2f °C/h, factor %.2f)",
                self.entity_id, hours, self._heat_rate.dead_time * 60, rate,
                self._preheat_timing.factor,
            )

    def _outdoor_feedforward(self, target: float) -> float:
        if not self._outdoor_sensor:
            return 0.0
        outdoor = self._read_float(self._outdoor_sensor)
        if outdoor is None:
            return self._ff  # keep the last one through a sensor hiccup
        return round(max(0.0, self._outdoor_gain * (target - outdoor)), 2)

    def _check_spike(self, now: datetime, room: float | None) -> None:
        """Room warming much faster than a radiator can: a shower, cooking, a heater."""
        if room is None:
            return
        self._room_history.append((now, room))
        while self._room_history and now - self._room_history[0][0] > SPIKE_WINDOW:
            self._room_history.popleft()
        if room - min(r for _, r in self._room_history) >= SPIKE_RISE - 1e-6:
            if not self._learning_paused(now):
                _LOGGER.info("%s: sudden heat, pausing learning", self.entity_id)
            if self._spike_start is None:
                self._spike_start = (now, min(r for _, r in self._room_history))
            self._spike_until = now + SPIKE_PAUSE
            if self._heat_source_seen is not None:
                self._heat_source_seen = now  # still getting warmer: still burning
        self._follow_heat_source(now, room)
        self._follow_room_heat(now, room)

    def _other_room_burning(self) -> bool:
        """Whether a room that lists this one under "heat reaches" has a heat source on."""
        for entry in self.hass.config_entries.async_entries(DOMAIN):
            if entry.entry_id == self._entry.entry_id or entry.state is not ConfigEntryState.LOADED:
                continue
            conf = {**entry.data, **entry.options}
            if self.entity_id in (conf.get(CONF_HEATS_ROOMS) or []) and entry.runtime_data.diag.get(
                "heat_source"
            ):
                return True
        return False

    def _follow_room_heat(self, now: datetime, room: float) -> None:
        """A stove next door: no learning while it burns, nor until this room has cooled back."""
        if self._other_room_burning():
            self._room_heat_seen, self._room_heat_gone = now, None
            return
        if self._room_heat_seen is None:
            return
        if room > max(self._goal(), self._day_target) + HEAT_SOURCE_END + 1e-6:
            self._room_heat_gone = None
        elif self._room_heat_gone is None:
            self._room_heat_gone = now
        if (
            self._room_heat_gone is not None and now - self._room_heat_gone >= HEAT_SOURCE_SETTLE
        ) or now - self._room_heat_seen >= HEAT_SOURCE_MAX:
            _LOGGER.info("%s: heat from the other room is gone, learning again", self.entity_id)
            self._room_heat_seen = self._room_heat_gone = None

    def _follow_heat_source(self, now: datetime, room: float) -> None:
        """Tell a wood stove from a shower: it leaves the room well above the target for hours."""
        reference = max(self._goal(), self._day_target)
        if self._spike_until is None or now >= self._spike_until:
            self._spike_start = None
        if self._heat_source_seen is None:
            shower = self._humidity_until is not None and now < self._humidity_until
            if (
                self._spike_start is not None
                and not shower
                and now - self._spike_start[0] >= HEAT_SOURCE_LASTS
                and room >= reference + HEAT_SOURCE_ABOVE - 1e-6
                and room >= self._spike_start[1] + HEAT_SOURCE_RISE - 1e-6
            ):
                _LOGGER.info("%s: extra heat source, pausing learning until it is gone", self.entity_id)
                self._heat_source_seen = now
                self._heat_source_gone = None
            return
        if room > reference + HEAT_SOURCE_END + 1e-6:
            self._heat_source_gone = None
        elif self._heat_source_gone is None:
            self._heat_source_gone = now
        if (
            self._heat_source_gone is not None and now - self._heat_source_gone >= HEAT_SOURCE_SETTLE
        ) or now - self._heat_source_seen >= HEAT_SOURCE_MAX:
            _LOGGER.info("%s: extra heat is gone, learning again", self.entity_id)
            self._heat_source_seen = self._heat_source_gone = None

    def _check_humidity(self, now: datetime, humidity: float | None) -> None:
        """A fast humidity rise is a shower, even before the room has warmed."""
        if humidity is None:
            return
        self._humidity_history.append((now, humidity))
        while self._humidity_history and now - self._humidity_history[0][0] > SPIKE_WINDOW:
            self._humidity_history.popleft()
        if humidity - min(h for _, h in self._humidity_history) >= HUMIDITY_RISE - 1e-6:
            if not self._learning_paused(now):
                _LOGGER.info("%s: humidity jump (shower?), pausing learning", self.entity_id)
            self._spike_until = now + SPIKE_PAUSE
            self._humidity_until = now + SPIKE_PAUSE
            self._publish()

    def _find_humidity_sensor(self) -> None:
        """The humidity sensor on the same device as the room sensor (e.g. an SHT4x)."""
        reg = er.async_get(self.hass)
        if (entry := reg.async_get(self._room_sensor)) is None or entry.device_id is None:
            return
        for other in er.async_entries_for_device(reg, entry.device_id):
            if other.domain == "sensor" and (
                other.device_class or other.original_device_class
            ) == "humidity":
                self._humidity_sensor = other.entity_id
                return

    def _learning_paused(self, now: datetime) -> bool:
        return self._heat_source_seen is not None or self._room_heat_seen is not None or (
            self._spike_until is not None and now < self._spike_until
        )

    def _learn(self, now: datetime, room: float, target: float, dt_hours: float) -> None:
        paused = self._learning_paused(now)
        full_heat = self._pi.valve_saturated and self._pi.error > 0 and not paused
        outdoor = self._outdoor()
        hours = now.timestamp() / 3600
        self._heat_rate.observe(hours, room, full_heat, outdoor)
        # Valve shut and the room cooling: how fast the room loses heat to the outside.
        closed = self._pi.valve_saturated and self._pi.error < 0 and not paused
        self._heat_rate.observe_cooling(hours, room, closed, outdoor)

        if self._tuner is not None and dt_hours > 0 and not paused:
            steady = (
                not self._pi.valve_saturated
                and self._preheat_for is None
                and self._window_pending is None
                and target == self._last_target
            )
            if (change := self._tuner.observe(self._pi.error, dt_hours, steady)) is not None:
                self._pi.kp, self._pi.ki = self._tuner.kp, self._tuner.ki
                _LOGGER.info("%s: auto-tuning: %s", self.entity_id, change)
        if (
            dt_hours > 0
            and not paused
            and self._lowered is None
            and self._preheat_for is None
            and target == self._last_target
        ):
            # The reduction showing now was chosen SUN_LEAD_HOURS ago: learn from that step.
            lead = timedelta(hours=SUN_LEAD_HOURS)
            then = [h for h in self._sun_history if now - h[0] >= lead - timedelta(minutes=1)]
            if then:
                _, sun_then, shut_then = then[-1]
                self._sun.learn(self._local_hour(now), room - target, sun_then, dt_hours, not shut_then)
        self._last_target = target

    def _find_battery_entities(self) -> None:
        """Battery and valve-position sensors of each TRV, found through its device."""
        reg = er.async_get(self.hass)
        for trv in self._trvs:
            if (entry := reg.async_get(trv)) is None or entry.device_id is None:
                continue
            for other in er.async_entries_for_device(reg, entry.device_id):
                if other.domain == "number" and other.entity_id.endswith(
                    "_local_temperature_calibration"
                ):
                    self._calibration_entities.setdefault(trv, other.entity_id)
                    continue
                if other.domain != "sensor":
                    continue
                if (other.device_class or other.original_device_class) == "battery":
                    self._battery_entities.setdefault(trv, other.entity_id)
                elif other.entity_id.endswith("_position") or (
                    other.unique_id or ""
                ).endswith("_position"):
                    self._position_entities.setdefault(trv, other.entity_id)

    def _detect_trv_step(self) -> None:
        """Use the coarsest setpoint step any of the room's TRVs reports (TV02: 0.5 °C)."""
        steps = [
            float(step)
            for trv in self._trvs
            if (s := self.hass.states.get(trv)) is not None
            and (step := s.attributes.get("target_temp_step")) is not None
        ]
        step = max(steps) if steps else DEFAULT_TRV_STEP
        self._pi.step = self._pi.hysteresis = step

    def _valve_position(self) -> float | None:
        """Average valve opening in %, only when every TRV in the room reports one."""
        positions = [self._read_float(self._position_entities.get(trv, "")) for trv in self._trvs]
        if not positions or any(p is None for p in positions):
            return None
        return round(sum(positions) / len(positions))

    @property
    def _lang(self) -> str:
        """Danish or English, following Home Assistant's language."""
        return language(self.hass.config.language)

    def _check_trvs(self) -> dict[str, str]:
        """Problems per TRV: offline, silent for hours, or low battery."""
        problems: dict[str, str] = {}
        now = dt_util.utcnow()
        for trv in self._trvs:
            state = self.hass.states.get(trv)
            if state is None or state.state in (STATE_UNAVAILABLE, STATE_UNKNOWN):
                # Only after a while: right after a restart, or a short dropout, isn't a problem.
                since = self._started if state is None else max(state.last_changed, self._started)
                if now - since >= timedelta(minutes=TRV_OFFLINE_MINUTES):
                    problems[trv] = problem_text("offline", None, self._lang)
                continue
            silent = (now - state.last_reported).total_seconds() / 3600
            if silent >= TRV_STALE_HOURS:
                problems[trv] = problem_text("silent", silent, self._lang)
                continue
            battery = self._read_float(self._battery_entities.get(trv, ""))
            if battery is not None and battery < BATTERY_LOW:
                problems[trv] = problem_text("battery", battery, self._lang)
        return problems

    @property
    def _window_open(self) -> bool:
        """Whether heating is off for an open window (after the open delay)."""
        return self._window_off

    def _any_window_open(self) -> bool:
        return any(
            (s := self.hass.states.get(w)) is not None and s.state == STATE_ON
            for w in self._windows
        )

    def _read_float(self, entity_id: str) -> float | None:
        state = self.hass.states.get(entity_id)
        if state is None or state.state in (STATE_UNAVAILABLE, STATE_UNKNOWN):
            return None
        try:
            return float(state.state)
        except ValueError:
            return None

    def _trv_temperatures(self) -> dict[str, float]:
        """Each TRV's own reading, so an average over several TRVs can be explained."""
        return {
            trv: float(t)
            for trv in self._trvs
            if (s := self.hass.states.get(trv)) is not None
            and (t := s.attributes.get(ATTR_CURRENT_TEMPERATURE)) is not None
        }

    def _average_trv_temperature(self) -> float | None:
        temps = list(self._trv_temperatures().values())
        return round(sum(temps) / len(temps), 1) if temps else None

    def _first_trv_temperature(self) -> float | None:
        for trv in self._trvs:
            if (s := self.hass.states.get(trv)) is not None:
                if (t := s.attributes.get(ATTR_CURRENT_TEMPERATURE)) is not None:
                    return float(t)
        return None

    # ------------------------------------------------------------ entity API

    def _goal(self) -> float:
        """The goal right now: away, night or day temperature."""
        data = self._entry.runtime_data
        if self._away_active:
            temp = data.away_temperature
            if self._night_scheduled:
                temp = min(temp, data.night_temperature)
            return min(temp, self._day_target)
        if self._night_active:
            return data.night_temperature
        return self._day_target

    # HA 2026.11 renamed the temperature members to native_* and will drop the old names in
    # 2027.11; 2026.10 only knows the old ones. Serve whichever this Home Assistant uses.
    if _NATIVE_CLIMATE:
        _attr_native_temperature_unit = UnitOfTemperature.CELSIUS

        @property
        def native_current_temperature(self) -> float | None:
            return self._room_temp

        @property
        def native_target_temperature(self) -> float:
            return self._goal()

    else:
        _attr_temperature_unit = UnitOfTemperature.CELSIUS

        @property
        def current_temperature(self) -> float | None:
            return self._room_temp

        @property
        def target_temperature(self) -> float:
            return self._goal()

    @property
    def hvac_action(self) -> HVACAction:
        if (
            self._attr_hvac_mode == HVACMode.OFF
            or self._window_open
            or (self._summer and self._exercise_until is None)
        ):
            return HVACAction.OFF
        heating = False
        for trv in self._trvs:
            if (s := self.hass.states.get(trv)) is None:
                continue
            action = s.attributes.get(ATTR_HVAC_ACTION)
            if action is not None:
                heating |= action == HVACAction.HEATING
            else:  # TV02 reports no valve state: guess from its own sensor
                local = s.attributes.get(ATTR_CURRENT_TEMPERATURE)
                # Prefer what we commanded (the TRV may not have confirmed it yet), unless the
                # TRV has refused it.
                sp = s.attributes.get(ATTR_TEMPERATURE)
                if trv not in self._rejected:
                    sp = self._trv_setpoint or sp
                heating |= local is not None and sp is not None and float(local) < float(sp)
        return HVACAction.HEATING if heating else HVACAction.IDLE

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        return {
            ATTR_INTEGRAL: round(self._pi.integral, 3),
            ATTR_ERROR: round(self._pi.error, 2),
            ATTR_TRV_SETPOINT: self._trv_setpoint,
            ATTR_WINDOW_OPEN: self._window_open,
            ATTR_DAY_TEMPERATURE: self._day_target,
            ATTR_NIGHT_ACTIVE: self._night_active,
            ATTR_PREHEATING: self._preheat_for is not None,
            ATTR_HEAT_RATE: round(self._heat_rate.rate, 2),
            ATTR_HEAT_RATE_SAMPLES: self._heat_rate.samples,
            ATTR_PREHEAT_LEAD: round(self._heat_rate.dead_time * 60),
            ATTR_PREHEAT_FACTOR: self._preheat_timing.factor,
            ATTR_PREHEAT_LEARNING: self._heat_rate.to_dict(),
            ATTR_LAST_PREHEAT: self._last_preheat,
            ATTR_HEAT_SOURCE: self._heat_source_seen is not None,
            ATTR_HEAT_FROM_ROOM: self._room_heat_seen is not None,
            ATTR_KP: self._pi.kp,
            ATTR_KI: self._pi.ki,
            ATTR_TUNED_FROM: self._opt_gains,
            ATTR_LAST_TUNING: self._tuner.last_change if self._tuner else None,
            ATTR_OUTDOOR_FF: self._ff,
            ATTR_AWAY: self._away_active,
            ATTR_SUMMER: self._summer,
            ATTR_OUTDOOR_AVG: None if self._outdoor_avg is None else round(self._outdoor_avg, 2),
            ATTR_WARM_SINCE: self._warm_since.isoformat() if self._warm_since else None,
            ATTR_LAST_EXERCISE: self._last_exercise.isoformat() if self._last_exercise else None,
            ATTR_SUN_PROFILE: self._sun.bins,
            ATTR_SUN_REDUCTION: self._sun_ff,
            ATTR_HEATING_TODAY: round(self._heating_today, 3),
            ATTR_HEATING_TOTAL: round(self._heating_total, 3),
            ATTR_HEATING_DAY: self._heating_day,
        }

    async def async_set_temperature(self, **kwargs: Any) -> None:
        if (temp := kwargs.get(ATTR_TEMPERATURE)) is None:
            return
        # The thermostat card always shows the current goal, so it changes the current one.
        if self._away_active:
            self._entry.runtime_data.away_temperature = float(temp)
            async_dispatcher_send(self.hass, SIGNAL_SETTINGS.format(self._entry.entry_id))
        elif self._night_active:
            self._entry.runtime_data.night_temperature = float(temp)
            async_dispatcher_send(self.hass, SIGNAL_SETTINGS.format(self._entry.entry_id))
        else:
            self._day_target = float(temp)
        await self._async_control()

    async def async_set_hvac_mode(self, hvac_mode: HVACMode) -> None:
        self._attr_hvac_mode = hvac_mode
        await self._async_control()

    async def async_reset_integral(self) -> None:
        self._pi.integral = 0.0
        self._pi.output = None
        self._seeded = False
        await self._async_control()
