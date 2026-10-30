"""Lukewarm radiators (district heating) and a TRV that opens gradually (TRV602 'comfort').

The TRV then reads only ~1 °C above the room even while heating. The rule "setpoint 1 °C above
what the TRV reads = valve fully open" freezes the integral and the room stays under target
(Alrum and Stue, 30 Oct). Compare: margin 1.0, margin 2.0, and using the TRV's own valve position.

Run:  python tests/simulate_lukewarm.py
"""

import math

from simulate import STEP, PIController

TARGET = 21.5
DAYS = 4
BAND = 2.0  # °C between closed and fully open for a modulating TRV


def outdoor(minute):
    return 6 - 4 * math.cos(2 * math.pi * ((minute / 60 - 5) % 24) / 24)


def run(margin=None, use_position=False, start_integral=0.0):
    room, rad = 21.2, 0.4
    pi = PIController(kp=3.0, ki=1.0, max_boost=6.0, max_cut=3.0, step=STEP, hysteresis=STEP)
    if margin is not None:
        pi.valve_margin = margin
    pi.integral = start_integral
    setpoint, hist = TARGET, []
    valve = 0.0
    for minute in range(DAYS * 1440):
        trv_local = room + 1.0 * rad  # lukewarm: at most 1 °C above the room
        if minute % 5 == 0:
            setpoint = pi.update(
                TARGET, room, 5 / 60 if minute else 0, trv_local,
                valve_position=valve * 100 if use_position else None,
            )
        valve = max(0.0, min(1.0, (setpoint - trv_local) / BAND))
        rad += (valve - rad) / 20
        room += (2.2 * rad - 0.12 * (room - outdoor(minute))) / 60
        hist.append((minute, room, pi.integral))
    return hist


def summary(name, hist):
    last = [(r, i) for m, r, i in hist if m >= (DAYS - 1) * 1440]
    rooms = [r for r, _ in last]
    print(f"{name:<34} last day {min(rooms):.2f}-{max(rooms):.2f} avg {sum(rooms)/len(rooms):.2f}"
          f"  learned offset {last[-1][1]:+.1f}")


if __name__ == "__main__":
    print(f"Target {TARGET} °C, lukewarm radiators, valve opens over {BAND} °C")
    summary("margin 1.0 (v0.5)", run(margin=1.0))
    summary("margin 1.0, offset already -2.3", run(margin=1.0, start_integral=-2.3))
    summary("margin 2.0", run(margin=2.0))
    summary("margin 2.0, offset already -2.3", run(margin=2.0, start_integral=-2.3))
    summary("TRV valve position", run(use_position=True))
    summary("TRV valve position, offset -2.3", run(use_position=True, start_integral=-2.3))
