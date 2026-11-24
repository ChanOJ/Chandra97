/* Tiny standard MIDI file player (Web Audio, no dependency, no sound bank).
 * Replaces the <embed ... controls=smallconsole> of the 1997 page, which no browser plays any more.
 * Usage: <span class="midi-player" data-src="/file.mid" data-loop="1"></span> + this script.
 * Notes are rendered by simple oscillators (drums by noise bursts): a chiptune-like rendition,
 * not a General MIDI one. Playback starts on click (browsers forbid autoplay).
 */
(function () {
  "use strict";

  function parse(buf) {
    var d = new DataView(buf), p = 0;
    function str(n) { var s = ""; for (var i = 0; i < n; i++) s += String.fromCharCode(d.getUint8(p++)); return s; }
    function u32() { var v = d.getUint32(p); p += 4; return v; }
    function u16() { var v = d.getUint16(p); p += 2; return v; }
    if (str(4) !== "MThd") throw new Error("not a MIDI file");
    u32(); u16(); var ntracks = u16(), div = u16(), events = [];
    if (div & 0x8000) throw new Error("SMPTE time not supported");
    for (var t = 0; t < ntracks; t++) {
      if (str(4) !== "MTrk") break;
      var len = u32(), end = p + len, tick = 0, run = 0;
      function vlq() { var v = 0, b; do { b = d.getUint8(p++); v = (v << 7) | (b & 0x7f); } while (b & 0x80); return v; }
      while (p < end) {
        tick += vlq();
        var st = d.getUint8(p);
        if (st & 0x80) { p++; if (st < 0xf0) run = st; } else st = run;
        if (st === 0xff) {
          var type = d.getUint8(p++), l = vlq();
          if (type === 0x51) events.push({ t: tick, k: "tempo", v: (d.getUint8(p) << 16) | (d.getUint8(p + 1) << 8) | d.getUint8(p + 2) });
          p += l;
        } else if (st === 0xf0 || st === 0xf7) {
          p += vlq();
        } else {
          var hi = st & 0xf0, ch = st & 0x0f, a = d.getUint8(p++), b = (hi === 0xc0 || hi === 0xd0) ? 0 : d.getUint8(p++);
          if (hi === 0x90 && b > 0) events.push({ t: tick, k: "on", ch: ch, n: a, v: b });
          else if (hi === 0x80 || hi === 0x90) events.push({ t: tick, k: "off", ch: ch, n: a });
          else if (hi === 0xc0) events.push({ t: tick, k: "prog", ch: ch, v: a });
        }
      }
      p = end;
    }
    events.sort(function (x, y) { return x.t - y.t; });
    // ticks -> seconds through the tempo map
    var sec = 0, last = 0, tempo = 500000, out = [];
    events.forEach(function (e) {
      sec += (e.t - last) * tempo / div / 1e6; last = e.t;
      if (e.k === "tempo") tempo = e.v; else { e.s = sec; out.push(e); }
    });
    return { events: out, length: sec };
  }

  function wave(prog) { // rough family -> oscillator
    if (prog >= 80 && prog < 88) return "square";
    if (prog >= 88 && prog < 104) return "triangle";
    if (prog >= 24 && prog < 40) return "sawtooth";
    if (prog >= 56 && prog < 80) return "sawtooth";
    return "triangle";
  }

  function Player(el) {
    var src = el.getAttribute("data-src"), loop = el.getAttribute("data-loop") === "1";
    var btn = document.createElement("button");
    btn.type = "button"; btn.textContent = "\u25B6 Play";
    btn.style.cssText = "font:11px Verdana,Arial,sans-serif;padding:1px 8px;cursor:pointer";
    el.appendChild(btn);
    var ctx, song, timer, idx, t0, playing = false, live = {}, prog = {};

    function noteOn(e, when) {
      var f = 440 * Math.pow(2, (e.n - 69) / 12), g = ctx.createGain(), peak = 0.12 * e.v / 127;
      if (e.ch === 9) { // drums: short noise burst
        var n = ctx.createBufferSource(), b = ctx.createBuffer(1, ctx.sampleRate / 10, ctx.sampleRate), x = b.getChannelData(0);
        for (var i = 0; i < x.length; i++) x[i] = (Math.random() * 2 - 1) * (1 - i / x.length);
        n.buffer = b; g.gain.value = peak * 2; n.connect(g); g.connect(ctx.destination); n.start(when); return;
      }
      var o = ctx.createOscillator();
      o.type = wave(prog[e.ch] || 0); o.frequency.value = f;
      g.gain.setValueAtTime(0, when); g.gain.linearRampToValueAtTime(peak, when + 0.01);
      o.connect(g); g.connect(ctx.destination); o.start(when);
      (live[e.ch + ":" + e.n] = live[e.ch + ":" + e.n] || []).push({ o: o, g: g });
    }
    function noteOff(e, when) {
      var l = live[e.ch + ":" + e.n], v = l && l.shift();
      if (!v) return;
      v.g.gain.cancelScheduledValues(when); v.g.gain.setValueAtTime(v.g.gain.value, when);
      v.g.gain.linearRampToValueAtTime(0, when + 0.08); v.o.stop(when + 0.1);
    }
    function pump() { // schedule 0.5 s ahead
      var now = ctx.currentTime - t0;
      while (idx < song.events.length && song.events[idx].s < now + 0.5) {
        var e = song.events[idx++], when = t0 + e.s;
        if (e.k === "prog") prog[e.ch] = e.v;
        else if (e.k === "on") noteOn(e, Math.max(when, ctx.currentTime));
        else noteOff(e, Math.max(when, ctx.currentTime));
      }
      if (idx >= song.events.length && now > song.length + 0.5) {
        if (loop) { idx = 0; t0 = ctx.currentTime; live = {}; prog = {}; } else stop();
      }
    }
    function stop() {
      playing = false; clearInterval(timer); btn.textContent = "\u25B6 Play";
      Object.keys(live).forEach(function (k) { live[k].forEach(function (v) { try { v.o.stop(); } catch (e) {} }); });
      live = {};
    }
    function start() {
      ctx = ctx || new (window.AudioContext || window.webkitAudioContext)();
      ctx.resume(); idx = 0; prog = {}; t0 = ctx.currentTime + 0.1; playing = true;
      btn.textContent = "\u25A0 Stop"; timer = setInterval(pump, 100);
    }
    btn.addEventListener("click", function () {
      if (playing) return stop();
      if (song) return start();
      btn.disabled = true; btn.textContent = "\u2026";
      fetch(src).then(function (r) { return r.arrayBuffer(); }).then(function (b) {
        song = parse(b); btn.disabled = false; start();
      }).catch(function () { btn.textContent = "(no sound)"; });
    });
  }

  Array.prototype.forEach.call(document.querySelectorAll(".midi-player"), Player);
})();
