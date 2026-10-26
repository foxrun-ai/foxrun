#!/usr/bin/env node

/**
 * browser-humanize.js — Anti-detection behavioral helpers for browser automation.
 *
 * Usage:
 *   const h = require('/path/to/browser-humanize.js');
 *   await h.humanDelay();
 *   const vp = h.randomViewport();
 *
 * Test:
 *   node browser-humanize.js --test
 */

// --- Delay helpers ---

/**
 * Returns a promise that resolves after a random delay between min and max ms.
 */
function randomDelay(min = 500, max = 2000) {
  const ms = Math.floor(Math.random() * (max - min + 1)) + min;
  return new Promise((resolve) => setTimeout(resolve, ms));
}

/** Natural-feeling pause between actions (800-2500ms). */
function humanDelay() {
  return randomDelay(800, 2500);
}

/** Short delay between keystrokes (50-150ms). */
function typeDelay() {
  return randomDelay(50, 150);
}

/** Pause after scrolling (300-800ms). */
function scrollDelay() {
  return randomDelay(300, 800);
}

/** Longer pause after page navigation (1500-3500ms). */
function navigationDelay() {
  return randomDelay(1500, 3500);
}

// --- Behavioral helpers ---

/**
 * Returns true ~20% of the time.
 * Use to simulate occasionally browsing non-target pages.
 */
function shouldBrowseExtra() {
  return Math.random() < 0.2;
}

// --- Viewport ---

const BASE_VIEWPORTS = [
  { width: 1366, height: 768 },
  { width: 1440, height: 900 },
  { width: 1536, height: 864 },
  { width: 1920, height: 1080 },
  { width: 1280, height: 720 },
];

/**
 * Returns a random viewport size from common resolutions
 * with slight random variance (+-10-30px) to avoid exact fingerprint matches.
 */
function randomViewport() {
  const base = BASE_VIEWPORTS[Math.floor(Math.random() * BASE_VIEWPORTS.length)];
  const jitter = () => Math.floor(Math.random() * 21) + 10; // 10-30
  const sign = () => (Math.random() < 0.5 ? -1 : 1);
  return {
    width: base.width + sign() * jitter(),
    height: base.height + sign() * jitter(),
  };
}

// --- Mouse path ---

/**
 * Returns an array of {x, y} points following a cubic Bezier curve
 * from (startX, startY) to (endX, endY).
 *
 * The two control points are randomized to create natural-looking arcs.
 * Compatible with agent-browser click commands that accept coordinates.
 */
function humanMousePath(startX, startY, endX, endY, steps = 10) {
  // Generate two random control points offset from the straight line
  const dx = endX - startX;
  const dy = endY - startY;
  const dist = Math.sqrt(dx * dx + dy * dy) || 1;

  // Perpendicular offset range scales with distance (15-40% of distance)
  const offsetRange = dist * (0.15 + Math.random() * 0.25);

  // Control point 1: roughly 1/3 along the path, offset perpendicular
  const cp1x = startX + dx * (0.25 + Math.random() * 0.15) + (Math.random() - 0.5) * offsetRange;
  const cp1y = startY + dy * (0.25 + Math.random() * 0.15) + (Math.random() - 0.5) * offsetRange;

  // Control point 2: roughly 2/3 along the path, offset perpendicular
  const cp2x = startX + dx * (0.6 + Math.random() * 0.15) + (Math.random() - 0.5) * offsetRange;
  const cp2y = startY + dy * (0.6 + Math.random() * 0.15) + (Math.random() - 0.5) * offsetRange;

  const points = [];
  for (let i = 0; i <= steps; i++) {
    const t = i / steps;
    const t2 = t * t;
    const t3 = t2 * t;
    const mt = 1 - t;
    const mt2 = mt * mt;
    const mt3 = mt2 * mt;

    // Cubic Bezier formula: B(t) = (1-t)^3*P0 + 3(1-t)^2*t*P1 + 3(1-t)*t^2*P2 + t^3*P3
    const x = mt3 * startX + 3 * mt2 * t * cp1x + 3 * mt * t2 * cp2x + t3 * endX;
    const y = mt3 * startY + 3 * mt2 * t * cp1y + 3 * mt * t2 * cp2y + t3 * endY;

    points.push({ x: Math.round(x), y: Math.round(y) });
  }

  return points;
}

// --- Exports ---

module.exports = {
  randomDelay,
  humanDelay,
  typeDelay,
  scrollDelay,
  navigationDelay,
  shouldBrowseExtra,
  randomViewport,
  humanMousePath,
};

// --- Self-test ---

if (require.main === module && process.argv.includes('--test')) {
  (async () => {
    console.log('=== browser-humanize self-test ===\n');

    console.log('randomDelay(100, 200):');
    const start = Date.now();
    await randomDelay(100, 200);
    console.log(`  resolved in ${Date.now() - start}ms\n`);

    console.log('shouldBrowseExtra() x10:');
    const results = Array.from({ length: 10 }, () => shouldBrowseExtra());
    console.log(`  ${results.map((r) => (r ? 'Y' : 'N')).join(' ')}\n`);

    console.log('randomViewport() x3:');
    for (let i = 0; i < 3; i++) {
      const vp = randomViewport();
      console.log(`  ${vp.width}x${vp.height}`);
    }
    console.log();

    console.log('humanMousePath(0, 0, 500, 300, 8):');
    const path = humanMousePath(0, 0, 500, 300, 8);
    path.forEach((p, i) => console.log(`  step ${i}: (${p.x}, ${p.y})`));
    console.log();

    console.log('Done.');
  })();
}
