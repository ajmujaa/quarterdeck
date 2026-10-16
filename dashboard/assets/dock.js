// The Helm dock: the pure rules behind its layout and its orb. No DOM, no clock, no network, no device: tested under node
// (bin/selftest-assistant.mjs). The page (index.html) keeps every behaviour of Helm as it was; this only decides how it is shown.

export const DOCK_W = 380, RAIL_W = 76, WIDE = 1100, PHONE = 700;
export const HEARING_LEVEL = 0.02;           // the microphone level above which Helm says it is hearing you (the same scale as helmLevel)

// "dock" (the full panel at the right, the page narrows to make room), "rail" (a narrow strip with only the orb, the page keeps nearly all its width)
// or "sheet" (phone width: a bottom sheet opened from the orb). A choice made by the owner is remembered; without one the dock starts as a rail
// below 1100 px. At phone width the dock is never docked: it is a sheet that is closed until the orb is pressed.
export function layoutMode(width, saved) {
  const w = Number(width) || 0;
  if (w > 0 && w <= PHONE) return "sheet";
  if (saved === "dock" || saved === "rail") return saved;
  return w > 0 && w < WIDE ? "rail" : "dock";
}
// The width the page must leave free at the right so that nothing is covered.
export const reservedWidth = mode => (mode === "dock" ? DOCK_W : mode === "rail" ? RAIL_W : 0);
export const toggledChoice = mode => (mode === "dock" ? "rail" : "dock");     // what Collapse / Expand saves

// The word and the look for the orb. `state` is Helm's own state (idle, listening, thinking, speaking); "hearing" is listening while the owner is
// actually talking. `level` is 0..1-ish loudness (the microphone's while listening, the voice's while speaking). With reduced motion or calm mode
// the orb is a still picture of the same state (animate false, no level-driven size).
export function orbVisual({state, level = 0, handsFree = false, reduced = false}) {
  const lv = Math.max(0, Math.min(1, Number(level) || 0));
  const hearing = state === "listening" && lv >= HEARING_LEVEL;
  const mode = hearing ? "hearing" : state === "listening" ? "listening" : state === "thinking" ? "thinking" : state === "speaking" ? "speaking" : "idle";
  const word = {idle: handsFree ? "Listening for Helm" : "Idle", listening: "Listening", hearing: "Hearing you", thinking: "Thinking", speaking: "Speaking"}[mode];
  const gain = mode === "speaking" ? 5 : 9;
  return {mode, word, animate: !reduced, scale: reduced ? 0 : Math.min(1, lv * gain), hint: mode === "idle" && !handsFree ? "Press to talk" : ""};
}

// The keys: Cmd or Ctrl + J talks (as before), Cmd or Ctrl + Backslash collapses or expands the dock. Anything else is nothing.
export function dockKey(e) {
  if (!e || !(e.metaKey || e.ctrlKey) || e.altKey) return null;
  const k = String(e.key || "").toLowerCase();
  return k === "j" && !e.shiftKey ? "talk" : k === "\\" ? "collapse" : null;
}
