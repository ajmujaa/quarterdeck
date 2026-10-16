// Pure helpers for the Notes view and for Helm's note commands. No DOM, no network: the page hands in the notes
// (as the server folds them: {id, at, text, project, done, updated, promoted}) and gets plain data back.

const ORD = {first: 1, second: 2, third: 3, fourth: 4, fifth: 5, sixth: 6, seventh: 7, eighth: 8, ninth: 9, tenth: 10,
  one: 1, two: 2, three: 3, four: 4, five: 5, six: 6, seven: 7, eight: 8, nine: 9, ten: 10};

// "second", "2nd", "2", "two" -> 2; anything else -> null
export function ordinal(word) {
  const w = String(word || "").toLowerCase().trim();
  if (ORD[w]) return ORD[w];
  const m = /^(\d{1,2})(?:st|nd|rd|th)?$/.exec(w);
  return m && Number(m[1]) > 0 ? Number(m[1]) : null;
}

// state: "open", "done" or "all". project: "" for any, "-" for untagged, or a project name. q: words, all must appear.
export function filterNotes(notes = [], {state = "open", project = "", q = ""} = {}) {
  const words = String(q || "").toLowerCase().split(/\s+/).filter(Boolean);
  return notes.filter(n => n && typeof n.text === "string"
    && (state === "all" || (state === "done") === !!n.done)
    && (!project || (project === "-" ? !n.project : n.project === project))
    && words.every(w => (n.text + " " + (n.project || "")).toLowerCase().includes(w)));
}

// The n-th open note, counting from 1 in the order the view and Helm read them (newest first).
export const nthOpen = (notes = [], n) => filterNotes(notes, {state: "open"})[n - 1] || null;

// What Helm reads out for "list my notes": a count, then the first few, numbered the way "the second note" counts.
export function notesText(notes = [], max = 5) {
  const open = filterNotes(notes, {state: "open"});
  if (!open.length) return "No open notes.";
  const clip = s => (s.length > 70 ? s.slice(0, 69) + "…" : s);
  return `${open.length} open note${open.length === 1 ? "" : "s"}: ` + open.slice(0, max).map((n, i) => `${i + 1}, ${clip(n.text)}`).join("; ")
    + (open.length > max ? `; and ${open.length - max} more` : "") + ".";
}
