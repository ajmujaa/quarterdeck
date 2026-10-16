async (page) => {
  const out = [];
  for (const [w, h] of [[1500, 900], [390, 844]]) {
    await page.setViewportSize({ width: w, height: h });
    await page.goto('http://127.0.0.1:7899/');
    await page.waitForTimeout(1500);
    await page.evaluate(() => { if (S && S.demo && !S.demo.on) toggleDemo(); });
    await page.waitForTimeout(2500);
    const ids = await page.evaluate(() => VIEWS.filter(v => v.id !== 'brain').map(v => [v.id, v.place || '']));
    for (const [id, place] of ids) {
      await page.evaluate(([id, place]) => { if (place) selectPlace(place, id); else dockGo(id); }, [id, place]);
      await page.waitForTimeout(900);
      const r = await page.evaluate(() => {
        const q = s => document.querySelector(s), R = e => { if (!e || !e.offsetParent && e.tagName !== 'BODY') return null; const r = e.getBoundingClientRect(); return [Math.round(r.x), Math.round(r.y), Math.round(r.width), Math.round(r.height)]; };
        const v = q('#view');
        return {
          view: window.view, proj: R(q('#proj-switch')), kicker: R(q('#pkicker')), h1: R(q('#ptitle')), sub: R(q('#psub')), tabs: R(q('#ptabs')), acts: R(q('#pacts')),
          primaries: v ? v.querySelectorAll('sl-button[variant=primary]').length : 0, pactsPrimary: document.querySelectorAll('#pacts sl-button[variant=primary]').length,
          h1s: v ? v.querySelectorAll('h1').length : 0, h2s: v ? v.querySelectorAll('h2').length : 0, h3s: v ? v.querySelectorAll('h3').length : 0,
          rawSelect: v ? v.querySelectorAll('select').length : 0,
          localProjSel: v ? [...v.querySelectorAll('sl-select')].map(s => (s.getAttribute('label') || s.id || '')).filter(t => /project/i.test(t)) : [],
          hscroll: document.documentElement.scrollWidth > innerWidth, btnSizes: v ? [...new Set([...v.querySelectorAll('sl-button')].map(b => b.getAttribute('size') || 'medium'))].join(',') : '',
        };
      });
      out.push(w + ' ' + id + ' ' + JSON.stringify(r));
    }
  }
  return out.join('\n');
}
