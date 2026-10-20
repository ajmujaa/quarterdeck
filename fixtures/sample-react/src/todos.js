// The pure logic of the todo list. No React in here, so it can be checked with `node --test` and nothing installed.

export function addTodo(todos, text) {
  const clean = String(text).trim();
  if (!clean) return todos;
  const id = todos.reduce((top, t) => Math.max(top, t.id), 0) + 1;
  return [...todos, { id, text: clean, done: false }];
}

export function toggleTodo(todos, id) {
  return todos.map((t) => (t.id === id ? { ...t, done: !t.done } : t));
}

export function removeTodo(todos, id) {
  return todos.filter((t) => t.id !== id);
}

export function remaining(todos) {
  return todos.filter((t) => !t.done).length;
}
