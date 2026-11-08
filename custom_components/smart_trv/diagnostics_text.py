"""Plain-language explanation of what the controller is doing right now, in Danish or English.

The language follows Home Assistant's own (hass.config.language): Danish for "da", English
otherwise. Numbers use a decimal comma in Danish and a point in English.
"""

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

TEXT: dict[str, dict[str, str]] = {
    "da": {
        "off": "Slukket. TRV'erne er slukket.",
        "window": "Vindue åbent. TRV'erne er slukket, og læringen står på pause.",
        "window_resume": " Lukket igen: varmen starter om {s} sek.",
        "no_sensor": "Ingen måling fra rumsensoren. TRV'erne beholder sidste setpunkt.",
        "at_target": "Rummet er på målet ({target})",
        "below": "Rummet er {diff} under målet ({room} af {target})",
        "above": "Rummet er {diff} over målet ({room} af {target})",
        "valve_open": "ventilen er åben",
        "valve_closed": "ventilen er lukket",
        "valve_pos": "ventilen står {pos} % åben",
        "reads_many": "TRV'erne måler i snit {avg} ({each})",
        "reads_one": "TRV'en måler {avg}",
        "window_pending": "🪟 Vindue/dør åben: slukker om {s} sek., hvis den bliver ved med at stå åben. ",
        "preheat": "☀️ Forvarmer: rummet skal være {target} kl. {time}, når natten slutter. ",
        "night": "🌙 Nattemperatur. ",
        "heat_source": "🔥 Ekstra varmekilde (fx brændeovn): læringen holder pause, til rummet er tilbage ved målet. ",
        "heat_from_room": "🔥 Varme fra et andet rum (fx brændeovn): læringen holder pause, til rummet er tilbage ved målet. ",
        "paused": "🚿 Pludselig varme eller fugt (fx bad eller madlavning): læringen holder pause til kl. {time}. ",
        "parts": "Lært offset {i} + reaktion nu {p}",
        "parts_outdoor": " + udetemperatur {o}",
        "sentence": "{where}. TRV sat til {sp}, {reads}, så {valve}. {parts}.",
        "cold_radiator": (
            " ⚠️ TRV'en har været helt åben i {h} t, men dens måling er kun steget {rise}: "
            "radiatoren bliver ikke varm. Test: skru TRV'en af i 30 min (så er ventilen helt åben). "
            "Bliver radiatoren varm, sidder fejlen i TRV'en/adapteren (ventilstiften trykkes ikke "
            "fri). Forbliver den kold, er det varmeforsyningen: fyr/fjernvarme, en lukket "
            "returventil eller fastsiddende ventilstift."
        ),
        "hot_radiator": (
            " ⚠️ Ventilen burde have været lukket i {h} t, men TRV'en måler stadig {trv} ({diff} "
            "over rummet): radiatoren er stadig varm, så ventilen lukker ikke helt. Tjek at "
            "TRV'en/adapteren trykker ventilstiften helt i bund (adapterens højde og låseskrue), "
            "og kør TRV'ens ventil-kalibrering igen, hvis den har en."
        ),
        "rejected": (
            " ⚠️ {trv} står stadig på {reported}, selvom Smart TRV har sendt {sent}. TRV'en tager "
            "ikke imod setpunktet. Tjek dens max_temperature i Zigbee2MQTT (sæt den til 35 °C) og "
            "at den står i preset manual."
        ),
        "calibration": (
            " ⚠️ {trv} har local_temperature_calibration {value}. Sæt den til 0 i Zigbee2MQTT og "
            "kør smart_trv.reset_integral."
        ),
        "calibration_guess": (
            " ⚠️ TRV'en måler {diff} koldere end rummet. Sidder den i kold luft, fx under et "
            "vindue, er det fint. Ellers tjek local_temperature_calibration i Zigbee2MQTT (skal "
            "være 0)."
        ),
        "problem": " ⚠️ {trv}: {problem}.",
        "problem_offline": "offline",
        "problem_silent": "ingen kontakt i {h} t",
        "problem_battery": "lavt batteri ({pct} %)",
        "preheat_late": "Forvarmningen kom {amount} for sent: starter tidligere fremover",
        "preheat_early": "Rummet var varmt {minutes} min før natten sluttede: starter senere fremover",
    },
    "en": {
        "off": "Off. The TRVs are off.",
        "window": "Window open. The TRVs are off and learning is paused.",
        "window_resume": " Closed again: heating resumes in {s} s.",
        "no_sensor": "No reading from the room sensor. The TRVs keep their last setpoint.",
        "at_target": "The room is on target ({target})",
        "below": "The room is {diff} below target ({room} of {target})",
        "above": "The room is {diff} above target ({room} of {target})",
        "valve_open": "the valve is open",
        "valve_closed": "the valve is closed",
        "valve_pos": "the valve is {pos} % open",
        "reads_many": "the TRVs read {avg} on average ({each})",
        "reads_one": "the TRV reads {avg}",
        "window_pending": "🪟 Window/door open: turning off in {s} s if it stays open. ",
        "preheat": "☀️ Preheating: the room should be {target} at {time}, when the night ends. ",
        "night": "🌙 Night temperature. ",
        "heat_source": "🔥 Extra heat source (e.g. a wood stove): learning paused until the room is back at its target. ",
        "heat_from_room": "🔥 Heat from another room (e.g. a wood stove): learning paused until the room is back at its target. ",
        "paused": "🚿 Sudden heat or humidity (e.g. a shower or cooking): learning paused until {time}. ",
        "parts": "Learned offset {i} + reaction now {p}",
        "parts_outdoor": " + outdoor {o}",
        "sentence": "{where}. TRV set to {sp}, {reads}, so {valve}. {parts}.",
        "cold_radiator": (
            " ⚠️ The TRV has been fully open for {h} h, but its reading rose only {rise}: the "
            "radiator isn't getting hot. Test: take the TRV off for 30 min (the valve is then fully "
            "open). If the radiator gets hot, the TRV/adapter is at fault (the valve pin isn't "
            "released). If it stays cold, it's the heat supply: boiler/district heating, a closed "
            "return valve or a stuck valve pin."
        ),
        "hot_radiator": (
            " ⚠️ The valve should have been closed for {h} h, but the TRV still reads {trv} ({diff} "
            "above the room): the radiator is still hot, so the valve doesn't fully close. Check "
            "that the TRV/adapter pushes the valve pin all the way in (adapter height and set "
            "screw), and run the TRV's valve calibration again if it has one."
        ),
        "rejected": (
            " ⚠️ {trv} still shows {reported} although Smart TRV sent {sent}. The TRV doesn't "
            "accept the setpoint. Check its max_temperature in Zigbee2MQTT (set it to 35 °C) and "
            "that it is in preset manual."
        ),
        "calibration": (
            " ⚠️ {trv} has local_temperature_calibration {value}. Set it to 0 in Zigbee2MQTT and "
            "run smart_trv.reset_integral."
        ),
        "calibration_guess": (
            " ⚠️ The TRV reads {diff} colder than the room. If it sits in cold air, e.g. under a "
            "window, that's fine. Otherwise check local_temperature_calibration in Zigbee2MQTT "
            "(should be 0)."
        ),
        "problem": " ⚠️ {trv}: {problem}.",
        "problem_offline": "offline",
        "problem_silent": "no contact for {h} h",
        "problem_battery": "low battery ({pct} %)",
        "preheat_late": "Preheating was {amount} short: starting earlier from now on",
        "preheat_early": "The room was warm {minutes} min before the night ended: starting later from now on",
    },
}


