"""Plain-language (Danish) explanation of what the controller is doing right now."""

from __future__ import annotations

from typing import Any

from .const import STATUS_HEATING, STATUS_NO_SENSOR, STATUS_OFF, STATUS_WINDOW

# A TRV this much colder than the room almost certainly has a calibration offset set.
CALIBRATION_WARN_DELTA = 2.0
# Asked for full heat this long while the TRV (on the radiator) is still not warmer than the room.
COLD_RADIATOR_HOURS = 2.0


def _c(value: float | None) -> str:
    return "?" if value is None else f"{value:.1f}".replace(".", ",") + " °C"


def explain(diag: dict[str, Any], room: float | None, target: float | None) -> str:
    status = diag["status"]
    if status == STATUS_OFF:
        return "Slukket. TRV'erne er slukket."
    if status == STATUS_WINDOW:
        return "Vindue åbent. TRV'erne er slukket, og læringen står på pause."
    if status == STATUS_NO_SENSOR:
        return "Ingen måling fra rumsensoren. TRV'erne beholder sidste setpunkt."

    error = diag["error"]
    if abs(error) < 0.05:
        where = f"Rummet er på målet ({_c(target)})"
    elif error > 0:
        where = f"Rummet er {_c(error)} under målet ({_c(room)} af {_c(target)})"
    else:
        where = f"Rummet er {_c(-error)} over målet ({_c(room)} af {_c(target)})"

    valve = "ventilen er åben" if status == STATUS_HEATING else "ventilen er lukket"
    text = (
        ("🌙 Nattemperatur. " if diag.get("night_active") else "")
        + f"{where}. TRV sat til {_c(diag['trv_setpoint'])}, TRV'en måler "
        f"{_c(diag['trv_temperature'])}, så {valve}. "
        f"Lært offset {_c(diag['integral'])} + reaktion nu {_c(diag['p_term'])}."
    )
    trv = diag["trv_temperature"]
    hours = diag.get("full_open_hours", 0.0)
    if (
        hours >= COLD_RADIATOR_HOURS
        and trv is not None
        and room is not None
        and room - trv < CALIBRATION_WARN_DELTA
        and trv < room + 1.0
    ):
        text += (
            f" ⚠️ TRV'en har været helt åben i {hours:.1f} t".replace(".", ",")
            + f", men måler stadig kun {_c(trv)}: radiatoren bliver ikke varm. Tjek "
            "fremløbstemperatur/natsænkning på fyr eller fjernvarme, luft i radiatoren, "
            "og at TV02 trykker ventilstiften helt."
        )
    if trv is not None and room is not None and room - trv >= CALIBRATION_WARN_DELTA:
        text += (
            f" ⚠️ TRV'en måler {_c(room - trv)} koldere end rummet. Det er næsten altid en "
            "gammel local_temperature_calibration (fx fra Better Thermostat): sæt den til 0 "
            "i Zigbee2MQTT og kør smart_trv.reset_integral."
        )
    return text
