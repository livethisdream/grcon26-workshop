"use strict";

// The page holds one selection and asks the server to turn it into block
// parameters. It deliberately computes nothing itself: every string it
// shows came from iio_explain.annotate() or iio_grc.build(), both of
// which are tested without a browser.

const state = {
  capture: null,
  defaults: {buffer_size: 32768},
  device: null,            // annotated device dict
  channels: new Set(),     // channel ids to stream
  settings: new Map(),     // "chan:attr" -> {channel, attr, value}
  detail: null,
};

const $ = (id) => document.getElementById(id);
const el = (tag, className, text) => {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined) node.textContent = text;
  return node;
};

// ------------------------------------------------------------ loading

fetch("/api/tree").then((r) => r.json()).then((payload) => {
  state.capture = payload.capture;
  state.defaults = payload.defaults;
  $("context").textContent =
    payload.source + " — " + (payload.capture.uri || "no uri") +
    " — " + (payload.capture.description || "");
  renderDevices();
  if (state.capture.devices.length) selectDevice(state.capture.devices[0]);
});

// ------------------------------------------------------------ devices

function renderDevices() {
  const list = $("devices");
  list.replaceChildren();
  for (const device of state.capture.devices) {
    const item = el("li");
    if (state.device && state.device.label === device.label) item.className = "on";
    item.appendChild(el("span", "name", device.label));
    const streaming = device.channels.filter((c) => c.scan_element).length;
    item.appendChild(el("small",
      null, device.channels.length + " ch, " + streaming + " streaming"));
    item.onclick = () => selectDevice(device);
    list.appendChild(item);
  }
}

function selectDevice(device) {
  // A Device Source targets one device, so the selection cannot outlive
  // a device change.
  state.device = device;
  state.channels = new Set();
  state.settings = new Map();
  state.detail = null;
  renderDevices();
  renderContents();
  showDetail(null);
  emit();
}

// ----------------------------------------------------------- contents

function renderContents() {
  const device = state.device;
  $("device-title").textContent = device.label;

  const note = $("device-note");
  note.replaceChildren();
  if (device.overlay) note.appendChild(overlayBlock(device.overlay));

  const host = $("contents");
  host.replaceChildren();

  const streaming = device.channels.filter((c) => c.scan_element);
  const config = device.channels.filter((c) => !c.scan_element);

  if (streaming.length) {
    host.appendChild(channelGroup(
      "Streaming channels", streaming, true,
      "Tick these to make them outputs of the block."));
  }
  if (config.length) {
    host.appendChild(channelGroup(
      "Other channels", config, false,
      "No scan index, so they cannot stream. Their attributes still go " +
      "in Parameters."));
  }
  for (const [key, title] of [["device_attrs", "Device attributes"],
                              ["buffer_attrs", "Buffer attributes"],
                              ["debug_attrs", "Debug attributes"]]) {
    if (device[key].length) {
      host.appendChild(attrGroup(title, null, device[key]));
    }
  }
}

function channelGroup(title, channels, tickable, hint) {
  const group = el("div", "group");
  group.appendChild(heading(title, channels.length));
  if (hint) group.appendChild(el("p", "hint", hint));

  for (const channel of channels) {
    const row = el("div", "row");
    if (tickable) {
      const box = el("input");
      box.type = "checkbox";
      box.checked = state.channels.has(channel.id);
      box.onchange = () => {
        if (box.checked) state.channels.add(channel.id);
        else state.channels.delete(channel.id);
        emit();
      };
      row.appendChild(box);
    }
    const label = el("span", "label", channel.id +
      (channel.name && channel.name !== channel.id ? " (" + channel.name + ")" : ""));
    label.onclick = () => showChannel(channel);
    row.appendChild(label);
    row.appendChild(el("span", "val",
      channel.output ? "output" : "input"));
    group.appendChild(row);

    if (channel.attrs.length) {
      const nested = attrGroup(null, channel, channel.attrs);
      nested.style.marginLeft = tickable ? "1.4rem" : "0.8rem";
      group.appendChild(nested);
    }
  }
  return group;
}

function attrGroup(title, channel, attrs) {
  const group = el("div", "group");
  if (title) group.appendChild(heading(title, attrs.length));
  for (const attr of attrs) group.appendChild(attrRow(channel, attr));
  return group;
}

function heading(title, count) {
  const node = el("h3", null, title + " ");
  node.appendChild(el("span", "count", "(" + count + ")"));
  return node;
}

