# Verifying a notebook live

`marimo check` executes nothing, and an executed export runs every cell once from a fixed
widget default. Neither can show that a control change reaches its consumers, and neither can
show stale state left behind by a previous change. A live session is the only instrument for
those questions — and it is where the defects static evidence cannot represent turn up: a
control that resets itself on an unrelated change is invisible to an export, because an export
renders one default and stops.

## Prefer kernel-side introspection

`scripts/execute-code.sh` runs Python in the live kernel, so a widget's value, a cell's
outputs and every intermediate a cell binds can be read directly — no rendering, no DOM, no
screenshot, and no temporary debug cell added to the notebook.

```bash
# once per kernel, before any real call
bash <skill>/scripts/execute-code.sh --url http://127.0.0.1:2718 \
  -c "import marimo._code_mode as cm; help(cm)"

# the call to reach for first: what does the cell actually think?
bash <skill>/scripts/execute-code.sh --url http://127.0.0.1:2718 \
  -c 'print(picker.value, position, repr(note))'
```

Reading the state a cell computes (a resolved index, a note string, a widget's value) settles
"did the guard fire, and against what" in one call. `ctx.set_ui_value(element, value)` sets a
widget from the same side.

## Driving the real UI, when interaction fidelity is the question

A kernel-side set is not a reader changing a control: it bypasses the frontend. The defect
class that matters most in a reactive notebook — a control that is *re-instantiated* because
its options changed — only reproduces through the UI. Drive the real page when that is the
question (headless is fine; the page needs no window), and then:

- **Read back what the kernel produced, never what the control displays.** After a
  re-instantiation a `<select>` can show an option the backend is not using — observed
  showing the *first* option while the resolved value was the sixth. Captions, table rows and
  figure trace names are the backend's; the control's own text is not.
- **Capture from a session started against the file under review.** A session whose notebook
  file was edited underneath it can leave a cell's output stale while the state feeding it is
  already correct, which reads as a defect that is not there.
- **Capture per step, both ways.** Change the control, read every dependent display, then
  change it back and read again: stale state shows up on the way back, not on the way out.
- **Let the cheap cells settle before believing a read.** Caption cells finish well before the
  figure cells that carry the same information; a read taken the instant the signature moves
  can miss a callout that is about to render.
- **Never infer live behaviour from an export**, and never treat a passing `marimo check` as
  evidence of anything beyond syntax and graph shape.
