// Pure logic for Helm's conversation memory and for deciding what an utterance is. No DOM, no network.
// The page keeps the memory and sends it with every request, so the server holds no hidden state.

export const MAX_TURNS = 12;
export const IDLE_MS = 30 * 60 * 1000;
const MAX_CHARS = 600;          // one remembered turn is cut to this

export const emptyMemory = () => ({turns: [], last: 0, deep: false, include: {agenda: false, notes: false}});

const cut = s => { s = String(s == null ? "" : s).replace(/\s+/g, " ").trim(); return s.length > MAX_CHARS ? s.slice(0, MAX_CHARS - 1) + "…" : s; };

// Silence for 30 minutes forgets the conversation (and switches the deep brain and any "include" off with it).
export function expire(mem, now = Date.now()) {
  return mem && mem.last && now - mem.last > IDLE_MS ? emptyMemory() : (mem || emptyMemory());
}

// Remember one turn ("user" or "assistant"); only the newest MAX_TURNS are kept. Returns a new memory.
// src says where the turn came from: "chat" (a conversation exchange) or "cmd" (a command and its answer, which can
// carry an agenda or note text). Only "chat" turns may ever be sent to Claude.
export function push(mem, role, content, now = Date.now(), src = "cmd") {
  const m = expire(mem, now), text = cut(content);
  if (!text || (role !== "user" && role !== "assistant")) return m;
  return {...m, last: now, turns: [...m.turns, {role, content: text, src: src === "chat" ? "chat" : "cmd"}].slice(-MAX_TURNS)};
}

// What is sent with a request: roles, words and where each turn came from.
export const forRequest = mem => (mem && mem.turns || []).map(t => ({role: t.role, content: t.content, src: t.src === "chat" ? "chat" : "cmd"}));

// Imperative openings that mean "do something", so that a classifier "clarify" about one of these stays a
// question about the command and does not become small talk.
const COMMAND_START = /^(?:start|begin|analy[sz]e|run|stop|halt|kill|cancel|pause|resume|trigger|plan|draft|turn|make|promote|convert|mark|finish|close|complete|dismiss|acknowledge|ack|clear|open|show|go|switch|find|search|review|remember|note|jot|capture|restart|list|read|brief|merge|delete|remove)\b/;
export function looksLikeCommand(text) {
  const t = String(text || "").toLowerCase().replace(/^(?:hey |ok |okay )?(?:helm|quarterdeck)[ ,]*/, "").replace(/^(?:please |can you |could you )+/, "").trim();
  return COMMAND_START.test(t) || /\b(?:issue|note|pull request|pr) #?\d+\b/.test(t);
}

// Which way an utterance goes, given what the fixed phrases and the local classifier made of it:
//   "command"      a command Helm understands
//   "conversation" chit-chat, a question, "what do you think": the conversation brain answers
//   "unknown"      nothing understood it and the classifier was unavailable, so the old "I did not catch" reply
// A command always beats conversation; only "none" or a "clarify" that is not about a command becomes conversation.
export function route(cmd, text) {
  const i = cmd && cmd.intent;
  if (i === "talk" || i === "none") return "conversation";
  if (i === "clarify") return looksLikeCommand(text) ? "command" : "conversation";
  if (i === "unknown") return "unknown";
  return "command";
}
