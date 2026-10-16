// Pure helpers that tie a log line to the Ledger row it belongs to. No DOM: the page passes plain data in.
// Log lines start with "[2026-10-05 14:03:11]" (local time, written by bin/lib.sh) or "[2026-10-05T12:03:11Z]"
// (UTC, written by the dashboard when it starts a run). A line belongs to a row when the project, the duty
// and the minute are the same.

const STAMP = /^\[(\d{4})-(\d\d)-(\d\d)[ T](\d\d):(\d\d)(?::\d\d(?:\.\d+)?)?(Z)?\]/;

// The start of the minute a log line was written in, in epoch milliseconds, or null.
export function logMinute(line) {
  const m = STAMP.exec(String(line));
  if (!m) return null;
  const [y, mo, d, h, mi] = m.slice(1, 6).map(Number);
  const t = m[6] ? Date.UTC(y, mo - 1, d, h, mi) : new Date(y, mo - 1, d, h, mi).getTime();
  return isNaN(t) ? null : t;
}

// The ledger row (a run) a log line belongs to, or null. `runs` is the dashboard's run list.
export function runForLine(line, runs, duty, project) {
  const t = logMinute(line);
  if (t === null) return null;
  return (runs || []).find(r => r && r.duty === duty && r.project === project && Math.floor(Date.parse(r.at) / 60000) * 60000 === t) || null;
}

// How many characters of the line the timestamp "[....]" takes, so the page can link just that part.
export const stampLength = line => { const m = STAMP.exec(String(line)); return m ? m[0].length : 0; };

// "Ledger / shipwright on wayfarer-mobile / log"
export const crumbText = (duty, project) => `Ledger / ${duty} on ${project} / log`;