def language(hass_language: str | None) -> str:
    """Danish for Danish, English for everything else."""
    return "da" if (hass_language or "").lower().startswith("da") else "en"


def _num(value: float, lang: str) -> str:
    text = f"{value:.1f}"
    return text.replace(".", ",") if lang == "da" else text


def _c(value: float | None, lang: str = "da") -> str:
    if value is None:
        return "?"
    if abs(value) < 0.05:
        value = 0.0  # no "-0,0"
    return f"{_num(value, lang)} °C"


def problem_text(code: str, value: float | None, lang: str) -> str:
    """A TRV problem (offline / silent / battery) in the given language."""
    t = TEXT[lang]
    if code == "silent":
        return t["problem_silent"].format(h=f"{value:.0f}")
    if code == "battery":
        return t["problem_battery"].format(pct=f"{value:.0f}")
    return t["problem_offline"]


def preheat_text(verdict: str, amount: float, lang: str) -> str:
    """What the morning taught the preheat timing, in the given language."""
    t = TEXT[lang]
    if verdict == "late":
        return t["preheat_late"].format(amount=_c(amount, lang))
    return t["preheat_early"].format(minutes=f"{amount * 60:.0f}")


def explain(diag: dict[str, Any], room: float | None, target: float | None, lang: str = "da") -> str:
    t = TEXT[lang]
    text = _explain_control(diag, room, target, lang)
    # TRV health matters whatever the room is doing (also when off or aired).
    for trv_id, problem in (diag.get("problems") or {}).items():
        text += t["problem"].format(trv=trv_id, problem=problem)
    return text


