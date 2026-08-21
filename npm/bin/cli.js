#!/usr/bin/env node
"use strict";

// `npx clipper-flash` entry point: runs the full installer.
// The actual toolkit is the `cf` command installed by the installer.

if (process.argv.includes("--help") || process.argv.includes("-h")) {
  console.log(`
  ⚡ Clipper-Flash — turn YouTube livestreams into Shorts with your AI agent.

  Usage:
    npx clipper-flash          run the full installer (uv, Python, FFmpeg, cf, skill)

  After installing, use the "cf" command or just ask your agent:
    "Check my channel and clip anything new."

  Docs: https://github.com/tahacore/Clipper-Flash
`);
  process.exit(0);
}

require("./install.js");
