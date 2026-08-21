#!/usr/bin/env node
"use strict";

const { spawnSync } = require("child_process");
const fs = require("fs");
const os = require("os");
const path = require("path");

const REF = process.env.CLIPPER_FLASH_REF || "main";
const RAW_BASE = `https://raw.githubusercontent.com/tahacore/Clipper-Flash/${REF}`;

function fail(msg) {
  console.error(`\n  !! ${msg}`);
  process.exit(1);
}

async function fetchScript(name) {
  const url = `${RAW_BASE}/${name}`;
  const res = await fetch(url);
  if (!res.ok) fail(`could not download installer (${res.status} from ${url})`);
  return res.text();
}

async function main() {
  console.log("\n  ⚡ Clipper-Flash installer\n");
  console.log("  This sets up everything: uv, Python, FFmpeg, the cf toolkit,");
  console.log("  and installs the skill for Claude Code / Codex.\n");

  const tmp = path.join(os.tmpdir(), `clipper-flash-install-${Date.now()}`);

  if (process.platform === "win32") {
    const script = await fetchScript("install.ps1");
    const file = `${tmp}.ps1`;
    fs.writeFileSync(file, script);
    const r = spawnSync(
      "powershell",
      ["-ExecutionPolicy", "Bypass", "-NoProfile", "-File", file],
      { stdio: "inherit" }
    );
    if (r.status !== 0) fail("installer failed - see output above");
  } else {
    const script = await fetchScript("install.sh");
    const file = `${tmp}.sh`;
    fs.writeFileSync(file, script);
    fs.chmodSync(file, 0o755);
    const r = spawnSync("bash", [file], { stdio: "inherit" });
    if (r.status !== 0) fail("installer failed - see output above");
  }

  console.log("\n  Next: open Claude Code or Codex and say:");
  console.log('    "Check my channel and clip anything new."\n');
}

main().catch((e) => fail(e.message));
