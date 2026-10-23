"""Smart TRV climate entity."""

from __future__ import annotations

from datetime import datetime, timedelta
import logging
from typing import Any

from homeassistant.components.climate import (
    ATTR_CURRENT_TEMPERATURE,
    ATTR_HVAC_ACTION,
    ATTR_HVAC_MODES,
    ATTR_MIN_TEMP,
    ATTR_PRESET_MODE,
    ATTR_PRESET_MODES,
    ClimateEntity,
    ClimateEntityFeature,
    HVACAction,
    HVACMode,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import (
    ATTR_ENTITY_ID,
    ATTR_TEMPERATURE,
    CONF_NAME,
    STATE_ON,
    STATE_UNAVAILABLE,
    STATE_UNKNOWN,
    UnitOfTemperature,
)
from homeassistant.core import Event, EventStateChangedData, HomeAssistant, callback
from homeassistant.helpers import entity_platform
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.dispatcher import async_dispatcher_connect, async_dispatcher_send
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.event import async_track_state_change_event, async_track_time_interval
from homeassistant.helpers.restore_state import RestoreEntity
from homeassistant.util import dt as dt_util

from .const import (
    ATTR_ERROR,
    ATTR_INTEGRAL,
    ATTR_TRV_SETPOINT,
    ATTR_WINDOW_OPEN,
    CONF_INTERVAL,
    CONF_KI,
    CONF_KP,
    CONF_MAX_BOOST,
    CONF_MAX_CUT,
    CONF_NIGHT_ENTITY,
    CONF_ROOM_SENSOR,
    CONF_TRV_STEP,
    CONF_TRVS,
    CONF_WINDOWS,
    DEFAULT_INTERVAL,
    DEFAULT_KI,
    DEFAULT_KP,
    DEFAULT_MAX_BOOST,
    DEFAULT_MAX_CUT,
    DEFAULT_TRV_STEP,
    DOMAIN,
    SIGNAL_SETTINGS,
    SIGNAL_UPDATE,
    STATUS_HEATING,
    STATUS_IDLE,
    STATUS_NO_SENSOR,
    STATUS_OFF,
    STATUS_WINDOW,
    TRV_MAX_TEMP,
    TRV_MIN_TEMP,
)
from .controller import PIController
from .diagnostics_text import explain

_LOGGER = logging.getLogger(__name__)

# Re-send a setpoint the TRV hasn't confirmed after this long (Zigbee messages do get lost).
RESEND_AFTER = timedelta(minutes=10)
# Longest gap fed into the integral, so a long outage doesn't cause a jump.
MAX_DT_HOURS = 0.5

ATTR_DAY_TEMPERATURE = "day_temperature"
ATTR_NIGHT_ACTIVE = "night_active"


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    async_add_entities([SmartTRVClimate(entry)])
    platform = entity_platform.async_get_current_platform()
    platform.async_register_entity_service("reset_integral", None, "async_reset_integral")


class SmartTRVClimate(ClimateEntity, RestoreEntity):
    _attr_has_entity_name = True
    _attr_name = None
    _attr_hvac_modes = [HVACMode.HEAT, HVACMode.OFF]
    _attr_supported_features = (
        ClimateEntityFeature.TARGET_TEMPERATURE
        | ClimateEntityFeature.TURN_ON
        | ClimateEntityFeature.TURN_OFF
    )
    _attr_temperature_unit = UnitOfTemperature.CELSIUS
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
        self._interval = timedelta(minutes=conf.get(CONF_INTERVAL, DEFAULT_INTERVAL))
        self._pi = PIController(
            kp=conf.get(CONF_KP, DEFAULT_KP),
            ki=conf.get(CONF_KI, DEFAULT_KI),
            max_boost=conf.get(CONF_MAX_BOOST, DEFAULT_MAX_BOOST),
            max_cut=conf.get(CONF_MAX_CUT, DEFAULT_MAX_CUT),
            step=conf.get(CONF_TRV_STEP, DEFAULT_TRV_STEP),
            hysteresis=conf.get(CONF_TRV_STEP, DEFAULT_TRV_STEP),
            min_temp=TRV_MIN_TEMP,
            max_temp=TRV_MAX_TEMP,
        )
        self._attr_unique_id = entry.entry_id
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)}, name=conf[CONF_NAME], model="PI controller"
        )
        self._attr_hvac_mode = HVACMode.HEAT
        self._day_target = 21.0
        self._attr_current_temperature: float | None = None
        self._seeded = False
        self._last_run: datetime | None = None
        self._trv_setpoint: float | None = None
        self._last_sent: dict[str, tuple[float, datetime]] = {}
        self._trvs_off = False
        self._full_open_since: datetime | None = None
        # TRVs still reporting another setpoint than we sent, after a resend: trv -> (sent, reported)
        self._rejected: dict[str, tuple[float, float]] = {}

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

        self._attr_current_temperature = self._read_float(self._room_sensor)

        self.async_on_remove(
            async_track_state_change_event(
                self.hass,
                [self._room_sensor, *self._windows, *filter(None, [self._night_entity])],
                self._async_input_changed,
            )
        )
        self.async_on_remove(
            async_dispatcher_connect(
                self.hass, SIGNAL_SETTINGS.format(self._entry.entry_id), self._async_settings_changed
            )
        )
        self.async_on_remove(
            async_track_state_change_event(self.hass, self._trvs, self._async_trv_changed)
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
            self._attr_current_temperature = self._read_float(self._room_sensor)
            self._publish()
            return
        self.hass.async_create_task(self._async_control())  # window or night changed: act now

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
        room = self._attr_current_temperature

        if self._attr_hvac_mode == HVACMode.OFF or self._window_open:
            self._last_run = now  # freeze the integral while not heating
            self._full_open_since = None
            await self._async_turn_trvs_off()
            self._publish()
            return

        target = self.target_temperature
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

        self._trv_setpoint = self._pi.update(
            target, room, dt_hours, self._average_trv_temperature()
        )
        # Track how long the TRV has been asked for full heat, to spot a radiator that stays cold.
        if self._pi.valve_saturated and self._pi.error > 0:
            self._full_open_since = self._full_open_since or now
        else:
            self._full_open_since = None
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

            # Some TRVs (e.g. Tuya TRV602) have no hvac modes to set, only presets.
            modes = state.attributes.get(ATTR_HVAC_MODES) or [HVACMode.HEAT, HVACMode.OFF]
            if HVACMode.HEAT in modes and state.state != HVACMode.HEAT:
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
                # Sent a while ago and the TRV still shows something else: it is refusing it,
                # e.g. a TRV602 whose max_temperature is below what we ask for.
                self._rejected[trv] = (setpoint, float(reported))
            await self._call("set_temperature", trv, temperature=setpoint)
            self._last_sent[trv] = (setpoint, now)

    async def _async_turn_trvs_off(self) -> None:
        if self._trvs_off:
            return
        for trv in self._trvs:
            state = self.hass.states.get(trv)
            if state is None or state.state in (HVACMode.OFF, STATE_UNAVAILABLE, STATE_UNKNOWN):
                continue
            # Use whatever "off" the TRV has: hvac mode (TV02), preset (TRV602), or lowest setpoint.
            modes = state.attributes.get(ATTR_HVAC_MODES) or [HVACMode.HEAT, HVACMode.OFF]
            presets = state.attributes.get(ATTR_PRESET_MODES) or []
            if HVACMode.OFF in modes:
                await self._call("set_hvac_mode", trv, hvac_mode=HVACMode.OFF)
            elif "off" in presets:
                if state.attributes.get(ATTR_PRESET_MODE) != "off":
                    await self._call("set_preset_mode", trv, preset_mode="off")
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
        self.async_write_ha_state()
        self._entry.runtime_data.diag = self._diagnostics()
        async_dispatcher_send(self.hass, SIGNAL_UPDATE.format(self._entry.entry_id))

    def _diagnostics(self) -> dict[str, Any]:
        trv_temp = self._average_trv_temperature()
        if self._attr_hvac_mode == HVACMode.OFF:
            status = STATUS_OFF
        elif self._window_open:
            status = STATUS_WINDOW
        elif self._attr_current_temperature is None:
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
            "rejected": dict(self._rejected),
            "error": round(self._pi.error, 2),
            "p_term": round(self._pi.kp * self._pi.error, 2),
            "integral": round(self._pi.integral, 2),
            "night_active": self._night_active,
            "full_open_hours": (
                round((dt_util.utcnow() - self._full_open_since).total_seconds() / 3600, 1)
                if self._full_open_since
                else 0.0
            ),
        }
        diag["explanation"] = explain(
            diag, self._attr_current_temperature, self.target_temperature
        )
        return diag

    # ------------------------------------------------------------------- helpers

    @property
    def _night_active(self) -> bool:
        return (
            self._night_entity is not None
            and (s := self.hass.states.get(self._night_entity)) is not None
            and s.state == STATE_ON
        )

    @property
    def _window_open(self) -> bool:
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

    @property
    def target_temperature(self) -> float:
        """The goal right now: the night temperature while the night entity is on."""
        if self._night_active:
            return self._entry.runtime_data.night_temperature
        return self._day_target

    @property
    def hvac_action(self) -> HVACAction:
        if self._attr_hvac_mode == HVACMode.OFF or self._window_open:
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
        }

    async def async_set_temperature(self, **kwargs: Any) -> None:
        if (temp := kwargs.get(ATTR_TEMPERATURE)) is None:
            return
        # The thermostat card always shows the current goal, so it changes the current one.
        if self._night_active:
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
