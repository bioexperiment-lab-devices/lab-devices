# Quickstart A — your first run, no lab needed

This walkthrough builds a tiny workflow that uses **no devices**, then runs it. By the end
you'll have seen the whole loop: **build → save → run → look at the results**. Because there's
no hardware, nothing can go wrong — it's the safest way to learn how Studio feels.

**What we'll build:** ask the operator for a dose, calculate a total from it, log that total,
wait a moment, and flag a warning if the number is unreasonable.

**You'll learn:** dragging blocks, editing settings in the Inspector, saving, starting a run
with no devices, answering an operator prompt, and opening the run record.

---

## 1. Start a new experiment

1. Open the **Builder** tab.
2. In the toolbar, click **New** (if a workflow is already open).
3. Type a name in the name field, e.g. `First run`.

![](../images/qs-a-new.png)
> *Screenshot: the Builder toolbar with the name field showing "First run" and the empty
> canvas below.*

---

## 2. Ask the operator for a number

1. From the **Palette**, under **Pause**, drag an **Operator input** chip onto the canvas.
2. Click the new block to open its Inspector, and set:
   - **Binding name:** `dose_ml`
   - **Type:** `float`
   - **Min:** `0`, **Max:** `50`
   - **Prompt:** `How many ml per dose?`

This will pause the run and ask the operator; their answer is stored as `dose_ml`. (See
[Operator input](../04-blocks/pause.md) and [bindings](../03-concepts/bindings-and-constants.md).)

![](../images/qs-a-operator-input.png)
> *Screenshot: the Operator input block on the canvas, Inspector filled in as above.*

---

## 3. Calculate a total

1. From the Palette, under **Data**, drag a **Compute** chip onto the canvas, **below** the
   Operator input.
2. In its Inspector, set:
   - **Into (binding):** `total_ml`
   - **Value:** `dose_ml * 3`

As you type `dose_ml`, notice the [expression](../03-concepts/expressions.md) editor
suggesting the name you just created.

---

## 4. Log the total to a stream

1. From the Palette, under **Data**, drag a **Record** chip onto the canvas, below Compute.
2. In its Inspector:
   - **Into stream:** click the picker and choose **new stream**, name it `doses`, unit `ml`.
   - **Value:** `total_ml`

Now every time this block runs it appends `total_ml` to the `doses`
[stream](../03-concepts/streams.md).

---

## 5. Add a short wait and a safety flag

1. From the Palette, under **Pause**, drag a **Wait** below Record. Set **Duration:** `2s`.
2. From the Palette, under **Safety**, drag an **Alarm** below Wait. Set:
   - **If:** `total_ml > 100`
   - **Message:** `Dose looks too high — check with the operator`

The [Alarm](../04-blocks/safety.md) records a warning if the total is unreasonable, but lets
the run finish.

![](../images/qs-a-finished-canvas.png)
> *Screenshot: the finished canvas — Operator input, Compute, Record, Wait, Alarm stacked in
> a Serial. The validation chip reads "valid".*

---

## 6. Save

Click **Save** in the toolbar. If prompted, confirm the name. The unsaved **●** dot next to
the name disappears once it's saved.

---

## 7. Run it

1. Switch to the **Run** tab.
2. Select your `First run` experiment if asked.
3. There are **no roles to map** (no devices), so you can **start the run** straight away.
4. When the run reaches the Operator input, it **pauses and asks** *"How many ml per dose?"*.
   Type a number — try `2` — and submit.

![](../images/qs-a-operator-prompt.png)
> *Screenshot: the run's operator prompt dialog asking "How many ml per dose?" with a number
> entered.*

The run continues: Compute works out `total_ml`, Record logs it, Wait pauses two seconds, and
the Alarm checks the condition. Watch the event log update as each block runs.

> **Try it:** run again and enter `40`. `total_ml` becomes `120`, the Alarm condition
> `total_ml > 100` is true, and you'll see the warning flagged — while the run still finishes.

---

## 8. Look at the record

1. When the run ends, switch to the **Records** tab.
2. Open the run you just finished.
3. You'll see the run's outcome, the `doses` stream with your logged value, and any alarm
   that fired.

![](../images/qs-a-record.png)
> *Screenshot: the Records tab with the finished run open, showing the `doses` stream value
> and the alarm (if `40` was entered).*

---

## What you learned

You built a workflow from blocks, set their options in the Inspector, saved it, ran it,
answered a prompt, and read the results — the entire Studio loop, with no hardware.

**Next:** do [Quickstart B](b-pump-densitometer.md) to run a real experiment with a pump and a
densitometer, including mapping roles to devices.
