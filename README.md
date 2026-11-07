<img src="custom_components/smart_trv/brand/icon@2x.png" alt="Smart TRV" width="128" align="right">

# Smart TRV (PI) – Home Assistant

🇬🇧 English · 🇩🇰 [Dansk](README.da.md)

Controls radiator thermostats (Tuya **TV02** and **TRV602** via Zigbee2MQTT, and any other TRV that is a `climate` entity) from a **room sensor** with a PI controller, so the room actually reaches its target.

## Why a TRV misses the target

A TRV measures the temperature right next to the hot radiator, so it thinks the room is warmer than it is. The usual fix is to add the difference between the TRV sensor and the room sensor to the setpoint. That is a purely proportional correction, and a P controller always settles with a remaining error: the valve has to stay a little open to keep the room warm, which needs the room to be a little *below* target. With the TV02's 0.5 °C steps it typically lands on 21.5 °C when the target is 22.

Smart TRV adds an **integral term**: as long as the room is below target, it slowly pushes the TRV setpoint up until the error is 0.

With offset-only correction the error grows with heat demand. It is largest at night, when it is coldest outside and the radiator has to give the most.

Simulation of a slow living room with cold nights and a window opened 11:15–11:30 (`python tests/simulate_stue.py`), target 22 °C:

| | Day (excluding airing) |
|---|---|
| Offset correction only (P) | 21.39–22.01 °C |
| Smart TRV (PI) | 21.88–22.22 °C |

TRVs are controlled with a setpoint, not a valve opening in %. If the valve is already fully open, the integral stops learning, because a higher setpoint changes nothing. If the TRV reports its own valve opening (the TRV602's `position`), Smart TRV uses it: 95 % or more is fully open, 5 % or less is closed. Otherwise it treats the valve as fully open when the setpoint is at least 2 °C above what the TRV itself measures. With lukewarm radiators (district heating) the TRV reads only about 1 °C above the room even while heating, so a 1 °C limit froze the integral and kept the room under target (`python tests/simulate_lukewarm.py`). This stops a cold radiator at night from "pumping up" the learned offset, which would overheat the room when the sun comes out. If the valve has been fully open for more than 2 hours without the TRV getting warmer, the explanation says the radiator isn't getting hot.

The integral learns from at most 0.3 °C of error at a time. Large errors, e.g. after airing, are handled by the P term, so the integral doesn't wind up and overshoot in the afternoon.

## Supported TRVs

Any TRV that is a `climate` entity in Home Assistant with a setpoint and its own temperature reading. Tested with:

| | Off when a window opens | "Heating" status | Note |
|---|---|---|---|
| Tuya **TV02** | `hvac_mode: off` | guessed from setpoint and the TRV's reading | 0.5 °C steps only |
| Tuya **TRV602** | preset `off` (it has no hvac off) | from the TRV's `running_state` | in Z2M: set **`max_temperature` to 35 °C** (otherwise it refuses Smart TRV's setpoints above its max and never heats), and `mode` to **comfort** (`eco` only opens/closes fully) |

If a TRV has neither hvac off nor preset off, Smart TRV sets it to its lowest setpoint while the window is open.

If a TRV doesn't accept the setpoint Smart TRV sends (it still shows a lower value after 10 minutes), the explanation shows a ⚠️ warning.

## Installation

**With HACS or the Marketplace (recommended):** In Home Assistant 2026.11+ HACS is built in under **Settings → Marketplace**.

1. HACS/Marketplace → ⋮ → **Custom repositories** → add `https://github.com/Tntdruid/ha-smart-trv`, category **Integration**. (Once Smart TRV is in the official catalog you can skip this and just search.)
2. Search for **Smart TRV (PI)** → **Download**.
3. Restart Home Assistant.
4. **Settings → Devices & services → Add integration → "Smart TRV (PI)"**.

HACS tells you when a new version is out.

**Manually:** Copy `custom_components/smart_trv` to `/config/custom_components/smart_trv` and restart Home Assistant.

During setup you pick the room sensor, one or more TRVs and optionally window sensors.

Before you start:

- **Turn off any other control of the room's TRVs**, e.g. other thermostat integrations or automations that set the TRV temperature. Otherwise they fight over it.
- **Set `local_temperature_calibration` to 0** on the TRVs in Zigbee2MQTT. An old offset from earlier control does no harm, but the controller then starts from a known point.
- The integration puts the TRVs in preset `manual` itself, so their internal weekly schedule doesn't override the setpoint.

Use the new `climate.<name>` entity in your dashboards and automations instead of the TRV itself.

## Settings

You only choose what describes the house: room sensor, TRVs, windows/doors with delays, night schedule, outdoor sensor and preheat on/off. Then you set the target, e.g. 22 °C, and Smart TRV does the rest:

