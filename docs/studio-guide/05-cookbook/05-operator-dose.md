# Recipe 5 — Ask the operator for a dose at start

**Goal:** ask the person running the experiment how much to dispense, then use their answer
as the dispense volume. The same workflow can run at different doses without editing it.

**Blocks used:** [Operator input](../04-blocks/pause.md) ·
[Command](../04-blocks/device-actions.md) (dispense, with an expression parameter).

**Roles:** `drug_pump` (pump).

## Build it

1. Create a [role](../03-concepts/roles.md) `drug_pump` (pump).
2. From the Palette under **Pause**, drag an **[Operator input](../04-blocks/pause.md)** onto
   the canvas. Set:
   - **Binding name:** `dose_ml`
   - **Type:** `float`
   - **Min:** `0`, **Max:** `10`
   - **Prompt:** `Drug dose this run (ml)?`
3. Drag the **`dispense`** verb of `drug_pump` below it. On the **volume_ml** field, click the
   small **ƒ** toggle to switch it to an [expression](../03-concepts/expressions.md), and
   enter `dose_ml`.
4. Save and run. At the start, Studio asks for the dose; the pump then dispenses exactly that.

![](../images/cb-05-operator-dose.png)
> *Screenshot: Operator input (dose_ml) above a dispense whose volume_ml field is in
> expression mode showing `dose_ml`.*

## Why it's built this way

The operator's answer becomes a [binding](../03-concepts/bindings-and-constants.md) named
`dose_ml`, and the **ƒ** toggle lets a device parameter read that binding instead of a fixed
number. This is the general trick for making a workflow **parameterized**: capture a value
once (from a person or a [Compute](../04-blocks/data.md)), then reference it wherever it's
needed. The **Min/Max** guard rails stop an accidental huge dose.

**Next:** [Recipe 6 — run three vials in parallel](06-parallel-vials.md).