function attrRow(channel, attr) {
  const row = el("div", "row");
  const label = el("span", "label", attr.name);
  label.title = attr.sysfs_name;
  label.onclick = () => showAttr(channel, attr);
  row.appendChild(label);

  row.appendChild(el("span", "val",
    attr.read_error ? "unreadable" : (attr.value === null ? "" : attr.value)));

  row.appendChild(control(channel, attr));
  if (!attr.understood) row.appendChild(el("span", "chip", "unexplained"));
  return row;
}

// The control writes into `settings`; leaving it alone writes nothing.
// That matters: params it emits are attributes the flowgraph will write
// to the hardware on start, so "shown" must never mean "set".
function control(channel, attr) {
  const key = (channel ? channel.id : "") + ":" + attr.name;
  const current = state.settings.get(key);
  const available = attr.available;

  const apply = (value) => {
    if (value === "" || value === null) state.settings.delete(key);
    else state.settings.set(key, {
      channel: channel ? channel.id : null, attr: attr.name, value: value});
    emit();
  };

  if (available && available.kind === "options") {
    const select = el("select");
    select.appendChild(new Option("— leave alone —", ""));
    for (const value of available.values) select.appendChild(new Option(value, value));
    select.value = current ? current.value : "";
    select.onchange = () => apply(select.value);
    return select;
  }

  const input = el("input");
  input.type = "text";
  input.size = 8;
  input.placeholder = available && available.kind === "range"
    ? available.min + "–" + available.max
    : "leave alone";
  input.value = current ? current.value : "";
  input.onchange = () => apply(input.value.trim());
  return input;
}

// ------------------------------------------------------------- detail

function chips(provenance) {
  const wrap = el("div");
  for (const tag of provenance) {
    const [kind, confidence] = tag.split(":");
    const chip = el("span", "chip " + (confidence || kind),
      confidence ? "overlay: " + confidence : kind);
    wrap.appendChild(chip);
  }
  return wrap;
}

function overlayBlock(overlay) {
  const block = el("div", "overlay");
  block.appendChild(el("p", null, overlay.text));
  if (overlay.source) block.appendChild(el("p", "cite", "source: " + overlay.source));
  if (overlay.check) block.appendChild(el("p", "cite", "to verify: " + overlay.check));
  block.appendChild(chips(["overlay:" + overlay.confidence]));
  return block;
}

function showDetail(nodes) {
  const host = $("detail");
  host.replaceChildren();
  host.className = "detail";
  if (!nodes) {
    host.appendChild(el("p", "hint", "Pick a channel or an attribute."));
    return;
  }
  for (const node of nodes) host.appendChild(node);
}

function showAttr(channel, attr) {
  const out = [];
  const title = el("p", "detail-title", attr.sysfs_name);
  out.push(title);
  out.push(el("p", "detail-where",
    state.device.label + (channel ? " / " + channel.id : "") +
    " — " + attr.type + " attribute"));
  out.push(chips(attr.provenance));

  if (attr.summary) {
    out.push(el("p", null, attr.summary));
    const dl = el("dl");
    addPair(dl, "its own unit", attr.unit);
    out.push(dl);
    if (attr.detail) out.push(el("p", null, attr.detail));
  } else {
    out.push(el("p", null,
      "Not in the ABI tables. Nothing generic is known about this " +
      "attribute — it is driver-specific."));
  }

  const facts = el("dl");
  addPair(facts, "value now", attr.read_error
    ? "unreadable (" + attr.read_error + ")"
    : (attr.value === null ? "—" : attr.value));
  if (attr.available) {
    addPair(facts, "legal values", attr.available.kind === "range"
      ? attr.available.min + " to " + attr.available.max +
        " step " + attr.available.step
      : attr.available.values.join(" "));
  }
  for (const [label, key] of [["direction", "direction"],
                              ["channel type", "channel_type"],
                              ["channel index", "channel_index"],
                              ["modifier", "modifier"]]) {
    if (attr.parsed[key] !== null && attr.parsed[key] !== undefined) {
      addPair(facts, label, String(attr.parsed[key]));
    }
  }
  addPair(facts, "role", attr.info_word);
  out.push(facts);

  if (attr.channel_type) {
    out.push(el("p", null,
      "Channel type '" + attr.channel_type.type + "' measures " +
      attr.channel_type.quantity + ". After scale and offset the unit is " +
      attr.channel_type.unit + "." +
      (attr.channel_type.note ? " Watch out: " + attr.channel_type.note + "." : "")));
  }

  if (attr.abi) {
    const block = el("div", "kernel");
    block.appendChild(el("h3", null, "The kernel's own words"));
    for (const paragraph of attr.abi.paragraphs) {
      block.appendChild(el("p", null, paragraph));
    }
    block.appendChild(el("p", "cite",
      "— Linux ABI " + attr.abi.source + ", since kernel " +
      (attr.abi.kernel_version || "?")));
    out.push(block);
  }

  if (attr.overlay) {
    const block = overlayBlock(attr.overlay);
    block.insertBefore(el("h3", null, "On this board"), block.firstChild);
    out.push(block);
  }

  showDetail(out);
  markSelected();
}

