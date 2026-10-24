"""Plain-language (Danish) explanation of what the controller is doing right now."""

from __future__ import annotations

from typing import Any

from .const import STATUS_HEATING, STATUS_NO_SENSOR, STATUS_OFF, STATUS_WINDOW

# A TRV this much colder than the room almost certainly has a calibration offset set.
CALIBRATION_WARN_DELTA = 2.0
# Asked for full heat this long while the TRV (on the radiator) is still not warmer than the room.
COLD_RADIATOR_HOURS = 2.0


def _c(value: float | None) -> str:
    if value is None:
        return "?"
    if abs(value) < 0.05:
        value = 0.0  # no "-0,0"
    return f"{value:.1f}".replace(".", ",") + " °C"


def explain(diag: dict[str, Any], room: float | None, target: float | None) -> str:
    text = _explain_control(diag, room, target)
    # TRV health matters whatever the room is doing (also when off or aired).
    for trv_id, problem in (diag.get("problems") or {}).items():
        text += f" ⚠️ {trv_id}: {problem}."
    return text


def _explain_control(diag: dict[str, Any], room: float | None, target: float | None) -> str:
    status = diag["status"]
    if status == STATUS_OFF:
        return "Slukket. TRV'erne er slukket."
    if status == STATUS_WINDOW:
        text = "Vindue åbent. TRV'erne er slukket, og læringen står på pause."
        if diag.get("window_pending") == "on":
            text += f" Lukket igen: varmen starter om {diag.get('window_seconds_left')} sek."
        return text
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
    per_trv = diag.get("trv_temperatures") or {}
    reads = (
        f"TRV'erne måler i snit {_c(diag['trv_temperature'])} ("
        + ", ".join(_c(t) for t in per_trv.values())
        + ")"
        if len(per_trv) > 1
        else f"TRV'en måler {_c(diag['trv_temperature'])}"
    )
    pending = ""
    if diag.get("window_pending") == "off":
        pending = (
            f"🪟 Vindue/dør åben: slukker om {diag.get('window_seconds_left')} sek., "
            "hvis den bliver ved med at stå åben. "
        )
    mode = ""
    if diag.get("preheat_until"):
        mode = (
            f"☀️ Forvarmer: rummet skal være {_c(diag.get('day_target'))} "
            f"kl. {diag['preheat_until']}, når natten slutter. "
        )
    elif diag.get("night_active"):
        mode = "🌙 Nattemperatur. "
    outdoor = diag.get("outdoor_ff") or 0.0
    parts = f"Lært offset {_c(diag['integral'])} + reaktion nu {_c(diag['p_term'])}"
    if outdoor >= 0.05:
        parts += f" + udetemperatur {_c(outdoor)}"
    text = (
        pending
        + mode
        + f"{where}. TRV sat til {_c(diag['trv_setpoint'])}, {reads}, så {valve}. "
        f"{parts}."
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
            + f", men måler stadig kun {_c(trv)}: radiatoren bliver ikke varm. Test: skru "
            "TRV'en af i 30 min (så er ventilen helt åben). Bliver radiatoren varm, sidder fejlen "
            "i TRV'en/adapteren (ventilstiften trykkes ikke fri). Forbliver den kold, er det "
            "varmeforsyningen: fyr/fjernvarme, en lukket returventil eller fastsiddende ventilstift."
        )
    for trv_id, (sent, reported) in (diag.get("rejected") or {}).items():
        text += (
            f" ⚠️ {trv_id} står stadig på {_c(reported)}, selvom Smart TRV har sendt {_c(sent)}. "
            "TRV'en tager ikke imod setpunktet. Tjek dens max_temperature i Zigbee2MQTT "
            "(sæt den til 35 °C) og at den står i preset manual."
        )
    if trv is not None and room is not None and room - trv >= CALIBRATION_WARN_DELTA:
        text += (
            f" ⚠️ TRV'en måler {_c(room - trv)} koldere end rummet. Det er næsten altid en "
            "gammel local_temperature_calibration (fx fra Better Thermostat): sæt den til 0 "
            "i Zigbee2MQTT og kør smart_trv.reset_integral."
        )
    return text
