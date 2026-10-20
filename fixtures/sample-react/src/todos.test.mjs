// Written for Node's own test runner, so the logic can be checked offline: `node --test`
import test from "node:test";
import assert from "node:assert/strict";
import { addTodo, toggleTodo, removeTodo, remaining } from "./todos.js";

test("addTodo adds an open item with the next id", () => {
  const list = addTodo(addTodo([], "milk"), "bread");
  assert.deepEqual(list, [
    { id: 1, text: "milk", done: false },
    { id: 2, text: "bread", done: false },
  ]);
});

test("addTodo ignores empty text", () => {
  assert.deepEqual(addTodo([], "   "), []);
});

test("toggleTodo flips one item and leaves the others", () => {
  const list = toggleTodo(addTodo(addTodo([], "a"), "b"), 2);
  assert.deepEqual(list.map((t) => t.done), [false, true]);
});

test("removeTodo drops one item", () => {
  const list = removeTodo(addTodo(addTodo([], "a"), "b"), 1);
  assert.deepEqual(list.map((t) => t.text), ["b"]);
});

test("remaining counts the open items", () => {
  const list = toggleTodo(addTodo(addTodo([], "a"), "b"), 1);
  assert.equal(remaining(list), 1);
});
