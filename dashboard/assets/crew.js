// The Crew page's data: which job each agent (duty) belongs to, one plain sentence for it, the few inputs that matter, and the one function
// that turns the Run dialog's fields into the arguments /api/run takes. Pure functions, so a node test can read them (bin/selftest-handlers.mjs).
// The duty files give a name and a header line, not a job, so the grouping lives in this one table. A duty that is in no group still appears, under "Other".

export const GROUPS = [
  {id: "review", title: "Review", why: "Read a pull request or the interface and say what is wrong. They report; none of them merges.",
   duties: ["surveyor", "inspector", "marshal", "lookout", "pilot", "joiner"]},
  {id: "build", title: "Build", why: "Turn an issue into a branch and a pull request, and write the tests that prove it.",
   duties: ["shipwright", "assayer", "caulker", "trials"]},
  {id: "plan", title: "Plan", why: "Decide what to do and in what order: requirements, sprints, rulings and issues.",
   duties: ["purser", "planner", "panel", "foreman", "harbourmaster"]},
  {id: "check", title: "Check and keep", why: "Look after the project: what comes aboard, the record of decisions, stale work.",
   duties: ["quartermaster", "logkeeper", "bosun", "scribe"]},
  {id: "infra", title: "Infrastructure", why: "Read a change to infrastructure files and say how risky it is. Files only; nothing touches a cloud account.",
   duties: ["infra"]},
  {id: "design", title: "Design and make", why: "Turn an idea into a one-page brief, then into mock-ups to look at.",
   duties: ["brief", "mockup"]},
];
export const OTHER = {id: "other", title: "Other", why: "Agents that are not sorted into a job yet.", duties: []};

// flag: the command-line flag. main: shown as a plain field (1 to 3 per agent). need: at least one of these flags must be filled before Run.
// does: one sentence. writes: what "Write for real" lets it do. local: it only ever writes a file in the data folder, either way.
const F = (flag, label, ph, extra = {}) => ({flag, label, ph, ...extra});
export const INFO = {
  surveyor: {does: "Reads a pull request and posts what it finds as review comments.", writes: "post its findings on the pull request",
    main: [F("--pr", "Pull request number", "for example 42. Empty reviews every open one", {main: 1})]},
  inspector: {does: "Checks that a pull request really does what its issue asked.", writes: "post its verdict on the pull request", need: ["--pr"],
    main: [F("--pr", "Pull request number", "for example 42", {main: 1}), F("--issue", "Issue it claims to fix", "for example 17 (optional)", {main: 1})]},
  marshal: {does: "Reads a pull request for security problems, from three sides.", writes: "post its verdict on the pull request",
    main: [F("--pr", "Pull request number", "for example 42. Empty checks every open one", {main: 1})]},
  lookout: {does: "Takes pictures of the running screens at three widths and judges them against the design notes.", writes: "post its findings on the pull request",
    main: [F("--pr", "Pull request number", "for example 42", {main: 1})]},
  pilot: {does: "Starts the app from a pull request and tries the main flows in a browser.", writes: "post its findings on the pull request",
    main: [F("--pr", "Pull request number", "for example 42", {main: 1})]},
  joiner: {does: "Reviews the interface for accessibility, states and small screens, and writes a findings document.", local: true,
    main: [F("--path", "Folder to look at", "for example src/components (optional)", {main: 1})]},
  shipwright: {does: "Takes one issue to a branch and a pull request.", writes: "push a branch and open a pull request", need: ["--issue", "--plan"],
    main: [F("--issue", "Issue number", "for example 17", {main: 1}), F("--plan", "Plan document", "instead of an issue: a plan in the workspace", {main: 1})]},
  assayer: {does: "Writes tests from the issue's requirements alone, without seeing the change, and keeps the ones that prove something.", writes: "add the tests to the pull request branch",
    need: ["--pr", "--issue"], main: [F("--pr", "Pull request number", "for example 42", {main: 1}), F("--issue", "Issue number", "for example 17", {main: 1})]},
  caulker: {does: "Fixes exactly what the reviewers found on a pull request, on its own branch, and nothing else.", writes: "push the fixes to the pull request branch", need: ["--pr"],
    main: [F("--pr", "Pull request number", "for example 42", {main: 1})], adv: [F("--findings", "Findings file", "path to a findings file")]},
  trials: {does: "Writes the test that reproduces a bug and checks that it fails on the current code.", writes: "commit the failing test", need: ["--issue"],
    main: [F("--issue", "Issue number", "for example 17", {main: 1})]},
  purser: {does: "Rewrites a backlog issue into requirements a stranger could start from.", writes: "write the requirements into the issue",
    main: [F("--issue", "Issue number", "for example 17", {main: 1})]},
  planner: {does: "Puts the open backlog in order, sizes each issue and proposes what fits. Moves nothing.", writes: "save the plan as a document",
    main: [F("--capacity", "How many issues fit", "for example 5 (optional)", {main: 1})], adv: [F("--budget", "Budget in dollars", "for example 20")]},
  panel: {does: "Seats several crew members on one question and makes them disagree, then writes the ruling.", local: true,
    main: [{flag: "--panel", label: "Kind of panel", type: "select", opts: ["design", "dev", "spec", "backlog", "decision"], def: "design", main: 1},
           F("--question", "The question", "for a decision panel", {main: 1}), F("--issue", "Issue number", "for a dev panel", {main: 1})],
    adv: [F("--target", "Path to restrict to", "path"), F("--idea", "The rough note", "for a spec panel"), F("--brief", "What prompted this review", "a sentence")]},
  foreman: {does: "Turns a findings document into well-formed GitHub issues, without duplicates.", writes: "file the issues on GitHub", need: ["--from"],
    main: [F("--from", "Findings document", "a file in the workspace", {main: 1})], adv: [{flag: "--one", label: "File only the first item", type: "check"}]},
  harbourmaster: {does: "Checks the project board against what is really happening on GitHub.", writes: "move the cards",
    main: [], adv: [{flag: "--sync-only", label: "Facts only, no model", type: "check"}, F("--max", "Most cards to move", "for example 25")]},
  quartermaster: {does: "Judges a dependency update: merge it, hold it or block it.", writes: "post its verdict on the pull request",
    main: [F("--pr", "Pull request number", "for example 42", {main: 1})]},
  logkeeper: {does: "Turns a decision panel's ruling into a numbered record in the project's docs.", writes: "open a pull request with the record", need: ["--panel"],
    main: [F("--panel", "Decision panel", "the panel's id", {main: 1})]},
  scribe: {does: "Drafts the README and the architecture overview a project is missing, from the facts the survey found. Ask for it on the project's Ready card or with qtdeck docs.", writes: "put the drafts on a new branch (a pull request when there is a repo)",
    main: []},
  bosun: {does: "Walks the project and reports drift: stale branches, dead settings, old to-dos.", writes: "save the report",
    main: [], adv: [F("--stale", "Days before a branch is stale", "60"), F("--todo", "Days before a to-do is old", "90"), {flag: "--again", label: "Report again even if nothing changed", type: "check"}]},
  infra: {does: "Reads a change to infrastructure files and reports what changes, how risky it is and how to undo it.", writes: "post the report on the pull request",
    main: [F("--pr", "Pull request number", "for example 42", {main: 1})], adv: [F("--diff", "Compare with this branch", "for example main")]},
  brief: {does: "Turns an idea, or an issue, into a one-page design brief to read and approve. Builds nothing.", writes: "save the brief as a document", need: ["--idea", "--issue"],
    main: [F("--idea", "The idea, in plain words", "a page for my book swap", {main: 1}), F("--issue", "Issue number", "instead of an idea, for example 17", {main: 1})],
    adv: [F("--for", "Who it is for", "my neighbours"), F("--revise", "Changes to make to a brief", "a sentence"), F("--id", "Brief id", "b2026..."), F("--project", "Project name", "name")]},
  mockup: {does: "Makes one static page per key screen from an approved brief, to look at. Builds no product.", writes: "save the pages in the data folder", main: []},
};