function showChannel(channel) {
  const out = [];
  out.push(el("p", "detail-title", channel.id));
  out.push(el("p", "detail-where", state.device.label + " — " +
    (channel.output ? "output" : "input") +
    (channel.scan_element
      ? ", streams at scan index " + channel.scan_index
      : ", not a scan element")));
  if (channel.description) out.push(el("p", null, channel.description));

  if (channel.data_format) {
    out.push(el("h3", null, "On the wire"));
    out.push(el("p", "mono", channel.data_format.shorthand));
    out.push(el("p", null, channel.data_format.english));
  }

  if (channel.identity && channel.identity.length) {
    out.push(el("h3", null, "What it is connected to"));
    // The last finding is the ABI convention, worth showing only when
    // nothing better answered -- same rule the CLI uses.
    const strong = channel.identity.filter((f) => !f.fallback);
    for (const finding of (strong.length ? strong : channel.identity)) {
      const block = el("div", finding.provenance === "overlay" ? "overlay" : null);
      block.appendChild(el("p", null, finding.text));
      block.appendChild(chips([finding.provenance === "overlay"
        ? "overlay:" + finding.confidence : finding.provenance]));
      out.push(block);
    }
  }

  if (channel.conversion) {
    out.push(el("h3", null, "Raw to real"));
    if (channel.conversion.note) {
      out.push(el("p", null, channel.conversion.note));
    } else {
      out.push(el("p", "mono", channel.conversion.expression + " = " +
        channel.conversion.value + " " + (channel.conversion.symbol || "")));
    }
  }

  showDetail(out);
  markSelected();
}

function addPair(dl, term, value) {
  if (value === null || value === undefined || value === "") return;
  dl.appendChild(el("dt", null, term));
  dl.appendChild(el("dd", null, String(value)));
}

function markSelected() {
  // Re-rendering the whole contents pane on every click would lose focus
  // in the value controls, so selection highlight is left implicit.
}

// --------------------------------------------------------------- emit

let pending = null;

function emit() {
  if (!state.device) return;
  const selection = {
    device: state.device.label,
    channels: [...state.channels],
    settings: [...state.settings.values()],
    buffer_size: state.defaults.buffer_size,
    decimation: 1,
  };
  clearTimeout(pending);
  pending = setTimeout(() => {
    fetch("/api/emit", {
      method: "POST",
      headers: {"Content-Type": "application/json"},
      body: JSON.stringify(selection),
    }).then((r) => r.json()).then(renderEmit);
  }, 60);
}

function renderEmit(result) {
  const host = $("emit");
  host.replaceChildren();
  for (const field of result.fields_display || []) {
    const wrap = el("div", "field");
    const label = el("label", null, field.label + "  ");
    label.appendChild(el("span", "kind", field.kind));
    wrap.appendChild(label);
    const box = el("div", "box");
    const input = el("input");
    input.readOnly = true;
    input.value = field.text;
    box.appendChild(input);
    const button = el("button", null, "copy");
    button.onclick = () => copy(input, button);
    box.appendChild(button);
    wrap.appendChild(box);
    host.appendChild(wrap);
  }

  const warnings = $("warnings");
  warnings.replaceChildren();
  for (const message of result.warnings || []) {
    warnings.appendChild(el("div", "warn", message));
  }

  $("make").textContent = result.make || "";
}

function copy(input, button) {
  const done = () => {
    button.textContent = "copied";
    setTimeout(() => { button.textContent = "copy"; }, 1200);
  };
  if (navigator.clipboard && window.isSecureContext) {
    navigator.clipboard.writeText(input.value).then(done);
  } else {
    input.select();
    document.execCommand("copy");
    done();
  }
}
