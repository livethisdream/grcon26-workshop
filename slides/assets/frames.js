/* GRCon26 workshop -- the deck.
 *
 * Ported from ECE 444's book/_static/frames.js. Position and the counter, the
 * laser and spotlight, the jump overlay, the keys, and present/read mode.
 * Sphinx-specific pieces (rubric titles, widget iframe autosizing) are gone;
 * a frame here titles itself with an <h2>.
 */
(function () {
  var deck   = document.getElementById('deck');
  /* A `.read-only` frame is notes material, not a beat: present mode hides it
     (frames.css), so it is left out of the counter and the contents overlay in
     both modes -- otherwise "12/41" in the room would count frames nobody
     sees. */
  var frames = Array.prototype.slice.call(deck.querySelectorAll('.frame:not(.read-only)'));
  var laser  = document.getElementById('laser');
  var spot   = document.getElementById('spot');
  var railfill = document.getElementById('railfill');
  var curEl  = document.getElementById('cur');
  var idx = 0, pointing = false, spotting = false;
  var px = window.innerWidth / 2, py = window.innerHeight / 2;

  document.getElementById('tot').textContent = frames.length;

  /* ---- position ----------------------------------------------------- */
  function setIndex(i, push) {
    i = Math.max(0, Math.min(frames.length - 1, i));
    if (i === idx && !push) return;
    idx = i;
    curEl.textContent = i + 1;
    railfill.style.height = ((i + 1) / frames.length * 100) + '%';
    var id = '#' + frames[i].id;
    /* Deep-linking is a nicety; it must never take the page down. In any
       sandboxed or opaque-origin document -- a file:// page included --
       replaceState throws, and because setIndex runs during init the throw
       would abort the rest of this file: no mode control, no expanders, all
       of it silently, with the page looking fine. */
    try {
      if (location.hash !== id) history.replaceState(null, '', id);
    } catch (err) { /* no addressable history here; carry on */ }
  }

  /* ---- pinch-to-zoom ------------------------------------------------ */
  /* Release scroll snapping while the reader is pinched in -- see the
     `body.zoomed` block in frames.css. Guarded because visualViewport is
     absent in older browsers and some embedded webviews. */
  var vv = window.visualViewport;
  if (vv) {
    var syncZoom = function () {
      document.body.classList.toggle('zoomed', vv.scale > 1.01);
    };
    vv.addEventListener('resize', syncZoom);
    vv.addEventListener('scroll', syncZoom);
    syncZoom();
  }

  var io = new IntersectionObserver(function (entries) {
    entries.forEach(function (e) {
      if (e.isIntersecting && e.intersectionRatio > 0.5) {
        setIndex(frames.indexOf(e.target));
      }
    });
  }, { root: deck, threshold: [0.5] });
  frames.forEach(function (f) { io.observe(f); });

  function go(i) {
    i = Math.max(0, Math.min(frames.length - 1, i));
    frames[i].scrollIntoView({ block: 'start' });
    setIndex(i, true);
  }

  /* ---- pointer ------------------------------------------------------- */
  function paint() {
    laser.style.transform = 'translate(' + px + 'px,' + py + 'px)';
    if (spotting) {
      spot.style.background =
        'radial-gradient(circle at ' + px + 'px ' + py + 'px, ' +
        'rgba(0,0,0,0) 0 84px, rgba(0,0,0,.30) 132px, rgba(0,0,0,.66) 230px)';
    }
  }
  window.addEventListener('pointermove', function (e) {
    px = e.clientX; py = e.clientY;
    if (pointing || spotting) paint();
  }, { passive: true });

  function sync() {
    laser.classList.toggle('on', pointing);
    spot.classList.toggle('on', spotting);
    document.body.classList.toggle('pointing', pointing || spotting);
    document.getElementById('btnLaser').setAttribute('aria-pressed', pointing);
    document.getElementById('btnSpot').setAttribute('aria-pressed', spotting);
    /* The panel is usually shut, so the button that opens it has to show that
       something is running. */
    document.getElementById('btnTools').setAttribute('data-active', pointing || spotting);
    paint();
  }
  function toggleLaser() { pointing = !pointing; sync(); }
  function toggleSpot()  { spotting = !spotting; sync(); }

  /* ---- jump index --------------------------------------------------- */
  var indexEl = document.getElementById('index');
  var listEl  = document.getElementById('indexlist');
  var showing = false;
  var seenSection = null;
  frames.forEach(function (f, i) {
    var sec = f.getAttribute('data-section');
    if (sec && sec !== seenSection) {
      seenSection = sec;
      var head = document.createElement('li');
      head.className = 'sec';
      head.innerHTML = '<span></span>';
      head.firstChild.textContent = sec;
      listEl.appendChild(head);
    }
    var h = f.querySelector('h1, h2');
    var li = document.createElement('li');
    var b  = document.createElement('button');
    b.type = 'button';
    var n = document.createElement('span'); n.className = 'n'; n.textContent = i + 1;
    var t = document.createElement('span');
    t.textContent = h ? h.textContent.trim() : 'Frame ' + (i + 1);
    b.appendChild(n); b.appendChild(t);
    b.addEventListener('click', function () { toggleIndex(false); go(i); });
    li.appendChild(b); listEl.appendChild(li);
  });
  function toggleIndex(force) {
    showing = (force === undefined) ? !showing : force;
    if (showing) closePops();
    indexEl.classList.toggle('on', showing);
    document.getElementById('btnIndex').setAttribute('aria-pressed', showing);
    if (showing) {
      var btns = listEl.querySelectorAll('li:not(.sec) button');
      for (var i = 0; i < btns.length; i++)
        btns[i].setAttribute('aria-current', i === idx);
      btns[idx] && btns[idx].focus();
    }
  }
  /* The counter: one tap for the contents, two to jump to the top. Both
     gestures share a target, so the open is deferred by one double-tap window
     and a second tap cancels it outright -- the overlay never flashes on its
     way to frame 1. The same path serves mouse and touch: the open overlay
     covers the counter, so on a mouse the second click of a real double-click
     lands on the backdrop and the native dblclick never fires at all. */
  var TAP_MS = 220;
  var btnIdx = document.getElementById('btnIndex');
  var tapTimer = null;

  btnIdx.addEventListener('click', function () {
    if (tapTimer) {
      clearTimeout(tapTimer); tapTimer = null;
      toggleIndex(false);
      go(0);
      return;
    }
    tapTimer = setTimeout(function () { tapTimer = null; toggleIndex(); }, TAP_MS);
  });
  /* Escape closes it, but a phone has no Escape key. */
  document.getElementById('btnIndexClose')
    .addEventListener('click', function () { toggleIndex(false); });
  indexEl.addEventListener('click', function (e) {
    if (e.target === indexEl) toggleIndex(false);
  });

  /* ---- HUD popovers -------------------------------------------------- */
  var shell = window.SHELL;
  var closePops = shell.closePops, anyPopOpen = shell.anyPopOpen;
  shell.onOpen.push(function () { toggleIndex(false); });

  var modePop  = shell.popover('btnMode', 'modepop');
  var toolsPop = shell.popover('btnTools', 'toolspop');

  /* Picking a tool shuts the panel -- you turned the laser on to point at the
     slide, not at the menu. */
  document.getElementById('btnLaser').addEventListener('click', function () {
    toggleLaser(); toolsPop.open(false);
  });
  document.getElementById('btnSpot').addEventListener('click', function () {
    toggleSpot(); toolsPop.open(false);
  });
  document.getElementById('btnFull').addEventListener('click', function () {
    fullscreen(); toolsPop.open(false);
  });
  /* Printing is read mode on paper, one frame per sheet -- but the browser
     prints whatever mode the page is in, and present mode would send the
     projector's type size to A4. Switch first, then print. */
  document.getElementById('btnPrint').addEventListener('click', function () {
    toolsPop.open(false);
    setMode('read', false);
    setTimeout(function () { window.print(); }, 60);
  });

  function fullscreen() {
    if (document.fullscreenElement) document.exitFullscreen();
    else if (document.documentElement.requestFullscreen) document.documentElement.requestFullscreen();
  }
  /* iPhone Safari has never implemented it; the call above would just no-op. */
  if (!document.documentElement.requestFullscreen) {
    document.getElementById('btnFull').hidden = true;
  }

  /* ---- keys ---------------------------------------------------------- */
  document.addEventListener('keydown', function (e) {
    if (e.metaKey || e.ctrlKey || e.altKey) return;
    var t = e.target;
    if (t && (t.tagName === 'INPUT' || t.tagName === 'TEXTAREA' || t.isContentEditable)) return;
    if (showing && e.key !== 'Escape' && e.key !== 'g' && e.key !== 'G') return;
    /* Space advances a frame, which would otherwise swallow the activation of
       whichever popover button has focus. Let the button have those two keys;
       every other shortcut still works with a panel open. */
    if ((e.key === ' ' || e.key === 'Enter') && t && t.closest && t.closest('.pop')) return;
    switch (e.key) {
      case 'ArrowRight': case 'ArrowDown': case 'PageDown': case ' ':
        e.preventDefault(); go(idx + 1); break;
      case 'ArrowLeft': case 'ArrowUp': case 'PageUp':
        e.preventDefault(); go(idx - 1); break;
      case 'Home': e.preventDefault(); go(0); break;
      case 'End':  e.preventDefault(); go(frames.length - 1); break;
      case 'l': case 'L': e.preventDefault(); toggleLaser(); break;
      case 's': case 'S': e.preventDefault(); toggleSpot(); break;
      case 'f': case 'F': e.preventDefault(); fullscreen(); break;
      case 'g': case 'G': e.preventDefault(); toggleIndex(); break;
      case 'p': case 'P':
        e.preventDefault();
        setMode(document.documentElement.getAttribute('data-mode') === 'read' ? 'present' : 'read', true);
        break;
      case 'd': case 'D':
        e.preventDefault();
        frames[idx] && setOpen(frames[idx], !frames[idx].classList.contains('open'));
        break;
      case 'Escape':
        if (anyPopOpen()) { closePops(); }
        else if (showing) { toggleIndex(false); }
        else if (pointing || spotting) { pointing = spotting = false; sync(); }
        break;
    }
  });

  /* ---- present / read ------------------------------------------------ */
  var segPresent = document.getElementById('btnPresent');
  var segRead    = document.getElementById('btnRead');
  /* Read is the default: the deck opens as continuous notes, and present is
     something you choose. Only an explicit choice is remembered -- writing the
     default into localStorage on every load pins a returning reader to
     whatever the default used to be. */
  var MODE_KEY = 'grcon26-frames-mode';
  function setMode(m, remember) {
    document.documentElement.setAttribute('data-mode', m);
    segPresent.setAttribute('aria-pressed', m === 'present');
    segRead.setAttribute('aria-pressed', m === 'read');
    /* The panel is usually shut, so the button IS the readout: labelled with
       the mode in force, the way a select shows its current value. */
    document.getElementById('btnMode').textContent = m;
    if (remember) { try { localStorage.setItem(MODE_KEY, m); } catch (err) {} }
    /* Coming back to present, land on the frame you were reading rather than
       wherever the continuous scroll had got to. */
    if (m === 'present') frames[idx] && frames[idx].scrollIntoView({ block: 'start' });
  }
  var startMode = 'read';
  try { startMode = localStorage.getItem(MODE_KEY) || 'read'; } catch (err) {}
  setMode(startMode === 'present' ? 'present' : 'read', false);
  segPresent.addEventListener('click', function () { setMode('present', true); modePop.open(false); });
  segRead.addEventListener('click', function () { setMode('read', true); modePop.open(false); });

  /* An inline expander, so a question mid-talk does not cost you the deck.
     One per frame, before its first depth: a cut frame can hold several depth
     runs, and `.open` reveals all of them at once. It is a toggle, so the
     detail can be put away again from the clicker. */
  function setOpen(f, on) {
    f.classList.toggle('open', on);
    var b = f.querySelector('.more');
    if (b) {
      b.textContent = on ? 'Less detail  −' : 'More detail  +';
      b.setAttribute('aria-expanded', on);
    }
  }
  frames.forEach(function (f) {
    var d = f.querySelector('.depth');
    if (!d) return;
    var b = document.createElement('button');
    b.type = 'button'; b.className = 'more';
    b.textContent = 'More detail  +';
    b.setAttribute('aria-expanded', 'false');
    b.addEventListener('click', function () {
      var on = !f.classList.contains('open');
      setOpen(f, on);
      if (on && d.focus) d.focus();
    });
    d.parentNode.insertBefore(b, d);
  });

  /* ---- open on the hash the URL asked for ---------------------------- */
  var start = frames.findIndex(function (f) { return '#' + f.id === location.hash; });
  if (start > 0) { frames[start].scrollIntoView({ block: 'start' }); setIndex(start, true); }
  else setIndex(0, true);

  deck.focus({ preventScroll: true });
})();
