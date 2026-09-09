import { chromium } from "playwright";
import type { BrowserContext, Locator, Page } from "playwright";
import type { Config } from "./config.ts";

// Selectors confirmed against gemini.google.com/gem/* (JP locale), 2026-08.
const COMPOSER = [
  'div.ql-editor[contenteditable="true"]',
  'rich-textarea div[contenteditable="true"]',
  '[contenteditable="true"][role="textbox"]',
].join(", ");

const SEND = [
  'button[aria-label*="送信" i]',
  'button[aria-label*="Send" i]',
  "button.send-button",
].join(", ");

const STOP = [
  'button[aria-label*="停止" i]',
  'button[aria-label*="Stop" i]',
  'button[aria-label*="回答を停止" i]',
].join(", ");

const RESPONSE = [
  ".model-response-text",
  "message-content",
  "model-response",
  ".markdown-main-panel",
].join(", ");

const NEW_CHAT = [
  'button[aria-label*="新しいチャット" i]',
  'button[aria-label*="New chat" i]',
  'a[aria-label*="新しいチャット" i]',
].join(", ");

const sleep = (ms: number) => new Promise((r) => setTimeout(r, ms));

export class GeminiGem {
  private ctx!: BrowserContext;
  private page!: Page;

  constructor(private cfg: Config) {}

  async open(): Promise<void> {
    const launch = (channel?: string) =>
      chromium.launchPersistentContext(this.cfg.userDataDir, {
        headless: this.cfg.headless,
        channel,
        viewport: { width: 1280, height: 900 },
        locale: "ja-JP",
        args: ["--disable-blink-features=AutomationControlled"],
      });
    try {
      this.ctx = await launch(this.cfg.useChrome ? "chrome" : undefined);
    } catch (err) {
      if (!this.cfg.useChrome) throw err;
      console.log(
        "Chrome を起動できませんでした。同梱 Chromium にフォールバックします。",
        (err as Error).message,
      );
      this.ctx = await launch(undefined);
    }
    this.page = this.ctx.pages()[0] ?? (await this.ctx.newPage());
    this.page.setDefaultTimeout(60_000);
    await this.goToGem();
    await this.ensureLoggedIn();
  }

  private async goToGem(): Promise<void> {
    await this.page.goto(this.cfg.gemUrl, { waitUntil: "domcontentloaded" });
  }

  private composer(): Locator {
    return this.page.locator(COMPOSER).first();
  }

  private async ensureLoggedIn(): Promise<void> {
    const deadline = Date.now() + 15 * 60_000;
    let warned = false;
    while (Date.now() < deadline) {
      if (await this.composer().isVisible().catch(() => false)) return;

      const onLogin = /accounts\.google\.com/.test(this.page.url());
      if (!onLogin && !warned) {
        // On the Gem page but no composer yet — give it a beat, then one reload.
        await sleep(4_000);
        if (await this.composer().isVisible().catch(() => false)) return;
        await this.goToGem().catch(() => {});
      }
      if (!warned) {
        console.log(
          "\n>> Gemini にログインしてください（開いた Chrome ウィンドウで Google ログイン）。\n" +
            ">> ログイン後この Gem のページに戻れば自動で続行します…\n",
        );
        warned = true;
      }
      await sleep(5_000);
    }
    throw new Error("ログイン/プロンプト入力欄を確認できませんでした（15分でタイムアウト）");
  }

  /** Fresh conversation so each batch is independent and the output stays small. */
  async newChat(): Promise<void> {
    const btn = this.page.locator(NEW_CHAT).first();
    if (await btn.isVisible().catch(() => false)) {
      await btn.click().catch(() => {});
      await sleep(800);
    } else {
      await this.goToGem();
    }
    await this.composer().waitFor({ state: "visible", timeout: 30_000 });
    await sleep(500);
  }

  /** Send one prompt, wait for the answer to settle, return its text. */
  async ask(prompt: string, timeoutMs: number): Promise<string> {
    const editor = this.composer();
    await editor.click();
    await this.page.keyboard.insertText(prompt);
    await sleep(400);

    const typed = (await editor.innerText().catch(() => "")).length;
    if (typed < Math.min(200, prompt.length / 2)) {
      throw new Error(`composer did not accept the prompt (got ${typed} chars)`);
    }

    const send = this.page.locator(SEND).first();
    await send.waitFor({ state: "visible", timeout: 15_000 });
    for (let i = 0; i < 24 && !(await send.isEnabled().catch(() => true)); i++) {
      await sleep(250);
    }
    await send.click();

    return this.waitForAnswer(timeoutMs);
  }

  private async waitForAnswer(timeoutMs: number): Promise<string> {
    const responses = this.page.locator(RESPONSE);
    const stop = this.page.locator(STOP).first();
    const start = Date.now();

    // Generation started: a stop control shows up (best effort).
    for (let i = 0; i < 12; i++) {
      if (await stop.isVisible().catch(() => false)) break;
      await sleep(500);
    }

    const stableFor = 4_000;
    let text = "";
    let lastChange = Date.now();

    while (Date.now() - start < timeoutMs) {
      await sleep(1_000);
      const now = await responses
        .last()
        .innerText()
        .catch(() => "");
      if (now !== text) {
        text = now;
        lastChange = Date.now();
        continue;
      }
      const generating = await stop.isVisible().catch(() => false);
      if (!generating && text.trim().length > 0 && Date.now() - lastChange >= stableFor) {
        return text;
      }
    }
    if (text.trim()) return text; // best effort on timeout
    throw new Error(`response timed out after ${timeoutMs}ms`);
  }

  async close(): Promise<void> {
    await this.ctx?.close().catch(() => {});
  }
}
