"""Outdoor compensation: cold nights with and without a feedforward from the outdoor sensor.

Run:  python tests/simulate_outdoor.py
"""

import math

from simulate import STEP, TARGET, PIController

DAYS = 4


def outdoor(minute):
    day = minute // 1440
    swing = 6 if day < 2 else 9  # a sudden colder spell from day 3
    return 6 - swing * math.cos(2 * math.pi * ((minute / 60 - 5) % 24) / 24) - (3 if day >= 2 else 0)


def run(gain):
    room, rad = 22.0, 0.5
    pi = PIController(kp=3.0, ki=1.0, max_boost=6.0, max_cut=3.0, step=STEP, hysteresis=STEP)
    setpoint, hist = TARGET, []
    for minute in range(DAYS * 1440):
        trv_local = room + 0.5 + 2.5 * rad
        out = outdoor(minute)
        if minute % 5 == 0:
            ff = gain * (TARGET - out)
            setpoint = pi.update(TARGET, room, 5 / 60 if minute else 0, trv_local, ff)
        valve = max(0.0, min(1.0, (setpoint - trv_local) / 0.5))
        rad += (valve - rad) / 20
        room += (3.0 * rad - 0.12 * (room - out)) / 60
        hist.append((minute, room))
    return hist


def summary(name, hist):
    for label, day in (("normal day", 1), ("cold snap", 2), ("cold day 2", 3)):
        r = [x for m, x in hist if day * 1440 <= m < (day + 1) * 1440]
        print(f"{name:<26} {label:<11} {min(r):.2f}-{max(r):.2f}  avg {sum(r)/len(r):.2f}")


if __name__ == "__main__":
    summary("Without outdoor sensor", run(0.0))
    summary("With outdoor (gain 0.1)", run(0.1))
