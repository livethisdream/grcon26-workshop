#!/usr/bin/env python3
"""Structural checks on the deck.

The frame view has a handful of rules that are invisible until they are
wrong on a projector: a frame with no title is unreachable from the contents
overlay, a duplicate id makes deep links land in the wrong place, and a
present block over the word budget is a slide nobody can read from the back
of the room. None of that raises anything in a browser.

Standard library only, same as everything else here.

    ./slides/check_deck.py            # 0 on success
"""
import os
import re
import sys
from html.parser import HTMLParser

HERE = os.path.dirname(os.path.abspath(__file__))
DECK = os.path.join(HERE, "index.html")

# Forty words a present block, which is the budget the frame view was
# re-cut against. Counted per block, not per frame: two blocks in a stage sit
# side by side and are read as one screen, but each has to stand on its own.
WORD_BUDGET = 40
# A frame's whole present layer. Two blocks at budget is already a busy slide.
FRAME_BUDGET = 85


# Void elements have no end tag, so pushing them onto the tag stack leaves it
# permanently one deeper and the depth comparison that closes a present block
# never matches again -- the block then swallows everything after it and
# reports a word count for half the frame. Cost one wrong failure the day the
# deck grew its first <img>.
VOID = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link",
        "meta", "param", "source", "track", "wbr"}


class Deck(HTMLParser):
    """Collect frames, their ids, titles, and present-block word counts."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.frames = []          # dicts: id, classes, title, present[], depth
        self.ids = []
        self.stack = []           # open tags, innermost last
        self.cur = None           # frame being read
        self.in_title = False
        self.present_depth = None  # nesting level of the open present block
        self.buf = []

    # -- helpers ---------------------------------------------------------
    def _classes(self, attrs):
        return dict(attrs).get("class", "").split()

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if "id" in a:
            self.ids.append(a["id"])
        classes = self._classes(attrs)
        if tag in VOID:
            return
        self.stack.append(tag)

        if tag == "section" and "frame" in classes:
            self.cur = {
                "id": a.get("id", ""),
                "classes": classes,
                "section": a.get("data-section", ""),
                "title": None,
                "present": [],
                "depth": False,
            }
            self.frames.append(self.cur)
        elif self.cur is not None:
            if tag in ("h1", "h2") and self.cur["title"] is None:
                self.in_title = True
                self.buf = []
            elif "present" in classes and self.present_depth is None:
                self.present_depth = len(self.stack)
                self.buf = []
            elif "depth" in classes:
                self.cur["depth"] = True

    def handle_endtag(self, tag):
        if self.in_title and tag in ("h1", "h2"):
            self.cur["title"] = "".join(self.buf).strip()
            self.in_title = False
            self.buf = []
        if self.present_depth is not None and len(self.stack) == self.present_depth:
            self.cur["present"].append("".join(self.buf))
            self.present_depth = None
            self.buf = []
        if tag in VOID:
            return
        if tag == "section" and self.stack and self.stack[-1] == "section":
            self.cur = None
        if self.stack:
            self.stack.pop()

    def handle_data(self, data):
        if self.in_title or self.present_depth is not None:
            self.buf.append(data)


def words(text):
    """Words a person reads off the screen.

    A code block is one glance, not fourteen words, so a `pre` run counts as
    a single item -- but the parser has already flattened it into the same
    buffer, so this is deliberately crude: anything with no letters in it is
    not a word.
    """
    return [w for w in re.split(r"\s+", text) if re.search(r"[A-Za-z]", w)]


def main():
    with open(DECK, encoding="utf-8") as fh:
        source = fh.read()

    deck = Deck()
    deck.feed(source)
    fails = []

    if not deck.frames:
        fails.append("no frames found -- did the markup change?")

    for f in deck.frames:
        where = f["id"] or "(no id)"
        if not f["id"]:
            fails.append("a frame has no id, so nothing can link to it")
        if not f["title"] and "title-frame" not in f["classes"]:
            fails.append(f"{where}: no <h1>/<h2>, so the contents overlay "
                         f"cannot name it")
        if "cut" in f["classes"] and not f["present"]:
            fails.append(f"{where}: marked `cut` but carries no present block, "
                         f"so present mode shows a bare title")
        if f["present"] and "cut" not in f["classes"]:
            fails.append(f"{where}: has present blocks but is not `cut`, so "
                         f"they will not lay out side by side")
        total = 0
        for i, block in enumerate(f["present"]):
            n = len(words(block))
            total += n
            if n > WORD_BUDGET:
                fails.append(f"{where}: present block {i + 1} is {n} words "
                             f"(budget {WORD_BUDGET}) -- move detail to depth")
        if total > FRAME_BUDGET:
            fails.append(f"{where}: {total} present words (budget "
                         f"{FRAME_BUDGET}) -- split the frame")

    for src in sorted(set(re.findall(r'<img[^>]+src="([^"]+)"', source))):
        if not src.startswith(("http:", "https:", "data:")):
            if not os.path.exists(os.path.join(HERE, src)):
                fails.append(f"missing image `{src}` -- render it with "
                             f"slides/render_grc.py")
    for tag in re.findall(r'<img[^>]*>', source):
        if 'alt="' not in tag:
            fails.append(f"an <img> has no alt text: {tag[:70]}")

    dupes = {i for i in deck.ids if deck.ids.count(i) > 1}
    for i in sorted(dupes):
        fails.append(f"duplicate id `{i}` -- deep links land on the first one")

    # Every id frames.js reaches for by name. A rename in the markup that
    # misses one of these breaks a control silently, with the page looking
    # fine.
    wired = ["deck", "laser", "spot", "railfill", "cur", "tot", "index",
             "indexlist", "btnIndex", "btnIndexClose", "btnMode", "btnTools",
             "btnLaser", "btnSpot", "btnFull", "btnPrint", "btnPresent",
             "btnRead", "modepop", "toolspop"]
    for i in wired:
        if i not in deck.ids:
            fails.append(f"frames.js wires `{i}` by id and the markup has none")

    counted = [f for f in deck.frames if "read-only" not in f["classes"]]
    print(f"{len(deck.frames)} frames, {len(counted)} in the counter, "
          f"{sum(1 for f in deck.frames if f['depth'])} carrying depth")

    if fails:
        print(f"\n{len(fails)} failures:", file=sys.stderr)
        for m in fails:
            print(f"  {m}", file=sys.stderr)
        return 1
    print("ok")
    return 0


if __name__ == "__main__":
    sys.exit(main())
