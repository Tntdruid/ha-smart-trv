"""What Smart TRV learns about each room. No Home Assistant imports, so it can be simulated.

- HeatRateLearner: how long the radiator takes to start and how fast the room then warms,
  depending on the outdoor temperature, for preheating.
- PreheatTiming: learns from each morning whether the room was warm in time.
- preheat_hours: how early to start so the room is warm when the night ends.
- AutoTuner: nudges Kp/Ki once a day from how the room actually behaved.
- SunProfile: how much to turn down ahead of the sun, per hour of the day.
"""

from __future__ import annotations

from dataclasses import dataclass, field

DEFAULT_HEAT_RATE = 1.0  # °C/h until the room has been measured
MAX_PREHEAT_HOURS = 6.0  # a slow room going 19 -> 22 °C at 0.75 °C/h needs ~5 h
PREHEAT_MARGIN = 1.1  # starting value of the learned preheat factor
DEFAULT_DEAD_TIME = 0.33  # h from opening the valve until the room starts to warm
MAX_DEAD_TIME = 2.0
COLD_START_HOURS = 1.0  # the valve must have been shut this long to measure the dead time
RISE_DETECT = 0.1  # °C above the lowest reading: the radiator has started to warm the room
MIN_OUTDOOR_SPREAD = 2.0  # °C (std. dev.) of outdoor temperatures before trusting the slope
MAX_SLOPE = 0.15  # (°C/h) per °C outdoor
COOL_SETTLE_HOURS = 1.0  # valve shut this long before the radiator is cold enough to measure
COOL_SPAN_HOURS = 1.0
FACTOR_MIN, FACTOR_MAX = 0.6, 2.0
LATE_TOLERANCE = 0.15  # °C short of the target at night end that counts as on time
EARLY_TOLERANCE = 0.5  # h at target before the night ended that counts as on time


