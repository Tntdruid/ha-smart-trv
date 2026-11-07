"""Preheat timing over three weeks of changing weather: the old fixed estimate vs. learning
radiator warm-up time, outdoor temperature and each morning's result.

Run:  python tests/simulate_preheat.py
"""

import math
import random

from simulate import STEP, PIController
from simulate_learning import learning

DAY, NIGHT = 22.0, 19.0
NIGHT_START, NIGHT_END = 22 * 60, 6 * 60
DAYS = 21


class OldRate:
    """The previous version: one warm-up rate, measured from the moment the valve opened."""

    def __init__(self):
        self.rate, self.samples, self._start = 1.0, 0, None

    def observe(self, t, room, full):
        if not full:
            self._start = None
            return
        if self._start is None:
            self._start = (t, room)
            return
        t0, r0 = self._start
        if t - t0 < 0.5:
            return
        if room - r0 > 0.05:
            m = min(5.0, max(0.05, (room - r0) / (t - t0)))
            self.rate = m if self.samples == 0 else 0.75 * self.rate + 0.25 * m
            self.samples += 1
        self._start = (t, room)


def weather(seed):
    """A daily mean that wanders between about -6 and 12 °C, plus a day/night swing."""
    rnd = random.Random(seed)
    means, m = [], 4.0
    for _ in range(DAYS + 1):
        m = max(-6.0, min(12.0, m + rnd.gauss(0, 3.0)))
        means.append(m)

    def outdoor(minute):
        d = means[minute // 1440]
        return d - 3 * math.cos(2 * math.pi * ((minute / 60 - 5) % 24) / 24)

    return outdoor


def run(smart, seed=3, rad_lag=35):
    outdoor = weather(seed)
    rnd = random.Random(seed)
    room, rad = 21.0, 0.3
    pi = PIController(kp=3.0, ki=1.0, max_boost=6.0, max_cut=3.0, step=STEP, hysteresis=STEP)
    rate = learning.HeatRateLearner() if smart else OldRate()
    timing = learning.PreheatTiming()
    preheat_for = run_start = reached = None
    results = []  # (room at 06:00, minutes warm before 06:00, outdoor at 06:00)
    setpoint = DAY
    for minute in range(DAYS * 1440):
        tod = minute % 1440
        trv_local = room + 0.5 + 2.5 * rad
        if minute % 5 == 0:
            night_end = minute - tod + NIGHT_END + (1440 if tod >= NIGHT_END else 0)
            out = outdoor(minute)
            if preheat_for is not None and minute >= preheat_for:
                early = (preheat_for - reached) / 60 if reached is not None else 0.0
                results.append((room, early * 60, out))
                if smart:
                    ran = (preheat_for - run_start) / 60
                    timing.learn(ran, max(0.0, DAY - room), early, rate.rate_at(out))
                preheat_for = reached = None
            elif preheat_for is not None and reached is None and room >= DAY - 0.1:
                reached = minute
            if is_night := (tod >= NIGHT_START or tod < NIGHT_END):
                if preheat_for is None:
                    if smart:
                        need = learning.preheat_hours(
                            rate.rate_at(out), room, DAY, rate.dead_time, timing.factor
                        )
                    else:
                        need = learning.preheat_hours(rate.rate, room, DAY, 0.0, 1.2)
                    if need > 0 and minute >= night_end - need * 60:
                        preheat_for, run_start = night_end, minute
            target = NIGHT if is_night and preheat_for is None else DAY
            setpoint = pi.update(target, room + rnd.gauss(0, 0.03), 5 / 60 if minute else 0, trv_local)
            full = pi.valve_saturated and pi.error > 0
            if smart:
                rate.observe(minute / 60, room, full, out)
                rate.observe_cooling(minute / 60, room, pi.valve_saturated and pi.error < 0, out)
            else:
                rate.observe(minute / 60, room, full)
        valve = max(0.0, min(1.0, (setpoint - trv_local) / 0.5))
        rad += (valve - rad) / rad_lag
        room += (4.5 * rad - 0.12 * (room - outdoor(minute))) / 60
    return results[7:]  # after a week of learning


if __name__ == "__main__":
    seeds = range(1, 6)
    print("Night 19 °C until 06:00, day 22 °C, slow radiator, weather changing day to day.")
    print(f"{len(seeds)} runs of 3 weeks, the last 14 mornings of each (after a week of learning):\n")
    for name, smart in (("Before (one rate, +20 %)", False), ("Now (warm-up, outdoor, mornings)", True)):
        res = [m for seed in seeds for m in run(smart, seed)]
        late = [DAY - r for r, _, _ in res if DAY - r > 0.15]
        early = [e for r, e, _ in res if DAY - r <= 0.15]
        print(f"  {name:<34} late {len(late):>2} of {len(res)} mornings"
              f" (worst {max(late, default=0):.1f} °C short),"
              f" warm on average {sum(early) / max(1, len(early)):.0f} min too early")
