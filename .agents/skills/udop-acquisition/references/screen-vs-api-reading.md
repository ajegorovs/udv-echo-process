# Reading values out of a GUI you cannot introspect

Four rules, each learned by getting it wrong on a live Delphi/VCL application whose controls are
caption-less and whose values are painted.

## 1. Labels come from the pixels; values come from the API

Painted labels are not retrievable. `WM_GETTEXT` and `GetWindowText` return empty for controls whose text is
*rendered* rather than stored — so the label beside a field exists only in a screenshot. The field's own
**value**, by contrast, is usually readable through the control (`WM_GETTEXT` on the field, `CB_GETCURSEL`
on a combo) and that read is precise.

So: take a screenshot for the label map, and read numbers from the control.

## 2. Zoom before you trust a digit

A vision read of a whole 627x384 dialog misread four digits in one pass — and **two independent reads made
the same error**, because the cause was in the image, not the reader: a value's leading character was clipped
by the edit's frame and rendered like a different digit. Agreement between two readings of one lossy source
is **not** corroboration.

Zoom to full resolution (crop the region; a crop keeps native pixels) before believing any number that
matters, or cross-check it against an API read.

## 3. A stale open dialog is not evidence

An application may hold a derived value that only refreshes when the window is reopened. A user reading one
field in a dialog they already have open sees the old value and concludes, reasonably, that nothing changed.
So a value is only what a **freshly opened** dialog states: close, reopen, then read — and never "read it
again" from the same open window.

## 4. A screenshot is not evidence about what a press would hit

Pixels show what is *visible*, not what is *there*: an unrelated window can be sitting in front of the region
you photographed, and a control's pre-show rectangle is not its shown one. For anything that ends in a press,
the evidence is the control tree with rectangles taken at the same moment — and if a control is not where a
binding expects it, refuse rather than press somewhere unintended.

## Corollary: read the mode off the caption

Two builds of the same application — simulator and instrument — differed in exactly one menu entry and in a
movable overlay's position, but their window captions differed plainly (`...Simul` versus `...DOP3010.43`).
Where a run's meaning depends on which build it drove, that caption is a free, checkable fact: read it and
refuse on a mismatch, the same way you refuse a mismatched instrument setting.
