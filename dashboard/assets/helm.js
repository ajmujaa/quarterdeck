// The microphone and speaker side of Helm. Everything stays on this Mac: the page
// records, cuts the recording at pauses in speech, turns each piece into 16 kHz mono
// WAV and posts it to this dashboard (whisper.cpp), then plays the reply the local
// voice sends back. No DOM here except through the callbacks the page passes in.

import {createSegmenter, listenParams} from "./turns.js";

export function toWav16k(chunks, rate) {
  let n = 0; for (const c of chunks) n += c.length;
  const all = new Float32Array(n); let o = 0;
  for (const c of chunks) { all.set(c, o); o += c.length; }
  const ratio = rate / 16000, len = Math.floor(n / ratio), pcm = new Int16Array(len);
  for (let i = 0; i < len; i++) {                       // average each window: a cheap low-pass before dropping samples
    const a = Math.floor(i * ratio), b = Math.max(a + 1, Math.min(n, Math.floor((i + 1) * ratio)));
    let s = 0; for (let j = a; j < b; j++) s += all[j];
    pcm[i] = Math.max(-1, Math.min(1, s / (b - a))) * 0x7fff;
  }
  const out = new DataView(new ArrayBuffer(44 + len * 2));
  const w = (at, t) => [...t].forEach((c, i) => out.setUint8(at + i, c.charCodeAt(0)));
  w(0, "RIFF"); out.setUint32(4, 36 + len * 2, true); w(8, "WAVEfmt "); out.setUint32(16, 16, true);
  out.setUint16(20, 1, true); out.setUint16(22, 1, true); out.setUint32(24, 16000, true); out.setUint32(28, 32000, true);
  out.setUint16(32, 2, true); out.setUint16(34, 16, true); w(36, "data"); out.setUint32(40, len * 2, true);
  pcm.forEach((v, i) => out.setInt16(44 + i * 2, v, true));
  return out.buffer;
}

// Listens until closed. The decisions (when a voice starts, when Helm must stop talking, when a turn ends) are turns.js;
// this only moves audio. `timing()` says what Helm is doing right now, `onOnset` fires when a recording starts,
// `onPeek` may end a conversation turn early, and `onSegment(wav, hint)` gets each finished recording.
export async function openMic({onLevel, onSegment, onOnset, onPeek, timing = () => listenParams()}) {
  const stream = await navigator.mediaDevices.getUserMedia({audio: {channelCount: 1, echoCancellation: true, noiseSuppression: true, autoGainControl: true}});
  const ctx = new AudioContext();
  await Promise.race([ctx.resume(), new Promise(r => setTimeout(r, 400))]);
  await ctx.audioWorklet.addModule("/assets/helm-tap.js");
  const node = new AudioWorkletNode(ctx, "tap"), mute = ctx.createGain();
  mute.gain.value = 0;
  ctx.createMediaStreamSource(stream).connect(node);
  node.connect(mute).connect(ctx.destination);          // pulled by the graph, silent
  let paused = false;
  const seg = createSegmenter({timing, onOnset, onSegment: (chunks, hint) => onSegment(toWav16k(chunks, ctx.sampleRate), hint),
    onPeek: onPeek && (chunks => onPeek(toWav16k(chunks, ctx.sampleRate)))});
  node.port.onmessage = e => {
    const x = e.data; let sum = 0;
    for (let i = 0; i < x.length; i++) sum += x[i] * x[i];
    const rms = Math.sqrt(sum / x.length), ms = x.length / ctx.sampleRate * 1000;
    onLevel(paused ? 0 : rms);
    if (paused) { seg.reset(); return; }
    seg.push(x, rms, ms);
  };
  return {
    state() { return ctx.state; },
    resume() { return ctx.resume(); },
    setPaused(p) { paused = p; },
    close() { node.port.onmessage = null; stream.getTracks().forEach(t => t.stop()); ctx.close(); },
  };
}

// Plays a WAV and reports its loudness while it plays, so the page can draw it.
let current = null;
export function stopSpeaking() { if (current) { try { current.src.stop(); } catch (e) {} } }
export async function playWav(buf, onLevel) {
  stopSpeaking();
  const ctx = new AudioContext();
  await Promise.race([ctx.resume(), new Promise(r => setTimeout(r, 400))]);
  if (ctx.state !== "running") { ctx.close(); throw new Error("the browser is holding audio until you click the page once"); }
  const audio = await ctx.decodeAudioData(buf);
  const src = ctx.createBufferSource(), an = ctx.createAnalyser(), data = new Float32Array(1024);
  an.fftSize = 1024; src.buffer = audio; src.connect(an); an.connect(ctx.destination);
  const me = current = {src};
  let alive = true;
  const tick = () => {
    if (!alive) return;
    an.getFloatTimeDomainData(data);
    let s = 0; for (let i = 0; i < data.length; i++) s += data[i] * data[i];
    onLevel(Math.sqrt(s / data.length));
    requestAnimationFrame(tick);
  };
  tick();
  await new Promise(res => { src.onended = res; src.start(); });
  alive = false; onLevel(0); if (current === me) current = null; ctx.close();
}
