"""PI controller that turns a room target into a TRV setpoint.

Kept free of Home Assistant imports so it can be tested on its own.

Why PI: the usual fix for a TRV that reads the hot radiator shifts its setpoint by
the measured difference between the TRV sensor and the room sensor. That is a
proportional correction, and a proportional-only loop always settles with a
remaining error -- typically the 0.5 °C you see. The integral term keeps
pushing the TRV setpoint up for as long as the room is below target, so the
remaining error goes to zero.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class PIController:
    kp: float
    ki: float
    max_boost: float
    max_cut: float
    step: float = 0.5
    min_temp: float = 5.0
    max_temp: float = 30.0
    # Big errors (after airing, a new target) are P's job; integrating them at full
    # weight winds up and overshoots hours later. They count as at most this much.
    integral_band: float = 0.3
    # Without a valve position from the TRV: when the TRV setpoint is this far from what the
    # TRV itself measures, its valve is taken as fully open (or closed). Moving the setpoint
    # further changes nothing, so don't learn from it: that's how a cold radiator at night
    # winds up the integral. 1 °C was too tight for lukewarm radiators with a TRV that opens
    # gradually: the integral froze and the room stayed under target.
    valve_margin: float = 2.0
    # Keep the last setpoint until the new one is at least this far away. Without it, sensor
    # noise flips the setpoint between two steps and the TRV motor runs every few minutes.
    hysteresis: float = 0.0
    integral: float = 0.0
    error: float = 0.0
    valve_saturated: bool = False
    output: float | None = None

    def seed(self, trv_temp: float | None, room_temp: float) -> None:
        """Start the integral at the TRV/room sensor difference (the usual offset correction)."""
        if trv_temp is None:
            return
        # A TRV on a radiator never really reads colder than the room; if it does, it's a
        # leftover local_temperature_calibration offset and not something to learn from.
        self.integral = self._clamp(trv_temp - room_temp, 0.0, self.max_boost)

    def update(
        self,
        target: float,
        room_temp: float,
        dt_hours: float,
        trv_temp: float | None = None,
        feedforward: float = 0.0,
        valve_position: float | None = None,
    ) -> float:
        """Return the TRV setpoint, rounded to the TRV's step.

        feedforward: extra offset known in advance (outdoor compensation), so the integral
        only has to learn what is left.
        """
        self.error = target - room_temp
        p = self.kp * self.error

        self.valve_saturated = False
        if valve_position is not None:
            # The TRV says how open it is (TRV602): trust it over any guess.
            self.valve_saturated = (valve_position >= 95 and self.error > 0) or (
                valve_position <= 5 and self.error < 0
            )
        elif trv_temp is not None:
            current = target + p + self.integral + feedforward
            self.valve_saturated = (
                current - trv_temp >= self.valve_margin and self.error > 0
            ) or (trv_temp - current >= self.valve_margin and self.error < 0)

        if dt_hours > 0 and not self.valve_saturated:
            learn = self._clamp(self.error, -self.integral_band, self.integral_band)
            candidate = self._clamp(
                self.integral + self.ki * learn * dt_hours,
                -self.max_cut,
                self.max_boost,
            )
            # Anti-windup: don't grow the integral while the output is already saturated.
            unsat = p + candidate + feedforward
            saturated_high = unsat > self.max_boost and self.error > 0
            saturated_low = unsat < -self.max_cut and self.error < 0
            if not (saturated_high or saturated_low):
                self.integral = candidate

        offset = self._clamp(p + self.integral + feedforward, -self.max_cut, self.max_boost)
        setpoint = self._clamp(target + offset, self.min_temp, self.max_temp)
        if self.output is None or abs(setpoint - self.output) >= self.hysteresis:
            self.output = round(round(setpoint / self.step) * self.step, 2)
        return self.output

    @staticmethod
    def _clamp(value: float, low: float, high: float) -> float:
        return max(low, min(high, value))
