// route.js: the page's address, as a pure module. No DOM, no globals, nothing that can throw.
//
// The address holds where the owner is: the page, the project scope and the open mission.
//
//   #/home/overview                      Home
//   #/brain/map   #/brain/rhythm         the Brain, in either mode
//   #/projects/<view>                    projects inbox missions prs board ledger timeline operations spend log
//   #/projects/projects                  the overview of every project, or (with ?project=) the one project's page
//   #/projects/mission[/<id>]            one mission (the id is encodeURIComponent encoded: cycle%3Aabc)
//   #/projects/log[/<project>~<duty>]    the open log (a system log: /~<name>)
//   #/agents/<view>  #/connections/connections  #/library/<view>  #/settings/settings
//   #/addon/<place>[/<view>]             an add-on's place and its pages
//   ...?project=<name>                   the project scope (absent: all projects)
//   #/projects/inbox?addon=<name>        the add-on scope (Needs you shows only that add-on's items)
//   #/work/...                           the old name of the Projects place: every address made before it was renamed opens the same page
//                                        (the page rewrites it to #/projects/... with replaceState)
//
// The hash is untrusted input: anyone can paste anything after the #. parseHash checks every part against `known`, the names the
// page actually has, and gives the default route (Home) for anything else. It never throws, and it never returns text that did not
// come from `known`, except a mission id or a log id, which are checked for shape and are only ever put in a request as data or shown
// through esc().
//
//   known = {groups: [{id, views: [...]}],      the page's NAV_GROUPS
//            projects: [name],                  the registered projects
//            addons: [name],                    the installed add-ons
//            places: {placeId: [viewId]},       the add-ons' places and the pages of each
//            brainModes: ["map", "rhythm"]}     optional

export const MAX_HASH = 300;
const RAW = /^#[A-Za-z0-9\-._~!$&'()*+,;=:@/?%]*$/;          // what encodeURIComponent and the route table can produce; a raw space, quote, angle bracket or non-ASCII letter is not ours
const BAD_CHAR = /[\u0000-\u001f\u007f<>"`\\]|[\ud800-\udbff](?![\udc00-\udfff])|(?<![\ud800-\udbff])[\udc00-\udfff]/;   // a decoded value never holds a control character, a character that closes markup or half of a surrogate pair
const MISSION_ID = /^[a-z]{2,12}:[^]{1,190}$/;                 // fix:<panel>#<n>  panel:<id>  run:<at>|<project>|<duty>  attn:<id>  cycle:<id>  brief:<id>  plan:<id>
const LOG_ID = /^[^~]{0,80}~[^~]{1,80}$/;                       // <project>~<duty>; a system log has no project: ~<name>
const VIRTUAL = {projects: ["mission", "log"]};                    // pages of a group that are not in its tab list, or that take an id
const WITH_ID = {mission: validMissionId, log: validLogId};
const GROUP_ALIAS = {work: "projects"};                         // the place that was called Work; an alias only when the page has no group of that name

export const defaultRoute = () => ({ok: false, group: "home", view: "overview", id: "", project: "", addon: "", brain: ""});

export function validMissionId(id) { return typeof id === "string" && id.length <= 200 && MISSION_ID.test(id) && !BAD_CHAR.test(id); }
export function validLogId(id) { return typeof id === "string" && LOG_ID.test(id) && !BAD_CHAR.test(id); }

const dec = s => { try { const v = decodeURIComponent(s); return BAD_CHAR.test(v) ? null : v; } catch (e) { return null; } };
const has = (list, x) => Array.isArray(list) && list.some(y => y === x);

function query(q) {                                           // "project=x&addon=y" -> {project, addon} or null when malformed
  const out = {};
  if (q === "") return out;
  for (const part of q.split("&")) {
    const i = part.indexOf("=");
    if (i < 1) return null;
    const k = part.slice(0, i), v = dec(part.slice(i + 1));
    if ((k !== "project" && k !== "addon") || v === null || v === "" || k in out) return null;
    out[k] = v;
  }
  return out;
}

export function parseHash(hash, known) {
  try {
    if (typeof hash !== "string" || hash.length > MAX_HASH || !RAW.test(hash) || !known || typeof known !== "object") return defaultRoute();
    const body = hash.slice(1);
    if (body[0] !== "/") return defaultRoute();
    const qi = body.indexOf("?");
    const path = qi < 0 ? body.slice(1) : body.slice(1, qi);
    const q = query(qi < 0 ? "" : body.slice(qi + 1));
    if (q === null || (q.project && q.addon)) return defaultRoute();
    const segs = path.split("/").map(dec);
    if (segs.length < 2 || segs.length > 3 || segs.some(s => s === null || s === "")) return defaultRoute();
    let [g, v, id] = segs;
    if (Object.hasOwn(GROUP_ALIAS, g) && !(known.groups || []).some(x => x && x.id === g)) g = GROUP_ALIAS[g];
    const r = defaultRoute(); r.ok = true;
    if (g === "addon") {                                       // an add-on's own place: it has no project scope
      const views = known.places && Object.hasOwn(known.places, v) ? known.places[v] : null;
      if (!views || q.project || q.addon) return defaultRoute();
      if (id !== undefined && !has(views, id)) return defaultRoute();
      return Object.assign(r, {group: "addon", view: id === undefined ? v : id, addon: v});
    }
    const group = (known.groups || []).find(x => x && x.id === g);
    if (!group) return defaultRoute();
    r.group = g;
    if (g === "brain") {
      if (id !== undefined || !has(known.brainModes || ["map", "rhythm"], v)) return defaultRoute();
      r.view = "brain"; r.brain = v;
    } else if (has(group.views, v) || has(VIRTUAL[g], v)) {
      r.view = v;
      if (id !== undefined) { if (!Object.hasOwn(WITH_ID, v) || !WITH_ID[v](id)) return defaultRoute(); r.id = id; }
    } else return defaultRoute();
    if (q.project) { if (!has(known.projects, q.project)) return defaultRoute(); r.project = q.project; }
    if (q.addon) { if (!has(known.addons, q.addon) || r.view !== "inbox") return defaultRoute(); r.addon = q.addon; }
    return r;
  } catch (e) {
    return defaultRoute();
  }
}

// The inverse. state = {group, view, id, project, addon, brain, place}. `place` (an add-on's place) wins over group.
// What cannot be written safely is left out (a bad mission id), and a state that cannot be written at all gives Home.
export function buildHash(state) {
  try {
    const s = state && typeof state === "object" ? state : {};
    const e = encodeURIComponent, str = x => typeof x === "string" ? x : "";
    let path;
    if (str(s.place)) {
      path = "/addon/" + e(s.place) + (str(s.view) && s.view !== s.place ? "/" + e(s.view) : "");
      return fit("#" + path);
    }
    const g = str(s.group), v = str(s.view);
    if (!g || !v) return "#/home/overview";
    if (g === "brain") path = "/brain/" + e(str(s.brain) || "map");
    else {
      path = "/" + e(g) + "/" + e(v);
      if (str(s.id) && Object.hasOwn(WITH_ID, v) && WITH_ID[v](s.id)) path += "/" + e(s.id);
    }
    const q = str(s.project) ? "?project=" + e(s.project) : str(s.addon) ? "?addon=" + e(s.addon) : "";
    return fit("#" + path + q);
  } catch (err) {
    return "#/home/overview";
  }
}
const fit = h => h.length <= MAX_HASH ? h : "#/home/overview";

// A hash that is the one-time pairing link, never a route.
export const isPairHash = h => typeof h === "string" && /^#pair=/.test(h);