@dataclass
class HeatRateLearner:
    """Measures how the room warms while the TRV is fully open.

    - dead_time: how long after the valve opens before the room starts to warm (the radiator
      and the water in it must heat up first). Only measured when the valve had been shut for
      a while, so the radiator was cold.
    - rate: how fast the room then warms (°C/h). Each measurement is also stored against the
      outdoor temperature, so cold mornings, which warm slower, can be planned for.
    - loss: how fast the room cools per °C it is warmer than outside, measured while the valve
      is shut (every night). A room that loses heat fast also warms slower when it is cold
      outside, so this gives the outdoor dependence before the weather has varied enough to
      measure it directly.
    """

    rate: float = DEFAULT_HEAT_RATE
    samples: int = 0
    alpha: float = 0.25  # weight of a new measurement
    min_span_hours: float = 0.5
    dead_time: float = DEFAULT_DEAD_TIME
    dead_samples: int = 0
    decay: float = 0.95  # weight of older measurements in the outdoor fit, per measurement
    # Exponentially weighted sums for rate vs. outdoor temperature (least squares).
    sw: float = 0.0
    sx: float = 0.0
    sy: float = 0.0
    sxx: float = 0.0
    sxy: float = 0.0
    loss: float | None = None  # (°C/h) per °C room above outdoor
    _start: tuple[float, float] | None = None
    _cool: tuple[float, float, float] | None = None  # start hours, room, closed since
    _episode: list | None = None  # [start hours, lowest room, cold radiator, warming]
    _off_since: float | None = None

    def observe(
        self, now_hours: float, room: float, full_heat: bool, outdoor: float | None = None
    ) -> None:
        if not full_heat:
            if self._off_since is None:
                self._off_since = now_hours
            self._episode = self._start = None
            return
        if self._episode is None:
            cold = self._off_since is not None and now_hours - self._off_since >= COLD_START_HOURS
            self._episode = [now_hours, room, cold, False]
            self._off_since = None
        ep = self._episode
        if not ep[3]:
            # Wait for the radiator: the room may even cool a little first.
            ep[1] = min(ep[1], room)
            waited = now_hours - ep[0]
            if room >= ep[1] + RISE_DETECT - 1e-9:
                ep[3] = True
                if ep[2]:
                    # Once warming, a 0.1 °C rise itself takes a while: don't count that.
                    self._learn_dead_time(waited - RISE_DETECT / max(self.rate, 0.2))
                self._start = (now_hours, room)
            elif waited > MAX_DEAD_TIME:
                ep[3] = True  # a radiator that never warms: don't learn a dead time from it
                self._start = (now_hours, room)
            return
        t0, r0 = self._start
        span = now_hours - t0
        if span < self.min_span_hours:
            return
        rise = room - r0
        if rise > 0.05:  # ignore spans where the sun dipped or a door stood open
            measured = min(5.0, max(0.05, rise / span))
            self.rate = measured if self.samples == 0 else (
                (1 - self.alpha) * self.rate + self.alpha * measured
            )
            self.samples += 1
            if outdoor is not None:
                self._add(outdoor, measured)
        self._start = (now_hours, room)

    def observe_cooling(
        self, now_hours: float, room: float, closed: bool, outdoor: float | None
    ) -> None:
        """Feed while the valve is (or isn't) shut, to learn how fast the room loses heat."""
        if not closed or outdoor is None:
            self._cool = None
            return
        if self._cool is None:
            self._cool = (now_hours, room, now_hours)
            return
        t0, r0, since = self._cool
        if now_hours - since < COOL_SETTLE_HOURS:
            self._cool = (now_hours, room, since)  # radiator still giving off heat
            return
        span = now_hours - t0
        if span < COOL_SPAN_HOURS:
            return
        above = (r0 + room) / 2 - outdoor
        drop = r0 - room
        if above >= 5.0 and drop > 0.05:  # sun or cooking warming the room: skip
            measured = min(0.2, drop / span / above)
            self.loss = measured if self.loss is None else 0.8 * self.loss + 0.2 * measured
        self._cool = (now_hours, room, since)

    def _learn_dead_time(self, hours: float) -> None:
        hours = min(MAX_DEAD_TIME, max(0.0, hours))
        self.dead_time = hours if self.dead_samples == 0 else 0.7 * self.dead_time + 0.3 * hours
        self.dead_samples += 1

    def _add(self, x: float, y: float) -> None:
        d = self.decay
        self.sw = self.sw * d + 1
        self.sx = self.sx * d + x
        self.sy = self.sy * d + y
        self.sxx = self.sxx * d + x * x
        self.sxy = self.sxy * d + x * y

    def rate_at(self, outdoor: float | None) -> float:
        """Expected warm-up rate at this outdoor temperature."""
        if outdoor is None or self.sw < 1:
            return self.rate
        mx, my = self.sx / self.sw, self.sy / self.sw
        var = self.sxx / self.sw - mx * mx
        if self.sw >= 3 and var >= MIN_OUTDOOR_SPREAD**2:
            slope = (self.sxy / self.sw - mx * my) / var  # measured in varied weather
        elif self.loss is not None:
            slope = self.loss  # the heat the room loses to the outside isn't warming it
        else:
            return self.rate
        slope = min(MAX_SLOPE, max(0.0, slope))
        estimate = my + slope * (outdoor - mx)
        return min(5.0, 3 * my, max(0.05, 0.3 * my, estimate))

    def to_dict(self) -> dict[str, float]:
        data = {k: round(getattr(self, k), 4) for k in ("dead_time", "sw", "sx", "sy", "sxx", "sxy")}
        return data | {
            "dead_samples": self.dead_samples,
            "loss": None if self.loss is None else round(self.loss, 5),
        }

    def load(self, data: dict) -> None:
        for key in ("dead_time", "sw", "sx", "sy", "sxx", "sxy"):
            if isinstance(data.get(key), (int, float)):
                setattr(self, key, float(data[key]))
        self.dead_samples = int(data.get("dead_samples") or 0)
        if isinstance(data.get("loss"), (int, float)):
            self.loss = float(data["loss"])


def preheat_hours(
    rate: float,
    room: float,
    day_target: float,
    dead_time: float = 0.0,
    factor: float = PREHEAT_MARGIN,
) -> float:
    """Hours of full heat needed to bring the room from now to the day target."""
    if room >= day_target:
        return 0.0
    hours = (dead_time + (day_target - room) / max(rate, 0.05)) * factor
    return min(MAX_PREHEAT_HOURS, hours)


@dataclass
class PreheatTiming:
    """Learns from each morning: start earlier if the room was late, later if it was early."""

    factor: float = PREHEAT_MARGIN
    samples: int = 0

    def learn(
        self, ran_hours: float, short_by: float, early_hours: float, rate: float
    ) -> tuple[str, float] | None:
        """After a preheat that ran ran_hours: the room was short_by °C below the target when
        the night ended, or had reached it early_hours before. Returns ("late"/"early", how
        much) when the factor changed."""
        if ran_hours < 0.25:
            return None
        if short_by > LATE_TOLERANCE:
            verdict, amount = "late", short_by
            ideal = ran_hours + short_by / max(rate, 0.05)
        elif early_hours > EARLY_TOLERANCE:
            verdict, amount = "early", early_hours
            ideal = max(0.1, ran_hours - early_hours)
        else:
            return None
        # Part of the way towards what would have been right, so one odd morning doesn't swing
        # it. A cold room is worse than a few minutes of extra heat: move faster when late.
        new = self.factor * (ideal / ran_hours) ** (0.6 if verdict == "late" else 0.3)
        new = round(min(FACTOR_MAX, max(FACTOR_MIN, new)), 3)
        if new == self.factor:
            return None
        self.factor = new
        self.samples += 1
        return verdict, amount


