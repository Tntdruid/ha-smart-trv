"""Plain-language (Danish) explanation of what the controller is doing right now."""

from __future__ import annotations

from typing import Any

from .const import STATUS_HEATING, STATUS_NO_SENSOR, STATUS_OFF, STATUS_WINDOW

# Without a readable calibration entity: a TRV this much colder than the room is more than cold
# air by a window can explain (Stue's TRVs under the window read ~2 °C below the room).
CALIBRATION_WARN_DELTA = 4.0
# Fully open this long while the TRV's own reading rose less than this: the radiator stays cold.
COLD_RADIATOR_HOURS = 2.0
COLD_RADIATOR_RISE = 0.5
# Told to close this long, yet the TRV still reads this much above the room and has barely
# cooled: the radiator stays hot, the valve doesn't shut (Soveværelse: 23.9 °C at a 21.5 setpoint).
HOT_RADIATOR_HOURS = 2.0
HOT_RADIATOR_ABOVE_ROOM = 1.0
HOT_RADIATOR_DROP = 0.5


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
    if (position := diag.get("valve_position")) is not None:
        valve = f"ventilen står {position} % åben"
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
    if diag.get("learning_paused_until"):
        mode += (
            "🚿 Pludselig varme eller fugt (fx bad eller madlavning): læringen holder pause til "
            f"kl. {diag['learning_paused_until']}. "
        )
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
    rise = diag.get("full_open_trv_rise")
    # Judged by whether the TRV's reading rises, not by how warm it is: a TRV under a window
    # reads below the room even on a hot radiator.
    if hours >= COLD_RADIATOR_HOURS and rise is not None and rise < COLD_RADIATOR_RISE:
        text += (
            f" ⚠️ TRV'en har været helt åben i {hours:.1f} t".replace(".", ",")
            + f", men dens måling er kun steget {_c(rise)}: radiatoren bliver ikke varm. Test: skru "
            "TRV'en af i 30 min (så er ventilen helt åben). Bliver radiatoren varm, sidder fejlen "
            "i TRV'en/adapteren (ventilstiften trykkes ikke fri). Forbliver den kold, er det "
            "varmeforsyningen: fyr/fjernvarme, en lukket returventil eller fastsiddende ventilstift."
        )
    closed = diag.get("closed_hours", 0.0)
    drop = diag.get("closed_trv_drop")
    if (
        closed >= HOT_RADIATOR_HOURS
        and drop is not None
        and drop < HOT_RADIATOR_DROP
        and trv is not None
        and room is not None
        and trv - room >= HOT_RADIATOR_ABOVE_ROOM
    ):
        text += (
            f" ⚠️ Ventilen burde have været lukket i {closed:.1f} t".replace(".", ",")
            + f", men TRV'en måler stadig {_c(trv)} ({_c(trv - room)} over rummet): radiatoren "
            "er stadig varm, så ventilen lukker ikke helt. Tjek at TRV'en/adapteren trykker "
            "ventilstiften helt i bund (adapterens højde og låseskrue), og kør TRV'ens "
            "ventil-kalibrering igen, hvis den har en."
        )
    for trv_id, (sent, reported) in (diag.get("rejected") or {}).items():
        text += (
            f" ⚠️ {trv_id} står stadig på {_c(reported)}, selvom Smart TRV har sendt {_c(sent)}. "
            "TRV'en tager ikke imod setpunktet. Tjek dens max_temperature i Zigbee2MQTT "
            "(sæt den til 35 °C) og at den står i preset manual."
        )
    if diag.get("calibration_known"):
        # Read from the TRV itself: only a real offset is worth a warning.
        for trv_id, value in (diag.get("calibrations") or {}).items():
            if abs(value) >= 0.1:
                text += (
                    f" ⚠️ {trv_id} har local_temperature_calibration {_c(value)}. Sæt den til 0 "
                    "i Zigbee2MQTT og kør smart_trv.reset_integral."
                )
    elif trv is not None and room is not None and room - trv >= CALIBRATION_WARN_DELTA:
        # Can't read the calibration: only warn when the gap is too big for cold air alone.
        text += (
            f" ⚠️ TRV'en måler {_c(room - trv)} koldere end rummet. Sidder den i kold luft, fx "
            "under et vindue, er det fint. Ellers tjek local_temperature_calibration i "
            "Zigbee2MQTT (skal være 0)."
        )
    return text
