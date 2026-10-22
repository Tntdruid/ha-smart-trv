"""A slower room, closer to the living-room graph: cold nights, an aired window at 11:15.

Run:  python tests/simulate_stue.py
"""

import math

from simulate import STEP, TARGET, PIController, snap

DAYS = 3
WINDOW = (11 * 60 + 15, 11 * 60 + 30)  # window open 11:15-11:30


def outdoor(minute):
    # 2 °C at 05:00, 10 °C at 17:00
    return 6 - 4 * math.cos(2 * math.pi * ((minute / 60 - 5) % 24) / 24)


def run(strategy, ki=1.0, kp=3.0):
    room, rad = 21.5, 0.5
    pi = PIController(kp=kp, ki=ki, max_boost=6.0, max_cut=3.0, step=STEP)
    pi.seed(room + 0.5, room)
    setpoint, hist = TARGET, []
    for minute in range(DAYS * 24 * 60):
        tod = minute % (24 * 60)
        window = WINDOW[0] <= tod < WINDOW[1]
        trv_local = room + 0.5 + 2.5 * rad
        if minute % 5 == 0:
            if strategy == "bt":
                setpoint = snap(TARGET + (trv_local - room))
            elif window:
                pass  # Smart TRV turns the TRVs off and freezes the integral
            else:
                setpoint = pi.update(TARGET, room, 5 / 60 if minute else 0, trv_local)
        valve = 0.0 if window and strategy == "pi" else max(0.0, min(1.0, (setpoint - trv_local) / 0.5))
        rad += (valve - rad) / 20
        loss = 0.12 * (10 if window else 1)
        room += (3.0 * rad - loss * (room - outdoor(minute))) / 60
        hist.append((minute, room))
    return hist


def summary(name, hist):
    day = [(m % 1440, r) for m, r in hist if m >= (DAYS - 1) * 1440]
    normal = [r for t, r in day if not (WINDOW[0] <= t < WINDOW[1] + 180)]
    after = next((t for t, r in day if t > WINDOW[1] and r >= TARGET - 0.1), None)
    rec = f"{(after - WINDOW[1]) / 60:.1f} h" if after else "never"
    print(f"{name:<24} day avg {sum(normal)/len(normal):.2f}  min/max {min(normal):.2f}/{max(normal):.2f}  "
          f"back within 0.1 °C after window: {rec}")


if __name__ == "__main__":
    summary("Better Thermostat-ish", run("bt"))
    for ki in (0.5, 1.0, 2.0):
        summary(f"Smart TRV Ki={ki}", run("pi", ki=ki))
