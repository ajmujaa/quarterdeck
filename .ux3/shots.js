async (page) => {
  const res = {};
  const lum = c => { const [r, g, b] = c.map(v => { v /= 255; return v <= 0.03928 ? v / 12.92 : Math.pow((v + 0.055) / 1.055, 2.4); }); return 0.2126 * r + 0.7152 * g + 0.0722 * b; };
  for (const theme of ['dark', 'light']) {
    for (const [w, h] of [[1500, 900], [1100, 800], [390, 844]]) {
      await page.setViewportSize({ width: w, height: h });
      await page.goto('http://127.0.0.1:7899/');
      await page.waitForTimeout(1200);
      await page.evaluate(t => { document.documentElement.setAttribute('data-theme', t); if (S && S.demo && !S.demo.on) toggleDemo(); }, theme);
      await page.waitForTimeout(2200);
      await page.evaluate(() => dockGo('brain'));
      await page.waitForTimeout(2500);
      await page.screenshot({ path: `.ux3/brain-${theme}-${w}.png` });
      await page.locator('#brain-bar').screenshot({ path: `.ux3/bar-map-${theme}-${w}.png` });
      await page.evaluate(() => setBrainMode('rhythm'));
      await page.waitForTimeout(1200);
      await page.screenshot({ path: `.ux3/rhythm-${theme}-${w}.png` });
      await page.locator('#brain-bar').screenshot({ path: `.ux3/bar-rhythm-${theme}-${w}.png` });
      // contrast of the toolbar's text
      res[`${theme}${w}`] = await page.evaluate(() => {
        const parse = s => (s.match(/[\d.]+/g) || []).slice(0, 4).map(Number);
        const lum = c => { const [r, g, b] = c.slice(0, 3).map(v => { v /= 255; return v <= 0.03928 ? v / 12.92 : Math.pow((v + 0.055) / 1.055, 2.4); }); return 0.2126 * r + 0.7152 * g + 0.0722 * b; };
        const bgOf = e => { while (e) { const c = parse(getComputedStyle(e).backgroundColor); if (c.length === 3 || (c.length === 4 && c[3] > 0.9)) return c; e = e.parentElement || (e.getRootNode() && e.getRootNode().host); } return [255, 255, 255]; };
        const out = [];
        for (const e of document.querySelectorAll('#brain-bar .bb-label, #brain-bar sl-button, #brain-bar sl-select')) {
          if (!e.offsetParent) continue;
          let t = e, base = e;
          if (e.shadowRoot) { base = e.shadowRoot.querySelector('[part~=base],[part~=combobox]') || e; t = e.shadowRoot.querySelector('[part~=label],[part~=display-input]') || base; }
          const fg = parse(getComputedStyle(t).color), bg = bgOf(base.matches && getComputedStyle(base).backgroundColor !== 'rgba(0, 0, 0, 0)' ? base : e);
          const L1 = lum(fg), L2 = lum(bg), r = (Math.max(L1, L2) + 0.05) / (Math.min(L1, L2) + 0.05);
          out.push([e.textContent.trim().slice(0, 10) || e.className, Math.round(r * 10) / 10]);
        }
        return out.filter(x => x[1] < 4.5);
      });
    }
  }
  return res;
}
