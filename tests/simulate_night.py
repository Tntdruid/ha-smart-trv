"""The living room on 21-22 Oct: the radiator can't deliver enough at night, then sun at 15:00.

Run:  python tests/simulate_night.py
"""

import math

from simulate import STEP, TARGET, PIController

DAYS = 3


def outdoor(minute):
    return 6 - 4 * math.cos(2 * math.pi * ((minute / 60 - 5) % 24) / 24)


def run(use_trv_reading):
    room, rad = 21.6, 0.3
    pi = PIController(kp=3.0, ki=1.0, max_boost=6.0, max_cut=3.0, step=STEP)
    setpoint, hist = TARGET, []
    for minute in range(DAYS * 24 * 60):
        hour = (minute % 1440) / 60
        supply = 0.75 if hour >= 22 or hour < 7 else 1.0  # weak/cold water at night
        sun = 1.2 if 14 <= hour < 16.5 else 0.0  # °C/h of free heat
        trv_local = room - 0.7 + 3.0 * rad * supply  # reads below the room when the radiator is cold
        if minute % 5 == 0:
            setpoint = pi.update(
                TARGET, room, 5 / 60 if minute else 0, trv_local if use_trv_reading else None
            )
        valve = max(0.0, min(1.0, (setpoint - trv_local) / 0.5))
        rad += (valve - rad) / 20
        room += (3.0 * rad * supply + sun - 0.12 * (room - outdoor(minute))) / 60
        hist.append((minute, room, pi.integral))
    return hist


def summary(name, hist):
    last = [(m % 1440 / 60, r, i) for m, r, i in hist if m >= (DAYS - 1) * 1440]
    night = [r for h, r, _ in last if h >= 23 or h < 7]
    sun = [r for h, r, _ in last if 14 <= h < 20]
    day = [r for h, r, _ in last if 9 <= h < 14]
    imax = max(i for _, _, i in last)
    print(f"{name:<34} night {min(night):.2f}-{max(night):.2f}  day {min(day):.2f}-{max(day):.2f}  "
          f"sun peak {max(sun):.2f}  max learned offset {imax:.1f}")


if __name__ == "__main__":
    summary("Before (no TRV reading)", run(False))
    summary("After (stop learning when valve full)", run(True))
