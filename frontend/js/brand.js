// WASHQ logo, icon and mascot, shared by every page.
// The W is the caracal; the eyes change with the mascot's state. The final Q is a search lens.
(function () {
  const SPRITE = `
<svg width="0" height="0" style="position:absolute" aria-hidden="true"><defs>
  <symbol id="w-mark" viewBox="0 -8 100 108">
    <path fill="none" stroke="var(--m, #14243B)" stroke-width="11" stroke-linejoin="miter" d="M6 6 L30 98 L50 34 L70 98 L94 6"/>
    <path stroke="var(--m, #14243B)" stroke-width="3.5" stroke-linecap="round" d="M4 -1 L2 -7 M96 -1 L98 -7"/>
    <rect x="25" y="47" width="12" height="5" rx="2.5" fill="#F58A36"/>
    <rect x="63" y="47" width="12" height="5" rx="2.5" fill="#F58A36"/>
  </symbol>
  <symbol id="w-body" viewBox="0 -8 100 108">
    <path fill="none" stroke="#14243B" stroke-width="11" stroke-linejoin="miter" d="M6 6 L30 98 L50 34 L70 98 L94 6"/>
    <path stroke="#14243B" stroke-width="3.5" stroke-linecap="round" d="M4 -1 L2 -7 M96 -1 L98 -7"/>
  </symbol>
  <symbol id="w-q" viewBox="0 0 100 110">
    <circle cx="46" cy="46" r="36" fill="none" stroke="var(--m, #14243B)" stroke-width="11"/>
    <path stroke="var(--m, #14243B)" stroke-width="12" stroke-linecap="round" d="M73 73 L94 100"/>
  </symbol>
  <symbol id="w-send" viewBox="0 0 24 24">
    <path d="M5 12h12M12 6l6 6-6 6" fill="none" stroke="#F7F5F0" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"/>
  </symbol>
</defs></svg>`;
  document.body.insertAdjacentHTML("afterbegin", SPRITE);

  const EYES = {
    idle:   '<rect x="25" y="47" width="12" height="5" rx="2.5" fill="#F58A36"/><rect x="63" y="47" width="12" height="5" rx="2.5" fill="#F58A36"/>',
    scan:   '<g class="beam"><rect x="16" y="48" width="68" height="3" rx="1.5" fill="#F58A36"/></g>',
    allow:  '<path fill="none" stroke="#F58A36" stroke-width="6" stroke-linecap="round" d="M25 52 Q31 44 37 52 M63 52 Q69 44 75 52"/>',
    block:  '<circle cx="31" cy="49" r="6" fill="#F58A36"/><circle cx="69" cy="49" r="6" fill="#F58A36"/>'
  };

  // The mascot: the W with eyes for one state (idle, scan, allow, block).
  function mascot(state, width) {
    const h = Math.round(width * 1.08);
    return `<svg class="mascot" width="${width}" height="${h}" viewBox="0 -8 100 108" style="overflow:visible" aria-hidden="true">` +
      `<use href="#w-body" x="0" y="-8" width="100" height="108"/>${EYES[state] || EYES.idle}</svg>`;
  }

  // The small W icon (logo eyes), for inline use.
  function mark(width) {
    return `<svg width="${width}" height="${Math.round(width * 1.08)}" aria-hidden="true"><use href="#w-mark"/></svg>`;
  }

  // Full logo: W (caracal) + ASH + Q (search lens). `size` is the letter size in px.
  function lockup(size) {
    const s = size;
    return `<span class="lockup" style="font-size:${s}px" role="img" aria-label="WASHQ">` +
      `<svg width="${Math.round(s * 1.18)}" height="${Math.round(s * 1.27)}" style="margin-bottom:${-Math.round(s * 0.07)}px" aria-hidden="true"><use href="#w-mark"/></svg>` +
      `<span class="wm" aria-hidden="true">ASH</span>` +
      `<svg width="${Math.round(s * 0.84)}" height="${Math.round(s * 0.93)}" style="margin-bottom:${-Math.round(s * 0.23)}px;margin-left:${Math.max(1, Math.round(s * 0.06))}px" aria-hidden="true"><use href="#w-q"/></svg>` +
      `</span>`;
  }

  window.WashqBrand = { mascot, mark, lockup };

  // Fill any element marked data-lockup="<size>" with the logo.
  document.querySelectorAll("[data-lockup]").forEach((el) => { el.innerHTML = lockup(+el.dataset.lockup || 18); });
})();