| What | How |
|---|---|
| Kp and Ki | Tune themselves once a day (see `kp`, `ki` and `last_tuning` on the climate entity) |
| TRV step | Read from the TRV (`target_temp_step`), otherwise 0.5 °C |
| Max boost / cut | Fixed 6 °C above and 3 °C below the target |
| Interval | Fixed 5 min. New readings show immediately, but the TRV only gets a new setpoint at a control run, and only when it has moved at least one TRV step. That keeps the motor quiet: about 20 changes a day instead of hundreds (`python tests/simulate_chatter.py`) |

The collapsed **Advanced** section lets you turn tuning off and change the starting values for Kp/Ki and the strength of the outdoor compensation. You don't need to.

## Windows and doors

Choose window and door sensors under **Configure**. Smart TRV then turns the TRVs off while something is open, and learning pauses meanwhile. Two delays per room:

| Field | Default | Meaning |
|---|---|---|
| Turn off after open | 60 s | How long it must be open before the TRVs turn off. Walking through a door doesn't turn the heating off |
| Back on after closed | 0 s | How long it must be closed before heating resumes |

While a delay runs, the explanation shows e.g. "🪟 Window/door open: turning off in 45 s". A window already open when Home Assistant starts turns the TRVs off at once.

## Night temperature per room

1. Create a schedule in Home Assistant (Settings → Devices & services → Helpers → Schedule), e.g. `schedule.night_heating`, that is **on at night**. Several rooms can share one schedule.
2. On the room: **Configure → Night schedule** → choose the schedule. An `input_boolean` or `binary_sensor` works too.
3. Set the **Night temperature** (`number.<room>_night_temperature`) on the device page or the dashboard. Each room has its own.

While the schedule is on, the room follows its night temperature and the explanation starts with 🌙. The thermostat card always shows the current target: turning it at night changes the night temperature, during the day the day temperature. Switching between day and night doesn't teach the integral anything wrong, because the valve is fully closed or fully open while the room changes temperature.

## The Smart TRV card

The integration has its own dashboard card and loads it itself. You don't need to add a resource.

Edit dashboard → **Add card** → search **"Smart TRV"** → choose the room. Or in YAML:

```yaml
type: custom:smart-trv-card
entity: climate.living_room_heating
show_graph: true        # 24 h graph of room vs. target
show_stats: true        # the four numbers
show_explanation: true  # the explanation
show_warnings: true     # ⚠️ warnings
show_night: true        # night temperature
```

All five can be switched on and off in the card settings. With all off you get a compact card with name, status, room temperature and target with −/+, which suits a "whole house" view. A hidden warning shows as ⚠️ on the status chip.

The card shows:
- Room temperature and target with −/+ (it waits until you stop clicking before sending)
- Status (Heating, Valve closed, Window open, 🌙 night) and on/off
- TRV setpoint, what the TRV reads, learned offset and error
- The explanation in one sentence, with ⚠️ warnings highlighted
- Night temperature with −/+

Click a value to see its history. The card finds the room's sensors itself, so you only choose the climate entity.

**Does the card show "Configuration error", or spin in the card picker?** Then auto-loading didn't take effect. Add the card as a resource (Settings → Dashboards → ⋮ → Resources → Add, type *JavaScript module*): `/smart_trv/smart-trv-card.js`. The integration serves the file itself, so it always follows updates.

Preview without Home Assistant: run `python -m http.server` in the repository and open `http://localhost:8000/tests/card_preview.html`.

## Preheat