// One plain sentence: the table above, else the duty file's own header line cut at its first full stop.
export function sentence(duty, role){
  if(INFO[duty] && INFO[duty].does) return INFO[duty].does;
  const r = String(role || "").trim();
  const i = r.search(/[.!?](\s|$)/);
  return (i > 0 ? r.slice(0, i + 1) : r) || "Does its job when you run it.";
}

// Every duty name in some group; those in none go to "Other", so a new duty always shows. Names: the duties on the machine, in this order.
export function groupDuties(names){
  const seen = new Set(), out = [];
  for(const g of GROUPS){
    const ds = g.duties.filter(d => names.includes(d));
    ds.forEach(d => seen.add(d));
    if(ds.length) out.push({...g, duties: ds});
  }
  const rest = names.filter(d => !seen.has(d));
  if(rest.length) out.push({...OTHER, duties: rest});
  return out;
}

// All the flags an agent takes, in the order the page has always sent them.
export const flagsOf = duty => { const i = INFO[duty] || {}; return [...(i.main || []), ...(i.adv || [])]; };
const ORDER = {panel: ["--panel", "--target", "--issue", "--question", "--idea", "--brief"], inspector: ["--pr", "--issue"], shipwright: ["--issue", "--plan"]};

// values: {flag: text or true}, extra: free text from Advanced. Returns exactly what /api/run takes: {args, apply}.
export function buildRun(duty, values, apply, extra = ""){
  const flags = flagsOf(duty), order = ORDER[duty] || flags.map(f => f.flag);
  const args = [];
  for(const fl of order){
    const f = flags.find(x => x.flag === fl); if(!f) continue;
    const v = values[fl];
    if(f.type === "check"){ if(v) args.push(fl); }
    else if(v != null && String(v).trim()) args.push(fl, String(v).trim());
  }
  for(const w of String(extra || "").trim().split(/\s+/)) if(w) args.push(w);
  return {args, apply: !!apply};
}

// null when it can run, else what is missing, in words.
export function missing(duty, values){
  const need = (INFO[duty] || {}).need;
  if(!need || need.some(f => values[f] != null && String(values[f]).trim())) return null;
  const names = need.map(f => flagsOf(duty).find(x => x.flag === f)).filter(Boolean).map(f => f.label.toLowerCase());
  return "Fill in " + names.join(" or ") + " first.";
}

// Where an agent stands: running, attention (the last run failed, or its verdict wants a person), idle, never, unbuilt.
// Same reading as the page's verdictClass: a good or neutral verdict is idle; a bad or unfamiliar one needs a look.
const QUIET = new Set(["CLEAN", "MERGED", "OK", "PROVEN", "SYNCED", "FILED", "REPRODUCED", "DRY-RUN", "SKIPPED", "NOT-RED", "NONE", "TAKEN", "NOTHING-TO-BUILD"]);
export function stateOf(a){
  if(a.status === "running") return "running";
  if(a.status === "unbuilt") return "unbuilt";
  if(!a.last_at) return "never";
  return !a.last_verdict || QUIET.has(String(a.last_verdict).toUpperCase()) ? "idle" : "attention";
}
