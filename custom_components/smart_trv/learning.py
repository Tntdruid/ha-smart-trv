"""What Smart TRV learns about each room. No Home Assistant imports, so it can be simulated.

- HeatRateLearner: how fast the room warms at full heat (°C/h), for preheating.
- preheat_hours: how early to start so the room is warm when the night ends.
- AutoTuner: nudges Kp/Ki once a day from how the room actually behaved.
"""

from __future__ import annotations

from dataclasses import dataclass, field

DEFAULT_HEAT_RATE = 1.0  # °C/h until the room has been measured
MAX_PREHEAT_HOURS = 6.0  # a slow room going 19 -> 22 °C at 0.75 °C/h needs ~5 h
PREHEAT_MARGIN = 1.2  # start 20 % earlier than the bare estimate


@dataclass
class HeatRateLearner:
    """Measures the room's warm-up speed while the TRV is fully open."""

    rate: float = DEFAULT_HEAT_RATE
    samples: int = 0
    alpha: float = 0.25  # weight of a new measurement
    min_span_hours: float = 0.5
    _start: tuple[float, float] | None = None

    def observe(self, now_hours: float, room: float, full_heat: bool) -> None:
        if not full_heat:
            self._start = None
            return
        if self._start is None:
            self._start = (now_hours, room)
            return
        t0, r0 = self._start
        span = now_hours - t0
        if span < self.min_span_hours:
            return
        rise = room - r0
        if rise > 0.05:  # ignore spans where the radiator was still warming up or the sun dipped
            measured = min(5.0, max(0.05, rise / span))
            self.rate = measured if self.samples == 0 else (
                (1 - self.alpha) * self.rate + self.alpha * measured
            )
            self.samples += 1
        self._start = (now_hours, room)


def preheat_hours(rate: float, room: float, day_target: float) -> float:
    """Hours of full heat needed to bring the room from now to the day target."""
    if room >= day_target:
        return 0.0
    return min(MAX_PREHEAT_HOURS, (day_target - room) / max(rate, 0.05) * PREHEAT_MARGIN)


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