If the room uses a **schedule** as its night schedule, Smart TRV starts heating early enough that the room *is* at day temperature when the night ends (the schedule's `next_event`). It preheats at most 6 hours ahead. Meanwhile the explanation shows "☀️ Preheating: the room should be 22.0 °C at 06:00". Can be turned off under Configure → *Preheat before the night ends*.

It learns three things about each room, all by itself:

- **Radiator warm-up time:** how long from the valve opening until the room starts to warm (the radiator and its water must heat up first). Measured each time the valve opens after being shut for an hour or more. Starts at 20 min.
- **Warm-up rate and the weather:** how fast the room then warms (°C/h), and how much slower it goes when it is cold outside. With an outdoor sensor it measures how fast the room cools at night with the valve shut. A room that loses heat fast also warms slower on a cold morning, so it starts earlier when it is cold and later when it is mild. Once it has warmed up in different weather, it uses those measurements directly.
- **Each morning's result:** if the room was short of the target when the night ended, it starts earlier next time. If it was warm more than 30 minutes early, it starts a little later. Mornings with an open window or a shower teach it nothing.

The climate entity shows what it has learned: `heat_rate`, `preheat_lead_minutes` (radiator warm-up), `preheat_factor` (the morning correction) and `last_preheat` (what the last morning taught it).

Simulation (`python tests/simulate_preheat.py`) of 5 × 3 weeks with the weather changing day to day and a slow radiator, the last 14 mornings of each:

| | Late mornings | Worst | Warm too early (average) |
|---|---|---|---|
| Before (one rate, +20 %) | 8 of 70 | 1.0 °C short | 32 min |
| Now | 4 of 70 | 0.3 °C short | 15 min |

## Outdoor temperature

Choose an outdoor sensor under Configure. Smart TRV then adds `0.1 × (target − outdoor)` to the TRV setpoint and reacts to cold nights *before* the room cools down; the learned offset handles the rest. In the simulation the swing on a normal day halves (21.75–22.24 → 21.89–22.13 °C). Adding the outdoor sensor to a room that has already learned subtracts the compensation from what it learned, so the setpoint doesn't jump.

## TRV monitoring

`binary_sensor.<room>_problem` turns on when a TRV is **offline**, hasn't reported for **6 hours**, or has **less than 20 % battery**. The battery sensor is found through the TRV's device. The problem also shows as ⚠️ in the explanation, and the **Whole house** view of the dashboard template lists all rooms and their problems. Use the sensor in an automation for a notification.

## Valve that doesn't close

If Smart TRV has told the TRV to close for more than 2 hours, but the TRV still reads at least 1 °C above the room and hasn't cooled at least 0.5 °C, the radiator is still hot. The explanation then warns that the valve doesn't fully close (e.g. adapter height or set screw, or the TRV's valve calibration). A sunny day doesn't trigger it, because then the TRV isn't noticeably warmer than the room.

## Showers and cooking

If the room temperature rises 0.6 °C or more within 15 minutes, or humidity 8 percentage points or more, it's a shower, cooking or similar, not the radiator. Smart TRV then pauses learning for 60 minutes so a shower doesn't drag the learned offset down; control carries on as normal. The humidity sensor is found automatically on the same device as the room sensor (e.g. an SHT4x). The explanation shows "🚿 … learning paused until 08:15".

## Auto-tuning

Once a day Smart TRV looks at how the room behaved while regulating calmly. Morning warm-up, airing and a fully open valve don't count.
- If the room oscillated: Kp −15 % and Ki −10 %.
- If it typically sat more than 0.12 °C from target without oscillating: Kp +15 % and Ki +20 %.
- Otherwise: no change.

Limits: Kp 1–6 and Ki 0.3–3. The climate entity shows the current `kp`, `ki` and `last_tuning`. If you change Kp/Ki yourself under Configure, tuning starts over from your values. Can be turned off under *Auto-tune Kp/Ki*.

## See what it is doing

The integration creates sensors you can graph (example for a room named "Living room"):

| Sensor | Shows |
|---|---|
| `sensor.living_room_status` | Heating / Valve closed / Window open / Off / No room reading. The `explanation` attribute says in one sentence what it is doing and why |
| `sensor.living_room_trv_setpoint` | What the TRV has been told |
| `sensor.living_room_trv_temperature` | What the TRV itself measures (each TRV as an attribute) |
| `sensor.living_room_error` | Target minus room temperature |
| `sensor.living_room_p_term` | The direct reaction to the error |
| `sensor.living_room_integral` | The learned offset. When it levels out, it has learned the room |
| `binary_sensor.living_room_problem` | TRV offline, silent or low battery |

**A ready dashboard that finds your entities itself:**

1. Open **Developer tools → Template**, clear the left side, and paste all of [dashboard/generate_dashboard.jinja](dashboard/generate_dashboard.jinja).
2. Copy the result on the right.
3. Create a new dashboard → ✏️ Edit → ⋮ → *Raw configuration editor*, and paste it.

You get a "Whole house" view plus one view per Smart TRV room, whatever you called them. Each room view shows the explanation, graphs of room/target, TRV and controller, and a logbook of what it did. Run the template again after adding rooms. It follows Home Assistant's language (Danish or English); set `lang` at the top to force one.

The service `smart_trv.reset_integral` resets the learned offset, e.g. after moving the room sensor. The learned offset, Kp/Ki and warm-up rate survive restarts.

**Languages:** settings, entity names, status, the card, the explanation and the dashboard template follow Home Assistant's language (Danish or English).

## Development

Tests run against Home Assistant with `pytest-homeassistant-custom-component` (`pytest`), and the simulations in `tests/simulate_*.py` model rooms, radiators and TRVs. GitHub Actions run HACS validation, hassfest and the tests on every push.
