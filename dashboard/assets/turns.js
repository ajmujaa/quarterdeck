// Turn-taking for Helm: when to start listening, when Helm must stop talking because the owner started, when a turn
// has ended, how long the follow-up window is. Pure: given a few numbers and timestamps, return a decision. No audio,
// no DOM, no clock of its own, so every rule here is tested under node (bin/selftest-assistant.mjs).
// helm.js feeds it audio levels; the page feeds it what Helm is doing.

export const T = {
  THRESHOLD: 0.02,                 // loudness (RMS) that counts as a voice when Helm is silent
  THRESHOLD_SPEAKING: 0.06,        // while Helm speaks, only something clearly louder than its own echo counts
  ONSET_MS: 120,                   // voice for this long starts a recording
  ONSET_MS_SPEAKING: 320,          // while Helm speaks, it must last this long to count as the owner (barge-in)
  END_MS_COMMAND: 900,             // a pause this long ends a command
  END_MS_CONVERSATION: 1400,       // in a conversation, wait longer so a pause to think does not cut the owner off
  PEEK_MS: 900,                    // in a conversation, after this pause check early whether the sentence is clearly finished
  DEAF_AFTER_PLAYBACK_MS: 300,     // the room still rings for a moment after Helm stops: do not listen to it
  FOLLOW_MS_COMMAND: 8000,         // after a command the wake word is not needed for this long
  FOLLOW_MS_CONVERSATION: 20000,   // in a conversation, for this long after Helm last spoke
  SLOW_ACK_MS: 2000,               // say "One moment" only if the first sentence takes longer than this
  MIN_MS: 350,                     // a recording shorter than this (without the pauses) is noise
  MAX_MS: 20000,                   // and one longer than this is cut
  PRE_MS: 300,                     // audio kept from before the onset, so the first word is not clipped
};

// What the microphone should do right now. `sinceSpeechEndMs` is how long ago Helm last stopped talking (or null).
export function listenParams({speaking = false, conversation = false, sinceSpeechEndMs = null, bargeIn = true} = {}) {
  const deaf = (speaking && !bargeIn) || (!speaking && sinceSpeechEndMs !== null && sinceSpeechEndMs >= 0 && sinceSpeechEndMs < T.DEAF_AFTER_PLAYBACK_MS);
  return {
    deaf, speaking,
    threshold: speaking ? T.THRESHOLD_SPEAKING : T.THRESHOLD,
    onsetMs: speaking ? T.ONSET_MS_SPEAKING : T.ONSET_MS,
    endMs: conversation ? T.END_MS_CONVERSATION : T.END_MS_COMMAND,
    peekMs: conversation ? T.PEEK_MS : 0,
  };
}

// One decision. ev: {type: "voice", rms, voicedMs} while nobody is being recorded;
// {type: "quiet", quietMs, segMs, peeked} while a recording is running.
//   "listen"         start recording
//   "stop_speaking"  start recording AND silence Helm: the owner is talking over it
//   "end_turn"       the recording is over, hand it on
//   "peek"           check now, with a quick transcription, whether the owner has clearly finished
//   "ignore"         nothing to do
export function decide(ev, p) {
  if (ev.type === "voice") {
    if (p.deaf || !(ev.rms > p.threshold) || ev.voicedMs < p.onsetMs) return "ignore";
    return p.speaking ? "stop_speaking" : "listen";
  }
  if (ev.type === "quiet") {
    if (ev.quietMs >= p.endMs || ev.segMs >= T.MAX_MS) return "end_turn";
    if (p.peekMs && !ev.peeked && ev.quietMs >= p.peekMs) return "peek";
  }
  return "ignore";
}

// Is a transcript a clearly finished sentence? Whisper punctuates, so a full stop, question mark or exclamation mark
// after at least three words (or a short complete phrase of a command) is taken as finished; a trailing "and", "so",
// "but", a comma or no mark at all is not.
export function sentenceFinished(text) {
  const t = String(text || "").trim();
  if (!/[.!?]["')]*$/.test(t) || /\b(?:and|but|so|or|because|then|the|a|to|of|with)[.!?]*$/i.test(t)) return false;
  return t.split(/\s+/).length >= 3 || /^(?:yes|no|okay|stop|help|thanks|thank you)[.!?]$/i.test(t);
}

export const followMs = conversation => (conversation ? T.FOLLOW_MS_CONVERSATION : T.FOLLOW_MS_COMMAND);

// Does this utterance need the wake word? In hands-free mode it does, unless Helm spoke recently enough.
export function needsWake({handsFree, now, followUntil}) {
  return !!handsFree && now >= followUntil;
}

// The recorder: turns a stream of audio chunks (each with its loudness and length in ms) into recordings, using decide().
// `timing()` returns listenParams each chunk, so a change in what Helm is doing takes effect at once.
//   onOnset({stopSpeaking}) a recording started (stopSpeaking: the owner is talking over Helm)
//   onPeek(chunks)          resolves to {text, finished}; asked once per pause in a conversation
//   onSegment(chunks, hint) the recording ended; hint is the peek's text when it already knew the sentence was finished
export function createSegmenter({timing, onOnset = () => {}, onPeek = null, onSegment}) {
  let pre = [], preLen = 0, seg = null, voiced = 0;
  const reset = () => { pre = []; preLen = 0; seg = null; voiced = 0; };
  const finish = hint => {
    const s = seg; reset();
    if (s && s.ms - s.quiet >= T.MIN_MS) onSegment(s.chunks, hint);
  };
  return {
    push(chunk, rms, ms) {
      const p = timing();
      if (!seg) {
        if (p.deaf) { reset(); return "ignore"; }
        pre.push({chunk, ms}); preLen += ms;
        while (preLen > T.PRE_MS && pre.length > 1) preLen -= pre.shift().ms;
        voiced = rms > p.threshold ? voiced + ms : 0;
        const d = decide({type: "voice", rms, voicedMs: voiced}, p);
        if (d === "ignore") return d;
        seg = {chunks: pre.map(x => x.chunk), ms: preLen, quiet: 0, peeked: false};
        onOnset({stopSpeaking: d === "stop_speaking"});
        return d;
      }
      seg.chunks.push(chunk); seg.ms += ms;
      seg.quiet = rms > p.threshold ? 0 : seg.quiet + ms;
      if (seg.quiet === 0) seg.peeked = false;                       // the owner spoke again: a later pause may be checked afresh
      const d = decide({type: "quiet", quietMs: seg.quiet, segMs: seg.ms, peeked: seg.peeked}, p);
      if (d === "end_turn") finish();
      else if (d === "peek" && onPeek) {
        const mine = seg; seg.peeked = true;
        Promise.resolve(onPeek(mine.chunks.slice())).then(r => {
          if (seg === mine && r && r.finished && mine.quiet >= p.peekMs) finish(r.text);      // still quiet, and clearly finished: end now
        }).catch(() => {});
      }
      return d;
    },
    reset,
    recording: () => !!seg,
  };
}
