// A small safe markdown renderer for reading a GitHub card. Pure: text in, HTML string out.
// Everything is escaped before it is placed; no raw HTML is ever passed through. Links keep only http, https and mailto.
// Images are never loaded: they become a plain link carrying their alt text. Issue text is data to show, never instructions.
export const MAX_CHARS = 200000;      // a longer body is cut here and says so
const MAX_INLINE = 2000;              // inline work is done in pieces this long, so no input can make it slow
const MAX_LINE = 4000;
export const OPEN_MARK = "<!-- quarterdeck:requirements -->";
export const CLOSE_MARK = "<!-- /quarterdeck:requirements -->";

const ESC = {"&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;", "`": "&#96;"};
export const esc = s => String(s ?? "").replace(/[&<>"'`]/g, c => ESC[c]);

// Only these three schemes ever become a link. Control characters and spaces inside the address are refused outright.
export function safeUrl(u) {
  const s = String(u ?? "").trim();
  if (!s || s.length > 2000 || /[\u0000-\u0020\u007f-\u009f\u2028\u2029]/.test(s)) return "";
  return /^(https?:\/\/[^\s/]|mailto:[^\s]+)/i.test(s) ? s : "";
}
const link = (url, label) => `<a href="${esc(url)}" target="_blank" rel="noopener noreferrer">${label}</a>`;

const INLINE = new RegExp([
  "`([^`\\n]{1,500})`",                                               // 1 code
  "!\\[([^\\[\\]\\n]{0,200})\\]\\(([^()\\s]{1,2000})(?:\\s+\"[^\"\\n]{0,200}\")?\\)",   // 2 alt, 3 url  (image)
  "\\[([^\\[\\]\\n]{1,200})\\]\\(([^()\\s]{1,2000})(?:\\s+\"[^\"\\n]{0,200}\")?\\)",    // 4 text, 5 url (link)
  "<((?:https?://|mailto:)[^<>\\s]{1,2000})>",                         // 6 autolink
  "(https?://[^\\s<>()\\[\\]]{1,2000})",                               // 7 bare address
  "\\*\\*([^*\\n]{1,500})\\*\\*",                                      // 8 bold
  "__([^_\\n]{1,500})__",                                              // 9 bold
  "~~([^~\\n]{1,500})~~",                                              // 10 struck
  "\\*([^*\\n]{1,500})\\*",                                            // 11 italic
  "(?<![\\w])_([^_\\n]{1,500})_(?![\\w])",                                // 12 italic
].join("|"), "g");

function inlineChunk(t) {
  let out = "", last = 0, m;
  INLINE.lastIndex = 0;
  while ((m = INLINE.exec(t))) {
    out += esc(t.slice(last, m.index));
    last = m.index + m[0].length;
    if (m[1] !== undefined) out += `<code>${esc(m[1])}</code>`;
    else if (m[3] !== undefined) { const u = safeUrl(m[3]); const a = m[2] || "image"; out += u ? link(u, esc("image: " + a)) : esc("image: " + a); }
    else if (m[5] !== undefined) { const u = safeUrl(m[5]); out += u ? link(u, esc(m[4])) : esc(m[4]); }
    else if (m[6] !== undefined) { const u = safeUrl(m[6]); out += u ? link(u, esc(m[6])) : esc(m[0]); }
    else if (m[7] !== undefined) {
      const trail = (m[7].match(/[.,;:!?'"]+$/) || [""])[0];
      const core = m[7].slice(0, m[7].length - trail.length), u = safeUrl(core);
      out += (u ? link(u, esc(core)) : esc(core)) + esc(trail);
    }
    else if (m[8] !== undefined || m[9] !== undefined) out += `<strong>${esc(m[8] ?? m[9])}</strong>`;
    else if (m[10] !== undefined) out += `<s>${esc(m[10])}</s>`;
    else if (m[11] !== undefined || m[12] !== undefined) out += `<em>${esc(m[11] ?? m[12])}</em>`;
  }
  return out + esc(t.slice(last));
}
export function inline(text) {
  const t = String(text ?? "").replace(/<br\s*\/?>/gi, " ");
  let out = "";
  for (let i = 0; i < t.length; i += MAX_INLINE) out += inlineChunk(t.slice(i, i + MAX_INLINE));
  return out;
}

const FENCE = /^ {0,3}(`{3,}|~{3,})\s*([\w+#.-]{0,30})[^\n]*$/;
const HEAD = /^ {0,3}(#{1,6})[ \t]+(.*?)(?:[ \t]+#+)?[ \t]*$/;
const HR = /^ {0,3}([-*_])(?:[ \t]*\1){2,}[ \t]*$/;
const ITEM = /^( *)([-*+]|\d{1,9}[.)])[ \t]+(.*)$/;
const TASK = /^\[([ xX])\][ \t]+(.*)$/;
const TSEP = /^ *\|?[ \t]*:?-{1,}:?[ \t]*(\|[ \t]*:?-{1,}:?[ \t]*)*\|? *$/;

function cells(line) {
  let s = line.trim();
  if (s.startsWith("|")) s = s.slice(1);
  if (s.endsWith("|") && !s.endsWith("\\|")) s = s.slice(0, -1);
  return s.split(/(?<!\\)\|/).map(c => c.replace(/\\\|/g, "|").trim()).slice(0, 20);
}

function renderList(items) {          // items: {indent, ordered, task, text}
  let out = "";
  const stack = [];
  const close = () => { out += "</li></" + (stack.pop().ordered ? "ol" : "ul") + ">"; };
  for (const it of items) {
    while (stack.length && it.indent < stack[stack.length - 1].indent) close();
    let top = stack[stack.length - 1];
    if (top && it.indent === top.indent && it.ordered !== top.ordered) { close(); top = stack[stack.length - 1]; }
    if (top && it.indent === top.indent) out += "</li>";
    else { stack.push({indent: it.indent, ordered: it.ordered}); out += it.ordered ? "<ol>" : "<ul>"; }
    const box = it.task === null ? "" : it.task
      ? `<span class="cb on" aria-label="done">&#9745;</span> ` : `<span class="cb" aria-label="not done">&#9744;</span> `;
    out += `<li${it.task === null ? "" : ' class="task"'}>${box}${inline(it.text)}`;
  }
  while (stack.length) close();
  return out;
}

// HTML comments are dropped (the purser's marks are comments). Done with indexOf so an unterminated run cannot be slow.
function stripComments(s) {
  let out = "", at = 0;
  for (;;) {
    const a = s.indexOf("<!--", at);
    if (a < 0) break;
    const b = s.indexOf("-->", a + 4);
    if (b < 0) break;
    out += s.slice(at, a); at = b + 3;
  }
  return out + s.slice(at);
}

const MAX_DEPTH = 8;   // quotes inside quotes: a few thousand > characters must not recurse that deep
export const renderMarkdown = text => render(text, 0);
function render(text, depth) {
  let src = String(text ?? "");
  let cut = false;
  if (src.length > MAX_CHARS) { src = src.slice(0, MAX_CHARS); cut = true; }
  src = stripComments(src).replace(/\r\n?/g, "\n");
  const lines = src.split("\n").map(l => l.length > MAX_LINE ? l.slice(0, MAX_LINE) + "…" : l);
  const out = [];
  let i = 0;
  const blank = l => !l.trim();
  while (i < lines.length) {
    const l = lines[i];
    if (blank(l)) { i++; continue; }
    let m = FENCE.exec(l);
    if (m) {
      const f = m[1][0], n = m[1].length, buf = [];
      i++;
      while (i < lines.length && !(new RegExp("^ {0,3}" + (f === "`" ? "`" : "~") + "{" + n + ",}\\s*$")).test(lines[i])) buf.push(lines[i++]);
      i++;
      out.push(`<pre><code>${esc(buf.join("\n"))}</code></pre>`);
      continue;
    }
    if ((m = HEAD.exec(l))) { const k = Math.min(6, m[1].length + 1); out.push(`<h${k}>${inline(m[2])}</h${k}>`); i++; continue; }   // card title is the h1, body headings start at h2
    if (HR.test(l)) { out.push("<hr>"); i++; continue; }
    if (l.includes("|") && i + 1 < lines.length && TSEP.test(lines[i + 1]) && lines[i + 1].includes("-") && lines[i + 1].includes("|")) {
      const head = cells(l); i += 2;
      const rows = [];
      while (i < lines.length && !blank(lines[i]) && lines[i].includes("|") && rows.length < 500) rows.push(cells(lines[i++]));
      out.push(`<div class="md-table"><table><thead><tr>${head.map(c => `<th>${inline(c)}</th>`).join("")}</tr></thead><tbody>`
        + rows.map(r => `<tr>${head.map((_, k) => `<td>${inline(r[k] ?? "")}</td>`).join("")}</tr>`).join("") + "</tbody></table></div>");
      continue;
    }
    if (/^ {0,3}>/.test(l)) {
      const buf = [];
      while (i < lines.length && /^ {0,3}>/.test(lines[i])) buf.push(lines[i++].replace(/^ {0,3}> ?/, ""));
      out.push(`<blockquote>${depth >= MAX_DEPTH ? `<p>${esc(buf.join("\n"))}</p>` : render(buf.join("\n"), depth + 1)}</blockquote>`);
      continue;
    }
    if (ITEM.test(l)) {
      const items = [];
      while (i < lines.length && !blank(lines[i])) {
        const im = ITEM.exec(lines[i]);
        if (im) {
          const t = TASK.exec(im[3]);
          items.push({indent: im[1].length >> 1 << 1, ordered: /\d/.test(im[2][0]), task: t ? t[1] !== " " : null, text: t ? t[2] : im[3]});
        } else if (items.length && /^\s+\S/.test(lines[i])) items[items.length - 1].text += " " + lines[i].trim();
        else break;
        i++;
      }
      out.push(renderList(items));
      continue;
    }
    const buf = [];
    while (i < lines.length && !blank(lines[i]) && !FENCE.test(lines[i]) && !HEAD.test(lines[i]) && !HR.test(lines[i]) && !/^ {0,3}>/.test(lines[i]) && !(buf.length && ITEM.test(lines[i]))) buf.push(lines[i++].trim());
    out.push(`<p>${buf.map(inline).join("<br>")}</p>`);
  }
  if (cut) out.push(`<p class="md-note">The rest of this body is not shown here (it is longer than ${Math.round(MAX_CHARS / 1000)} KB).</p>`);
  return out.join("\n");
}

// The purser writes its requirements between two marks. Split them off so they can be shown in their own section.
export function splitRequirements(body) {
  const s = String(body ?? "");
  const a = s.indexOf(OPEN_MARK);
  const b = a < 0 ? -1 : s.indexOf(CLOSE_MARK, a + OPEN_MARK.length);
  if (a < 0 || b < 0) return {main: s, requirements: ""};
  return {main: (s.slice(0, a) + s.slice(b + CLOSE_MARK.length)).trim(), requirements: s.slice(a + OPEN_MARK.length, b).trim()};
}
