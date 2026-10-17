// refresh-probe.js <html-file>: load the page in a real Chromium and say whether it tried to go to evil.invalid (a refresh to another site).
const { chromium } = require("playwright");
const fs = require("fs");
(async () => {
  const html = fs.readFileSync(process.argv[2], "utf8");
  const browser = await chromium.launch({ executablePath: process.env.QUARTERDECK_CHROMIUM || undefined });
  const page = await browser.newPage();
  let hit = false;
  await page.route("**/*", (route) => {
    const u = route.request().url();
    if (u.includes("evil.invalid")) { hit = true; return route.abort(); }
    if (u === "http://r7.test/") return route.fulfill({ status: 200, contentType: "text/html", body: html });
    return route.abort();
  });
  await page.goto("http://r7.test/");
  await page.waitForTimeout(2500);
  console.log(hit ? "NAVIGATED" : "stayed");
  await browser.close();
})().catch((e) => { console.log("error " + e.message); process.exit(2); });
