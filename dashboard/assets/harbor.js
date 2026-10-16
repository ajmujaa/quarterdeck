// Harbor map: the order of the berths. Pure; no DOM, no clock. There is no position or lane data, so berths are an ordered row:
// blocked first, then waiting for you, then running, then idle; by name inside each state.
const RANK = {blocked: 0, awaiting: 1, running: 2, idle: 3};
export function berthOrder(items) {
  return items.slice().sort((a, b) => (RANK[a.st] ?? 9) - (RANK[b.st] ?? 9) || String(a.name).localeCompare(String(b.name)));
}
