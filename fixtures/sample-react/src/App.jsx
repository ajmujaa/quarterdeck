import React, { useState } from "react";
import { addTodo, toggleTodo, removeTodo, remaining } from "./todos.js";

export default function App() {
  const [todos, setTodos] = useState([]);
  const [text, setText] = useState("");

  function submit(event) {
    event.preventDefault();
    setTodos(addTodo(todos, text));
    setText("");
  }

  return (
    <main>
      <h1>Todos</h1>
      <form onSubmit={submit}>
        <input aria-label="New todo" value={text} onChange={(e) => setText(e.target.value)} />
        <button type="submit">Add</button>
      </form>
      <ul>
        {todos.map((t) => (
          <li key={t.id}>
            <label>
              <input type="checkbox" checked={t.done} onChange={() => setTodos(toggleTodo(todos, t.id))} />
              <span style={{ textDecoration: t.done ? "line-through" : "none" }}>{t.text}</span>
            </label>
            <button onClick={() => setTodos(removeTodo(todos, t.id))}>Remove</button>
          </li>
        ))}
      </ul>
      <p>{remaining(todos)} left</p>
    </main>
  );
}
