"""How often does the TRV setpoint change? Room sensor with noise, reporting every minute.

Before: control ran on every sensor update. After: control on the 5 min timer with output hysteresis.

Run:  python tests/simulate_chatter.py
"""

import math
import random

from simulate import STEP, TARGET, PIController

DAYS = 3


def outdoor(minute):
    return 6 - 4 * math.cos(2 * math.pi * ((minute / 60 - 5) % 24) / 24)


def run(every_update, hysteresis, seed=1):
    rnd = random.Random(seed)
    room, rad = 21.8, 0.5
    pi = PIController(kp=3.0, ki=1.0, max_boost=6.0, max_cut=3.0, step=STEP, hysteresis=hysteresis)
    pi.seed(room + 0.5, room)
    setpoint, last_t, changes, hist = None, 0, 0, []
    for minute in range(DAYS * 24 * 60):
        measured = round(room + rnd.gauss(0, 0.04), 2)  # SHT4x-ish noise, reported every minute
        trv_local = room + 0.5 + 2.5 * rad
        if every_update or minute % 5 == 0:
            new = pi.update(TARGET, measured, (minute - last_t) / 60, trv_local)
            last_t = minute
            if minute >= (DAYS - 1) * 1440 and setpoint is not None and new != setpoint:
                changes += 1
            setpoint = new
        valve = max(0.0, min(1.0, (setpoint - trv_local) / 0.5))
        rad += (valve - rad) / 20
        room += (3.0 * rad - 0.12 * (room - outdoor(minute))) / 60
        if minute >= (DAYS - 1) * 1440:
            hist.append(room)
    return changes, min(hist), max(hist), sum(hist) / len(hist)


if __name__ == "__main__":
    for name, every, hyst in (
        ("Before (every update, no hysteresis)", True, 0.0),
        ("After (5 min timer + hysteresis)", False, STEP),
    ):
        c, lo, hi, avg = run(every, hyst)
        print(f"{name:<40} TRV setpoint changes/day {c:>4}   room {lo:.2f}-{hi:.2f} (avg {avg:.2f})")