def _explain_control(
    diag: dict[str, Any], room: float | None, target: float | None, lang: str
) -> str:
    t = TEXT[lang]

    def c(value: float | None) -> str:
        return _c(value, lang)

    status = diag["status"]
    if status == STATUS_OFF:
        return t["off"]
    if status == STATUS_WINDOW:
        text = t["window"]
        if diag.get("window_pending") == "on":
            text += t["window_resume"].format(s=diag.get("window_seconds_left"))
        return text
    if status == STATUS_NO_SENSOR:
        return t["no_sensor"]

    error = diag["error"]
    if abs(error) < 0.05:
        where = t["at_target"].format(target=c(target))
    elif error > 0:
        where = t["below"].format(diff=c(error), room=c(room), target=c(target))
    else:
        where = t["above"].format(diff=c(-error), room=c(room), target=c(target))

    valve = t["valve_open"] if status == STATUS_HEATING else t["valve_closed"]
    if (position := diag.get("valve_position")) is not None:
        valve = t["valve_pos"].format(pos=position)
    per_trv = diag.get("trv_temperatures") or {}
    if len(per_trv) > 1:
        reads = t["reads_many"].format(
            avg=c(diag["trv_temperature"]), each=", ".join(c(v) for v in per_trv.values())
        )
    else:
        reads = t["reads_one"].format(avg=c(diag["trv_temperature"]))

    pending = ""
    if diag.get("window_pending") == "off":
        pending = t["window_pending"].format(s=diag.get("window_seconds_left"))
    mode = ""
    if diag.get("preheat_until"):
        mode = t["preheat"].format(target=c(diag.get("day_target")), time=diag["preheat_until"])
    elif diag.get("night_active"):
        mode = t["night"]
    if diag.get("heat_source"):
        mode += t["heat_source"]
    elif diag.get("heat_from_room"):
        mode += t["heat_from_room"]
    elif diag.get("learning_paused_until"):
        mode += t["paused"].format(time=diag["learning_paused_until"])

    outdoor = diag.get("outdoor_ff") or 0.0
    parts = t["parts"].format(i=c(diag["integral"]), p=c(diag["p_term"]))
    if outdoor >= 0.05:
        parts += t["parts_outdoor"].format(o=c(outdoor))
    text = pending + mode + t["sentence"].format(
        where=where, sp=c(diag["trv_setpoint"]), reads=reads, valve=valve, parts=parts
    )

    trv = diag["trv_temperature"]
    hours = diag.get("full_open_hours", 0.0)
    rise = diag.get("full_open_trv_rise")
    # Judged by whether the TRV's reading rises, not by how warm it is: a TRV under a window
    # reads below the room even on a hot radiator.
    if hours >= COLD_RADIATOR_HOURS and rise is not None and rise < COLD_RADIATOR_RISE:
        text += t["cold_radiator"].format(h=_num(hours, lang), rise=c(rise))
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
        text += t["hot_radiator"].format(h=_num(closed, lang), trv=c(trv), diff=c(trv - room))
    for trv_id, (sent, reported) in (diag.get("rejected") or {}).items():
        text += t["rejected"].format(trv=trv_id, reported=c(reported), sent=c(sent))
    if diag.get("calibration_known"):
        # Read from the TRV itself: only a real offset is worth a warning.
        for trv_id, value in (diag.get("calibrations") or {}).items():
            if abs(value) >= 0.1:
                text += t["calibration"].format(trv=trv_id, value=c(value))
    elif trv is not None and room is not None and room - trv >= CALIBRATION_WARN_DELTA:
        # Can't read the calibration: only warn when the gap is too big for cold air alone.
        text += t["calibration_guess"].format(diff=c(room - trv))
    return text
