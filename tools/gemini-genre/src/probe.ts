/**
 * Diagnostic: open the Gem with the saved profile and report what's on the page,
 * so the selectors in gemini.ts can be fixed against the real DOM.
 *
 *   npx tsx src/probe.ts
 */
import { chromium } from "playwright";
import { loadConfig } from "./config.ts";

const CANDIDATES = [
  "rich-textarea",
  "div.ql-editor",
  'div.ql-editor[contenteditable="true"]',
  '[contenteditable="true"]',
  '[contenteditable="true"][role="textbox"]',
  "textarea",
  "button.send-button",
  'button[aria-label*="Send" i]',
  'button[aria-label*="送信" i]',
  'button[aria-label*="prompt" i]',
  "message-content",
  ".model-response-text",
  "input-area-v2",
  ".input-area",
  "bard-mode-switcher",
];

const sleep = (ms: number) => new Promise((r) => setTimeout(r, ms));

async function main() {
  const cfg = loadConfig(process.argv);
  const ctx = await chromium.launchPersistentContext(cfg.userDataDir, {
    headless: false,
    channel: cfg.useChrome ? "chrome" : undefined,
    viewport: { width: 1280, height: 900 },
    locale: "ja-JP",
    args: ["--disable-blink-features=AutomationControlled"],
  });
  const page = ctx.pages()[0] ?? (await ctx.newPage());
  console.log("goto", cfg.gemUrl);
  await page.goto(cfg.gemUrl, { waitUntil: "domcontentloaded" });
  await sleep(6000);

  console.log("\nurl   :", page.url());
  console.log("title :", await page.title());

  const signedIn = await page
    .locator('a[aria-label*="Google アカウント" i], a[aria-label*="Google Account" i], img.gb_A, [data-ogsr-up]')
    .first()
    .isVisible()
    .catch(() => false);
  console.log("signed-in widget visible:", signedIn);

  console.log("\nselector hits:");
  for (const sel of CANDIDATES) {
    const n = await page.locator(sel).count().catch(() => -1);
    let sample = "";
    if (n > 0) {
      const el = page.locator(sel).first();
      const aria = (await el.getAttribute("aria-label").catch(() => null)) ?? "";
      const cls = (await el.getAttribute("class").catch(() => null)) ?? "";
      const tag = await el.evaluate((e) => e.tagName.toLowerCase()).catch(() => "?");
      sample = `  <${tag} class="${cls.slice(0, 60)}" aria-label="${aria.slice(0, 40)}">`;
    }
    console.log(`  ${String(n).padStart(3)}  ${sel}${sample}`);
  }

  // Dump the editable region's surrounding markup, if any.
  const editable = page.locator('[contenteditable="true"], textarea').first();
  if (await editable.count()) {
    const html = await editable
      .evaluate((e) => (e.closest("form,div[class],section") ?? e).outerHTML.slice(0, 1200))
      .catch(() => "");
    console.log("\neditable container markup:\n", html);
  } else {
    console.log("\nno contenteditable/textarea found — dumping <main> skeleton:");
    const main = await page
      .locator("main, body")
      .first()
      .evaluate((e) =>
        Array.from(e.querySelectorAll("*"))
          .slice(0, 40)
          .map((n) => n.tagName.toLowerCase() + (n.className ? "." + String(n.className).split(" ")[0] : ""))
          .join("\n"),
      )
      .catch(() => "");
    console.log(main);
  }

  console.log("\nleaving the window open 60s for inspection…");
  await sleep(60_000);
  await ctx.close();
}

main().catch((e) => {
  console.error(e);
  process.exit(1);
});