@dataclass
class AutoTuner:
    """Once a day: lower Kp/Ki if the room oscillated, raise Ki if it sat off target."""

    kp: float
    ki: float
    kp_min: float = 1.0
    kp_max: float = 6.0
    ki_min: float = 0.3
    ki_max: float = 3.0
    window_hours: float = 24.0
    errors: list[float] = field(default_factory=list)
    hours: float = 0.0
    last_change: str | None = None

    def observe(self, error: float, dt_hours: float, steady: bool) -> str | None:
        """Feed one control step. Returns a description when Kp/Ki changed."""
        self.hours += dt_hours
        # Only steady regulation tells us about tuning: not night/day steps, airing or a
        # radiator that can't keep up (valve fully open).
        if steady and abs(error) < 1.0:
            self.errors.append(error)
        if self.hours < self.window_hours - 1e-6:  # 288 x 5 min sums to 23.9999... h
            return None
        change = self._evaluate()
        self.errors.clear()
        self.hours = 0.0
        return change

    def _evaluate(self) -> str | None:
        e = self.errors
        if len(e) < 50:  # under ~4 h of usable data: don't guess
            return None
        mean_abs = sum(abs(x) for x in e) / len(e)
        amp = (max(e) - min(e)) / 2
        crossings = sum(
            1 for a, b in zip(e, e[1:]) if (a > 0.1 and b < -0.1) or (a < -0.1 and b > 0.1)
        )
        old = (self.kp, self.ki)
        if crossings >= 6 and amp > 0.3:
            self.kp = max(self.kp_min, round(self.kp * 0.85, 2))
            self.ki = max(self.ki_min, round(self.ki * 0.9, 2))
            why = "svingede"
        elif mean_abs > 0.12:
            # Typically off target without swinging back and forth: react harder.
            self.kp = min(self.kp_max, round(self.kp * 1.15, 2))
            self.ki = min(self.ki_max, round(self.ki * 1.2, 2))
            why = "lå for langt fra målet"
        else:
            return None
        if (self.kp, self.ki) == old:
            return None
        self.last_change = f"Rummet {why}: Kp {old[0]} → {self.kp}, Ki {old[1]} → {self.ki}"
        return self.last_change


SUN_LEAD_HOURS = 0.5  # turn down this long before the sun's heat shows: the radiator lags
SUN_RATE = 0.6  # °C of reduction learned per °C·h the room sat over target in the sun
SUN_MAX = 3.0
SUN_DEADBAND = 0.1  # °C: closer than this to the target teaches nothing


@dataclass
class SunProfile:
    """How much to turn the TRV down at each hour of the day when the sun shines.

    Learned from sunny hours, iteratively: if the room still went over target at 15:00, turn
    down more from 14:00 next sunny day; if it then fell under target, turn down less. It
    settles where the room stays on target, so it doesn't swing from one day to the next.
    """

    bins: list[float] = field(default_factory=lambda: [0.0] * 24)

    def _weights(self, hour: float) -> tuple[int, int, float]:
        hour %= 24
        low = int(hour) % 24
        return low, (low + 1) % 24, hour - int(hour)

    def at(self, hour: float) -> float:
        """The learned reduction for the sun's effect at this local hour (0-24)."""
        low, high, frac = self._weights(hour)
        return self.bins[low] * (1 - frac) + self.bins[high] * frac

    def reduction(self, hour: float, sun: float) -> float:
        """°C to take off the TRV setpoint now, given how sunny it is (0-1)."""
        return round(sun * self.at(hour + SUN_LEAD_HOURS), 2) if sun > 0 else 0.0

    def learn(
        self, hour: float, above: float, sun: float, dt_hours: float, can_cut: bool = True
    ) -> None:
        """Feed a steady control step: the room is `above` °C over its target now.

        sun and can_cut describe the step SUN_LEAD_HOURS ago, whose reduction shows now: how
        sunny it was then, and whether the TRV could still be turned down (not already shut).
        Turning down more than shut teaches nothing, and would only wind the profile up.
        """
        if sun <= 0 or dt_hours <= 0 or abs(above) < SUN_DEADBAND or (above > 0 and not can_cut):
            return
        step = SUN_RATE * sun * max(-0.5, min(0.5, above)) * dt_hours
        low, high, frac = self._weights(hour)
        for idx, weight in ((low, 1 - frac), (high, frac)):
            self.bins[idx] = round(min(SUN_MAX, max(0.0, self.bins[idx] + step * weight)), 4)

    def load(self, data: object) -> None:
        if isinstance(data, list) and len(data) == 24:
            self.bins = [float(v) for v in data]
