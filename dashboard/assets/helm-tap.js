// The microphone tap, loaded into the audio thread by helm.js (audioWorklet.addModule). A file of its own so the page's
// Content-Security-Policy needs no blob: script source: it is served from this server like every other asset.
class Tap extends AudioWorkletProcessor {
  process(inputs){ const ch = inputs[0][0]; if(ch) this.port.postMessage(ch.slice()); return true; }
}
registerProcessor("tap", Tap);
