# The workshop deck

One HTML file, two ways to read it, and a printer.

```
xdg-open slides/index.html          # that is the whole build step
```

There is no generator, no toolchain and nothing to install. Open the file
from disk, from a web server, or from a Pages URL and it behaves the same.

## Two modes, one document

The format is [ECE 444's frame view](https://github.com/livethisdream/ece444)
ported to a standalone page. A frame is one full-viewport section; the deck is
a stack of them under `scroll-snap`.

| mode | what it is | who it is for |
| --- | --- | --- |
| **read** (default) | continuous notes, everything visible | a participant, before or after |
| **present** | one frame a screen, detail collapsed | the room |

The two are the same document. `:::{depth}` content — here, `<div class="depth">`
— is **always in the DOM**. Present mode hides it behind *More detail +*; it is
never deleted, so presenting cannot lose anything the notes carry.

A frame marked `cut` shows only its `<h2>` and its `.present` blocks on screen.
Two present blocks in one `.stage` sit side by side on a laptop and stack on a
phone: key points beside the table or the diagram they talk to.

| class | means |
| --- | --- |
| `frame cut` | has a present layer; present mode shows only that |
| `frame section-frame` | a divider — which act we are in |
| `frame read-only` | notes material, skipped by present mode *and* by the counter |
| `stage split` / `split-r` | the wider track goes left / right, for a table beside a callout |
| `present callout` | the one present block that keeps a box in both modes |

## Keys

<kbd>&rarr;</kbd> <kbd>&larr;</kbd> move · <kbd>P</kbd> present or read ·
<kbd>D</kbd> detail · <kbd>G</kbd> contents (the counter is the button; double-tap
for the top) · <kbd>L</kbd> laser · <kbd>S</kbd> spotlight · <kbd>F</kbd> fullscreen.

## Printing to PDF

**tools → print / PDF**, or <kbd>&#8984;</kbd><kbd>P</kbd>. The button switches
to read mode first, because the browser prints whatever mode the page is in and
present mode would send projector-sized type to A4.

`@media print` in `frames.css` releases the deck's fixed-height scroll container
— without that the whole deck prints as **one** page — and gives each frame
`break-after: page`, so a printed frame has room to write beside it. The depth
is always shown on paper: the handout carries the material the projected deck
does not.

Measured, not assumed: 47 frames print as 49 sheets (two long frames spill to a
second page). If a change ever makes that number 1, the print block has been
overridden.

## Hosting it

`.github/workflows/pages.yml` publishes `slides/` on every push to `main`. It
needs **Settings → Pages → Source: GitHub Actions** turned on once; nothing else.

The deck is entirely self-contained apart from one Google Fonts stylesheet, and
every rule that uses it names a full fallback stack — it was checked with the
request blocked. A conference room's network is not a dependency.

## Checking a change

```
./slides/check_deck.py        # structure: titles, ids, word budgets
uv run pytest tests/test_slides.py
```

The structural check enforces what is invisible until it is wrong in front of
people: every frame has a title (or the contents overlay cannot name it), ids
are unique (or deep links land in the wrong place), a `cut` frame actually has
a present layer, no present block is over **40 words**, and no frame's present
layer is over **85**. It also asserts that every id `frames.js` reaches for by
name still exists in the markup.

**What it cannot check is layout.** Whether a frame fits one screen in present
mode is a question for a browser. The way to answer it:

```js
// headless, at the projector's size
const over = [];
document.querySelectorAll('.frame:not(.read-only)').forEach(f => {
  const w = f.querySelector('.wrap');
  const cs = getComputedStyle(f);
  const h = w.getBoundingClientRect().height
          + parseFloat(cs.paddingTop) + parseFloat(cs.paddingBottom);
  if (h > window.innerHeight) over.push(f.id + ' ' + Math.round(h));
});
```

Run in present mode. Every frame currently fits at 1024&times;768, 1280&times;800 and
1440&times;900, and nothing overflows horizontally at 390px. When a frame overruns,
**split it or move detail into `depth` — never cut the content.**

## Files

```
index.html          the deck
assets/shell.css    palette, type, HUD, popovers, jump overlay
assets/frames.css   the scroller, present/read, the present layer, print
assets/shell.js     one popover implementation
assets/frames.js    position, counter, laser, contents, keys, modes
check_deck.py       the structural check
```
