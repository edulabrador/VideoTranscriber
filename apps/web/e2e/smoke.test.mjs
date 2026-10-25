// Browser test of the real app: backend API (simulated models) + built frontend.
// Run `pnpm build` first, then `pnpm e2e`. Needs uv, FFmpeg and Playwright's Chromium.
import assert from "node:assert/strict";
import { spawn, spawnSync } from "node:child_process";
import { mkdtempSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { dirname, join, resolve } from "node:path";
import { after, before, test } from "node:test";
import { fileURLToPath } from "node:url";

import { chromium } from "playwright";

const web = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const repo = resolve(web, "..", "..");
const work = mkdtempSync(join(tmpdir(), "videotranscriber-e2e-"));
const children = [];
let browser;
let page;

function start(command, args, options) {
  const child = spawn(command, args, {
    stdio: ["ignore", "inherit", "inherit"],
    ...options,
  });
  children.push(child);
  return child;
}

async function waitFor(url) {
  for (let attempt = 0; attempt < 240; attempt += 1) {
    try {
      if ((await fetch(url)).ok) return;
    } catch {
      /* not listening yet */
    }
    await new Promise((done) => setTimeout(done, 500));
  }
  throw new Error(`${url} did not start`);
}

before(async () => {
  const tone = spawnSync("ffmpeg", [
    "-loglevel",
    "error",
    "-f",
    "lavfi",
    "-i",
    "sine=frequency=330:duration=30",
    join(work, "reunion.wav"),
  ]);
  assert.equal(tone.status, 0, "FFmpeg is required");
  start(
    "uv",
    ["run", "--project", "backend", "python", "scripts/e2e_server.py"],
    {
      cwd: repo,
      env: {
        ...process.env,
        OUTPUT_DIR: join(work, "output"),
        TEMP_DIR: join(work, "temp"),
        HISTORY_FILE: join(work, "history.json"),
        MODELS_DIR: join(work, "models"),
        COBALT_API_URL: "",
      },
    },
  );
  start(
    "pnpm",
    [
      "exec",
      "vite",
      "preview",
      "--host",
      "127.0.0.1",
      "--port",
      "5187",
      "--strictPort",
    ],
    {
      cwd: web,
    },
  );
  await waitFor("http://127.0.0.1:8187/api/health");
  await waitFor("http://127.0.0.1:5187/");
  browser = await chromium.launch(
    process.env.PLAYWRIGHT_CHROMIUM
      ? { executablePath: process.env.PLAYWRIGHT_CHROMIUM }
      : {},
  );
  page = await browser.newPage({ viewport: { width: 1280, height: 1000 } });
});

after(async () => {
  await browser?.close();
  for (const child of children) child.kill();
  rmSync(work, { recursive: true, force: true });
});

test("upload, speakers, playback, search, editing, summary and library", async () => {
  const errors = [];
  page.on("pageerror", (error) => errors.push(error.message));
  await page.goto("http://127.0.0.1:5187/");

  await page.getByText("Opciones avanzadas").click();
  await page.getByLabel(/Identificar quién habla/).check();
  await page.getByLabel("Número de hablantes").selectOption("2");
  await page.getByRole("tab", { name: "Subir archivo" }).click();
  await page
    .locator("input[type=file]")
    .setInputFiles(join(work, "reunion.wav"));

  await page.waitForSelector("#transcript", { timeout: 60_000 });
  assert.match(
    await page.locator(".transcript-metadata").innerText(),
    /2 hablantes/,
  );
  assert.equal(
    await page.locator(".speaker-label").first().innerText(),
    "Hablante 1",
  );
  assert.equal(await page.locator(".export-actions a").count(), 5);

  // The audio copy plays and a timestamp seeks to its segment.
  await page.waitForFunction(
    () => document.querySelector("audio")?.readyState >= 1,
  );
  await page.locator("button.timestamp").nth(2).click();
  await page.waitForFunction(
    () => document.querySelector("audio").currentTime >= 10,
  );
  await page.waitForSelector(".segment.playing");
  await page.evaluate(() => document.querySelector("audio").pause());

  // Search counts and highlights matches.
  await page.getByLabel("Buscar en la transcripción").fill("número 3");
  assert.equal(await page.locator(".match-count").innerText(), "1 de 1");
  assert.equal(await page.locator(".transcript-text mark").count(), 1);
  await page.getByLabel("Buscar en la transcripción").fill("");

  // Corrections and speaker names are saved and reach the exports.
  await page.getByRole("button", { name: /Corregir texto/ }).click();
  await page.getByLabel("Nombre para Hablante 1").fill("Ana");
  await page.getByLabel("Texto en 0:00").fill("Bienvenidos a la reunión.");
  await page.getByRole("button", { name: /Guardar cambios/ }).click();
  await page.waitForSelector("text=Corregida");
  assert.equal(await page.locator(".speaker-label").first().innerText(), "Ana");
  const jobId = await page.evaluate(() =>
    localStorage.getItem("videotranscriber-job-id"),
  );
  const txt = await (
    await fetch(`http://127.0.0.1:8187/api/jobs/${jobId}/download/txt`)
  ).text();
  assert.match(txt, /^Ana: Bienvenidos a la reunión\./);

  // Local summary through the (simulated) Ollama server.
  await page
    .getByRole("button", { name: /Resumir con modelo-de-prueba/ })
    .click();
  await page.waitForSelector(".summary-text");
  assert.match(await page.locator(".summary-text").innerText(), /presupuesto/);
  assert.equal(
    await page.locator(".summary-text h4").first().innerText(),
    "Resumen",
  );
  assert.equal(await page.locator(".export-actions a").count(), 6);

  if (process.env.E2E_SCREENSHOTS) {
    await page.screenshot({
      path: join(process.env.E2E_SCREENSHOTS, "transcript.png"),
      fullPage: true,
    });
  }

  // The library lists the result with the corrected preview, and fits a phone screen.
  assert.equal(await page.locator(".library-item").count(), 1);
  await page.waitForFunction(() =>
    document.querySelector(".library-preview")?.textContent?.startsWith("Ana:"),
  );
  await page.setViewportSize({ width: 390, height: 900 });
  assert.equal(
    await page.evaluate(
      () => document.documentElement.scrollWidth > window.innerWidth,
    ),
    false,
  );
  if (process.env.E2E_SCREENSHOTS) {
    await page.screenshot({
      path: join(process.env.E2E_SCREENSHOTS, "mobile.png"),
      fullPage: true,
    });
  }
  assert.deepEqual(errors, []);
});
