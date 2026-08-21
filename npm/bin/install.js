#!/usr/bin/env node
"use strict";

const { spawnSync } = require("child_process");
const fs = require("fs");
const os = require("os");
const path = require("path");

const REF = process.env.CLIPPER_FLASH_REF || "main";
const RAW_BASE = `https://raw.githubusercontent.com/tahacore/Clipper-Flash/${REF}`;

// NOTE: never call process.exit() while async I/O may be pending - it can
// trip libuv assertion crashes on Windows. Set process.exitCode instead.
function fail(msg) {
  console.error(`\n  !! ${msg}\n`);
  process.exitCode = 1;
}

async function fetchScript(name) {
  const url = `${RAW_BASE}/${name}`;
  let res;
  try {
    res = await fetch(url);
  } catch (e) {
    fail(`network error fetching installer: ${e.message}`);
    return null;
  }
  if (!res.ok) {
    fail(`could not download installer (${res.status} from ${url})`);
    return null;
  }
  return res.text();
}

async function main() {
  console.log("\n  ⚡ Clipper-Flash installer\n");
  console.log("  This sets up everything: uv, Python, FFmpeg, the cf toolkit,");
  console.log("  and installs the skill for Claude Code / Codex.\n");

  const name = process.platform === "win32" ? "install.ps1" : "install.sh";
  const script = await fetchScript(name);
  if (script === null) return;

  const tmp = path.join(os.tmpdir(), `clipper-flash-install-${Date.now()}`);
  const file = process.platform === "win32" ? `${tmp}.ps1` : `${tmp}.sh`;
  fs.writeFileSync(file, script);
  if (process.platform !== "win32") fs.chmodSync(file, 0o755);

  const cmd =
    process.platform === "win32"
      ? spawnSync("powershell", ["-ExecutionPolicy", "Bypass", "-NoProfile", "-File", file], { stdio: "inherit" })
      : spawnSync("bash", [file], { stdio: "inherit" });

  if (cmd.error) {
    fail(`could not launch installer: ${cmd.error.message}`);
    return;
  }
  if (cmd.status !== 0) {
    fail(`installer failed - see output above`);
    return;
  }

  console.log("\n  Next: open Claude Code or Codex and say:");
  console.log('    "Check my channel and clip anything new."\n');
}

main().catch((e) => fail(e.message));
