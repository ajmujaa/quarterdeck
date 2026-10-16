async (page) => {
  const out = {};
  for (const [theme, w, h, svc] of [['dark', 1500, 900, 'macmail'], ['light', 1500, 900, 'x'], ['dark', 1100, 800, 'meta'], ['light', 390, 844, 'macmail'], ['dark', 390, 844, 'threads']]) {
    await page.setViewportSize({ width: w, height: h });
    await page.goto('http://127.0.0.1:7899/');
    await page.waitForTimeout(1200);
    await page.evaluate(t => document.documentElement.setAttribute('data-theme', t), theme);
    await page.evaluate(() => dockGo('connections'));
    await page.waitForTimeout(2500);
    await page.screenshot({ path: `.ux3/conn-${theme}-${w}.png` });
    await page.evaluate(id => connHelp(id), svc);
    await page.waitForTimeout(1200);
    await page.screenshot({ path: `.ux3/help-${svc}-${theme}-${w}.png` });
    out[`${theme}${w}${svc}`] = await page.evaluate(() => {
      const d = document.querySelector('#drawer'), f = document.querySelector('#dfoot').getBoundingClientRect(), b = document.querySelector('#dfoot sl-button').getBoundingClientRect();
      return { open: d.open, footRight: Math.round(f.right - b.right), hs: document.documentElement.scrollWidth > innerWidth, sections: [...document.querySelectorAll('#dbody h2')].map(x => x.textContent).join('|') };
    });
    await page.evaluate(() => closeDrawer());
    await page.waitForTimeout(500);
  }
  return out;
}
