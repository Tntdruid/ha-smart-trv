"""Preheat and auto-tuning in a living-room model.

Run:  python tests/simulate_learning.py
"""

import importlib.util
import math
import random
import sys
from pathlib import Path

from simulate import STEP, PIController

_spec = importlib.util.spec_from_file_location(
    "learning", Path(__file__).parents[1] / "custom_components/smart_trv/learning.py"
)
learning = importlib.util.module_from_spec(_spec)
sys.modules["learning"] = learning
_spec.loader.exec_module(learning)

DAY, NIGHT = 22.0, 19.0
NIGHT_START, NIGHT_END = 22 * 60, 6 * 60  # minutes of the day


def outdoor(minute):
    return 6 - 4 * math.cos(2 * math.pi * ((minute / 60 - 5) % 24) / 24)


def is_night(tod):
    return tod >= NIGHT_START or tod < NIGHT_END


def run(days, preheat=True, kp=3.0, ki=1.0, tune=False, seed=1, noise=0.03, rad_lag=20):
    rnd = random.Random(seed)
    room, rad = 21.0, 0.3
    pi = PIController(kp=kp, ki=ki, max_boost=6.0, max_cut=3.0, step=STEP, hysteresis=STEP)
    rate = learning.HeatRateLearner()
    tuner = learning.AutoTuner(kp=kp, ki=ki) if tune else None
    preheat_for, last_target, setpoint = None, None, DAY
    at_wakeup, bands, gains = [], [], []
    day_vals = []
    for minute in range(days * 1440):
        tod = minute % 1440
        trv_local = room + 0.5 + 2.5 * rad
        if minute % 5 == 0:
            # night ends at the next 06:00
            night_end = minute - tod + NIGHT_END + (1440 if tod >= NIGHT_END else 0)
            if not is_night(tod):
                preheat_for = None
            elif preheat and preheat_for != night_end:
                need = learning.preheat_hours(rate.rate, room, DAY)
                if need > 0 and minute >= night_end - need * 60:
                    preheat_for = night_end
            target = NIGHT if is_night(tod) and preheat_for is None else DAY
            measured = room + rnd.gauss(0, noise)
            setpoint = pi.update(target, measured, 5 / 60 if minute else 0, trv_local)
            rate.observe(minute / 60, room, pi.valve_saturated and pi.error > 0)
            if tuner:
                steady = not pi.valve_saturated and preheat_for is None and target == last_target
                if tuner.observe(pi.error, 5 / 60, steady):
                    pi.kp, pi.ki = tuner.kp, tuner.ki
            last_target = target
        valve = max(0.0, min(1.0, (setpoint - trv_local) / 0.5))
        rad += (valve - rad) / rad_lag
        room += (3.0 * rad - 0.12 * (room - outdoor(minute))) / 60
        if tod == NIGHT_END:
            at_wakeup.append(room)
        if 10 * 60 <= tod < 21 * 60:
            day_vals.append(room)
        if tod == 1439:
            bands.append((min(day_vals), max(day_vals)))
            gains.append((pi.kp, pi.ki))
            day_vals = []
    return at_wakeup, bands, gains, rate


if __name__ == "__main__":
    print("Preheat (night 19 °C until 06:00, day 22 °C), room at 06:00:")
    for name, pre in (("without preheat", False), ("with preheat", True)):
        wake, _, _, rate = run(5, preheat=pre)
        print(f"  {name:<16} " + "  ".join(f"{w:.1f}" for w in wake) + f"   (learned {rate.rate:.2f} °C/h)")

    print("\nAuto-tuning from bad gains, daytime band per day (10-21):")
    for name, kp, ki, lag in (
        ("too aggressive, slow rad", 6.0, 3.0, 60),
        ("too sluggish", 1.0, 0.3, 20),
        ("default", 3.0, 1.0, 20),
    ):
        for tune in (False, True):
            _, bands, gains, _ = run(14, preheat=True, kp=kp, ki=ki, tune=tune, rad_lag=lag)
            last = bands[-3:]
            spread = max(b - a for a, b in last)
            lo = min(a for a, _ in last)
            hi = max(b for _, b in last)
            label = f"{name} {'tuned' if tune else 'fixed'}"
            print(f"  {label:<32} last 3 days {lo:.2f}-{hi:.2f} (spread {spread:.2f})  Kp/Ki now {gains[-1]}")
