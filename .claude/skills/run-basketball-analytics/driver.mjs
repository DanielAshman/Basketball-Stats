#!/usr/bin/env node
// Driver for the run-basketball-analytics skill.
// Usage (from the repo root, i.e. basketball-analytics/):
//   node .claude/skills/run-basketball-analytics/driver.mjs up      # start docker stack + vite dev server
//   node .claude/skills/run-basketball-analytics/driver.mjs smoke   # drive the running app, screenshot, check console
//   node .claude/skills/run-basketball-analytics/driver.mjs down    # stop vite + docker stack
//   node .claude/skills/run-basketball-analytics/driver.mjs         # up -> smoke, leaves the stack running
//
// Requires `npm install` once inside this skill directory (installs playwright)
// and `npx playwright install chromium` once (downloads the browser binary).

import { execSync, spawn } from 'node:child_process';
import { existsSync, mkdirSync } from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const SKILL_DIR = path.dirname(fileURLToPath(import.meta.url));
const REPO_ROOT = path.resolve(SKILL_DIR, '../../..'); // .claude/skills/run-basketball-analytics -> repo root
const BACKEND_URL = 'http://localhost:8000';
const FRONTEND_URL = 'http://localhost:5173';
const SCREENSHOT_DIR = path.join(SKILL_DIR, 'screenshots');

function sh(cmd, opts = {}) {
  console.log(`$ ${cmd}`);
  return execSync(cmd, { stdio: 'inherit', cwd: REPO_ROOT, ...opts });
}

async function waitFor(url, timeoutMs = 60_000) {
  const start = Date.now();
  while (Date.now() - start < timeoutMs) {
    try {
      const res = await fetch(url);
      if (res.ok) return true;
    } catch {
      // not up yet
    }
    await new Promise((r) => setTimeout(r, 1000));
  }
  throw new Error(`Timed out waiting for ${url}`);
}

async function cmdUp() {
  // Docker Desktop must be running for `docker info` to succeed.
  try {
    execSync('docker info', { stdio: 'ignore' });
  } catch {
    console.log('Docker daemon not reachable, launching Docker Desktop...');
    sh('open -a Docker');
    const start = Date.now();
    while (Date.now() - start < 60_000) {
      try {
        execSync('docker info', { stdio: 'ignore' });
        break;
      } catch {
        await new Promise((r) => setTimeout(r, 2000));
      }
    }
  }

  sh('docker-compose up -d --build');
  console.log(`Waiting for backend health at ${BACKEND_URL}/health ...`);
  await waitFor(`${BACKEND_URL}/health`);
  console.log('Backend healthy.');

  // Start the Vite dev server in the background if it isn't already serving.
  try {
    const res = await fetch(FRONTEND_URL);
    if (res.ok) {
      console.log('Frontend already running.');
      return;
    }
  } catch {
    // not running, fall through to start it
  }

  console.log('Starting frontend (vite dev server)...');
  const child = spawn('npm', ['run', 'dev', '--', '--port', '5173'], {
    cwd: path.join(REPO_ROOT, 'frontend'),
    detached: true,
    stdio: 'ignore',
  });
  child.unref();

  console.log(`Waiting for frontend at ${FRONTEND_URL} ...`);
  await waitFor(FRONTEND_URL);
  console.log('Frontend serving.');
}

async function cmdDown() {
  try {
    sh("lsof -ti:5173 -sTCP:LISTEN | xargs -r kill");
  } catch {
    // nothing listening, fine
  }
  sh('docker-compose down');
}

async function cmdSmoke() {
  const { chromium } = await import('playwright');
  mkdirSync(SCREENSHOT_DIR, { recursive: true });

  const browser = await chromium.launch();
  const page = await browser.newPage();
  const consoleErrors = [];
  page.on('console', (msg) => {
    if (msg.type() === 'error') consoleErrors.push(msg.text());
  });
  page.on('pageerror', (err) => consoleErrors.push(String(err)));

  console.log(`Navigating to ${FRONTEND_URL} ...`);
  await page.goto(FRONTEND_URL, { waitUntil: 'networkidle', timeout: 30_000 });
  await page.waitForSelector('text=Basketball Analytics');
  await page.screenshot({ path: path.join(SCREENSHOT_DIR, '1-video-upload.png'), fullPage: true });

  console.log('Switching to Live Game Entry tab...');
  await page.click('text=Live Game Entry');
  await page.waitForSelector('text=Start a live game');

  const suffix = Date.now();
  await page.fill('input[placeholder="vs. Eastside Warriors"]', `Smoke Test Game ${suffix}`);
  await page.fill('input[type="date"]', '2026-09-07');
  await page.click('button:has-text("Start game")');

  console.log('Waiting for roster screen (game created via backend API)...');
  await page.waitForSelector('text=Roster', { timeout: 15_000 });

  console.log('Adding a player and recording an event...');
  const jerseyInput = page.locator('input[type="number"]');
  await jerseyInput.fill('23');
  await page.click('button:has-text("Add to roster")');
  await page.waitForSelector('text=#23');
  await page.click('button:has-text("2 Pointer")');
  await page.waitForSelector('text=2 Pointer >> nth=1'); // activity log entry, distinct from the button

  await page.screenshot({ path: path.join(SCREENSHOT_DIR, '2-live-game-entry.png'), fullPage: true });

  await browser.close();

  console.log('\n--- Smoke test result ---');
  console.log('Screenshots:', SCREENSHOT_DIR);
  if (consoleErrors.length > 0) {
    console.log('CONSOLE ERRORS:');
    for (const e of consoleErrors) console.log(' -', e);
    process.exitCode = 1;
  } else {
    console.log('No console errors. PASS.');
  }
}

const command = process.argv[2] ?? 'default';

switch (command) {
  case 'up':
    await cmdUp();
    break;
  case 'down':
    await cmdDown();
    break;
  case 'smoke':
    await cmdSmoke();
    break;
  case 'default':
    await cmdUp();
    await cmdSmoke();
    break;
  default:
    console.error(`Unknown command: ${command} (expected up|smoke|down)`);
    process.exit(1);
}
