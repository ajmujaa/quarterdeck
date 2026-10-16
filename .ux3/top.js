async (page) => {
  const out = {};
  for (const w of [1500, 1280, 1100, 980, 860, 390]) {
    await page.setViewportSize({ width: w, height: 800 });
    await page.goto('http://127.0.0.1:7899/');
    await page.waitForTimeout(1500);
    out[w] = await page.evaluate(() => {
      const t = document.querySelector('.topbar'), r = t.getBoundingClientRect();
      const kids = [...t.children].filter(e => e.offsetParent).map(e => Math.round(e.getBoundingClientRect().y));
      return { h: Math.round(r.height), rows: new Set(kids).size, hs: document.documentElement.scrollWidth > innerWidth };
    });
  }
  return out;
}
