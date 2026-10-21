#!/usr/bin/env node
"use strict";
// qtdeck: a thin shim. It finds Python 3.10 or newer, finds the Quarterdeck program, runs bin/qtdeck with your arguments and exits with its status.
// No shell is used (arguments reach the program exactly as typed), the environment is passed through unchanged, and nothing is downloaded or installed.
const {spawnSync} = require("node:child_process");
const fs = require("node:fs");
const os = require("node:os");
const path = require("node:path");

const WANT = [3, 10];

function pythonVersion(cmd) {        // asks the interpreter for its version only; isolated mode runs no project or user code
  const r = spawnSync(cmd, ["-I", "-c", "import sys; print(sys.version_info[0], sys.version_info[1])"], {encoding: "utf8", timeout: 10000});
  if (r.error || r.status !== 0) return null;
  const m = /^(\d+) (\d+)\s*$/.exec(r.stdout || "");
  return m ? [Number(m[1]), Number(m[2])] : null;
}
const newEnough = v => v && (v[0] > WANT[0] || (v[0] === WANT[0] && v[1] >= WANT[1]));

function findPython(env) {
  const tries = [env.QUARTERDECK_PYTHON, "python3", "python"].filter(Boolean);
  for (const cmd of tries) if (newEnough(pythonVersion(cmd))) return cmd;
  return null;
}

function hasProgram(dir) { return !!dir && fs.existsSync(path.join(dir, "bin", "qtdeck")); }
function findApp(env) {
  const here = path.resolve(__dirname, "..");
  const tries = [env.QUARTERDECK_APP, path.join(here, "app"), path.resolve(here, "..", "..")];     // an override, the package's own app folder, then a clone
  return tries.find(hasProgram) || null;
}

function fail(a, b) { process.stderr.write(a + "\n" + b + "\n"); process.exit(127); }

function main() {
  const env = process.env;
  const python = findPython(env);
  if (!python) fail("qtdeck needs Python 3.10 or newer, and none was found.", "Install it (macOS: brew install python@3.12; Debian or Ubuntu: sudo apt-get install python3), or set QUARTERDECK_PYTHON to one, then run qtdeck again.");
  const app = findApp(env);
  if (!app) fail("qtdeck could not find its program files.", "Reinstall with: npm install -g qtdeck, or set QUARTERDECK_APP to a Quarterdeck folder.");
  // The program runs `python3`. If the interpreter chosen is not what python3 means on this machine, a one-entry folder in front of PATH says so; otherwise nothing is changed.
  let runEnv = env, tmp = null;
  if (python !== "python3") {
    const real = spawnSync(python, ["-I", "-c", "import sys; print(sys.executable)"], {encoding: "utf8"}).stdout.trim();
    if (real) {
      tmp = fs.mkdtempSync(path.join(os.tmpdir(), "qtdeck-py-"));
      fs.symlinkSync(real, path.join(tmp, "python3"));
      runEnv = {...env, PATH: tmp + path.delimiter + (env.PATH || "")};
    }
  }
  const r = spawnSync("bash", [path.join(app, "bin", "qtdeck"), ...process.argv.slice(2)], {stdio: "inherit", env: runEnv});
  if (tmp) { try { fs.rmSync(tmp, {recursive: true, force: true}); } catch (e) { /* a leftover temp folder is harmless */ } }
  if (r.error) fail("qtdeck could not start its program (" + r.error.code + ").", "It needs bash. Check that bash is installed.");
  if (r.status === null) process.exit(128 + (os.constants.signals[r.signal] || 1));
  process.exit(r.status);
}
main();
