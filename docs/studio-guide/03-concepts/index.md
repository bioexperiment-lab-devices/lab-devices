# Concepts

Every workflow you build is made of four ideas. Once these click, the whole Builder makes
sense. Read them in order — later pages assume the earlier ones.

| Concept | In one line | Think of it as |
|---------|-------------|----------------|
| **[Roles](roles.md)** | A labeled slot for a device. | "The pump that adds medium." |
| **[Streams](streams.md)** | A named series of numbers collected over the run. | A column in a lab notebook that grows one row per reading. |
| **[Bindings & constants](bindings-and-constants.md)** | A single named value. | A sticky note that says `dose_ml = 2`. |
| **[Expressions](expressions.md)** | How you compute and decide from all of the above. | The little formulas you'd write on that notebook. |

## How they fit together

- You design the experiment with **roles** instead of specific devices, so the same
  workflow runs on any matching hardware. You pick the real devices right before you run.
- Devices produce readings, which you collect into **streams** (many numbers over time).
- You capture single values — an operator's answer, a computed target — as **bindings** and
  **constants** (one number each).
- You use **expressions** everywhere a decision or a calculated value is needed: "repeat
  until the average OD is above 0.6", "dilute if the last reading is over 0.5".

Keep this page handy as a glossary while you read the rest of the guide.
