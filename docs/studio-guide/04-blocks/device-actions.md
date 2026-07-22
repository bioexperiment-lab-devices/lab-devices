# Device actions — Command & Measure

Device actions are the steps that actually **talk to a device**: dispense liquid, take a
reading, set a temperature. There are two kinds, **Command** and **Measure**, and both are
created the same way — by dragging a **verb chip** from a [role](../03-concepts/roles.md).

> **How to add one:** select a role in the Roles panel, then drag one of its verb chips
> (*dispense*, *measure*, …) onto the canvas. Studio creates a Command or a Measure block
> already pointed at that role.

The available verbs come from the device's **type**. There are three types, and each offers
a fixed set of verbs (listed below). Numeric and yes/no parameters can take a fixed value
**or** an [expression](../03-concepts/expressions.md) — click the small **ƒ** toggle on the
field to switch to expression mode.

---

## Command

**What it does** — tells a device to do something (dispense, move, set the thermostat).

**When to use it** — any time you act on hardware without capturing a reading into a stream.

![](../images/block-command.png)
> *Screenshot: a Command block selected — a pump `dispense` — with the Inspector showing
> Role, Verb, and the volume/speed/direction parameters.*

**Settings**

- **Role** — which device to command (only roles of the matching type are offered).
- **Verb** — what to do. The choices depend on the device type:

  | Type | Command verbs |
  |------|---------------|
  | **pump** | `dispense`, `rotate`, `stop`, `set_calibration` |
  | **valve** | `set_position`, `home`, `configure`, `stop` |
  | **densitometer** | `set_led`, `set_thermostat`, `set_tube_correction`, `calibrate_tube`, `stop`, `stop_monitoring` |

- **Params** — the settings for the chosen verb, generated automatically. Some are required,
  some are dropdowns (a closed set of choices), some have sensible defaults. Common ones:
  - `dispense` → **volume_ml** (required), **speed_ml_min**, **direction** (`forward` /
    `reverse`), **drop_suckback_ml**.
  - `rotate` → **direction** (required), **speed_ml_min** (required).
  - `set_position` → **position** (required, whole number), **rotation** (`shortest` /
    `direct` / `wrap`).
  - `set_thermostat` → **enabled** (required, yes/no), **target_c** (temperature).
  - `set_led` → **level** (required, 0–255).

<details><summary>Details &amp; gotchas</summary>

- **Modes.** A few verbs turn something *on* until it's turned off — `set_thermostat`,
  `set_led`, `rotate` (continuous pumping). Studio treats these as "modes" and makes sure
  they're closed safely when the run ends. You don't have to add the closing step yourself.
- **`stop` is the safe primitive.** Every actuating device has a `stop`. It always succeeds
  and is the thing to reach for when you want a device idle.
- **Absolute vs. relative.** `set_position`, `home`, `set_led`, `set_thermostat` are
  *absolute* — asking for the same value twice lands the device in the same place.
  `dispense` and `rotate` are *relative* — running them twice doses twice. This is why
  retrying them needs an explicit opt-in (see Retry, below).
</details>

---

## Measure

**What it does** — takes a **reading** from a device and stores it in a
[stream](../03-concepts/streams.md).

**When to use it** — whenever you want to record data: OD over time, temperature, a blank.

![](../images/block-measure.png)
> *Screenshot: a Measure block selected — a densitometer `measure` — with the Inspector
> showing Role, Verb, params, and the "Into stream" picker.*

**Settings**

- **Role** — which device to read (only densitometers have measure verbs).
- **Verb** — what to read:

  | Verb | Reads |
  |------|-------|
  | `measure` | optical density / absorbance (OD). Optional **include_raw** (yes/no). |
  | `measure_blank` | the blank baseline (slope). |
  | `read_temperature` | the current temperature in °C. |

- **Params** — any settings the verb needs (e.g. `measure`'s **include_raw**).
- **Into stream** — the [stream](../03-concepts/streams.md) this reading is appended to. Pick
  an existing stream, or create one inline right from the picker.

<details><summary>Details &amp; gotchas</summary>

- **Only the densitometer measures.** Pumps and valves are command-only — they have no
  Measure verbs.
- **`read_temperature` is independent.** It reads the temperature without running the optics
  or LED, so it works even while the thermostat is on and even between OD readings.
- Each Measure adds **one** sample per run. Put it inside a [Loop](flow.md) to build up a
  series.
</details>

---

## Retry — riding out a flaky device

Both Command and Measure blocks have a **Retry** option under **On failure** (device actions
are the only blocks that do). It automatically re-tries a device call that fails.

![](../images/block-retry.png)
> *Screenshot: the Retry section of a Command Inspector for a `dispense` verb, showing the
> amber "allow repeat" hazard box with the Attempts and Backoff fields.*

**Settings**

- **retry on failure** — the checkbox that turns retry on.
- **Attempts** — the **total** number of tries, including the first (so `2` means "try once
  more if the first fails").
- **Backoff** — an optional pause before each retry, a [duration](../03-concepts/expressions.md)
  like `2s`.

<details><summary>Details &amp; gotchas — why some verbs warn you</summary>

Retry is safe for **reads** and **absolute** actions — reading OD twice, or setting the same
position twice, does no harm. It is **dangerous** for **relative** actions:

- **`dispense`**, **`rotate`**, and **`calibrate_tube`** are *not* safe to retry
  automatically. Retrying a half-finished dispense can deliver a **second dose** on top of
  what already went in — a silent double-dose of your culture.

So when you turn on Retry for one of these verbs, Studio shows an **amber hazard box** and
hides Attempts/Backoff until you tick **allow repeat**, confirming you understand the risk.
`allow_repeat` is not a safety feature — it's you taking responsibility for a repeat.

**Rule of thumb:** tolerate and retry **reads** freely; think hard before retrying anything
that moves liquid.
</details>

---

**Related:** [Roles](../03-concepts/roles.md) · [Streams](../03-concepts/streams.md) · [Safety blocks](safety.md)
