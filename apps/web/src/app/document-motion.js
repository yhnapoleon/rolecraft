// Shared document layout, based on the public Motion App Store tutorial's FLIP
// contract and timing. This is our implementation, not Motion+'s paid source.
// https://motion.dev/examples/js-app-store-layout (500ms, .39 .14 .26 1)
// A persistent flight layer survives live API renders and retargets from its
// current geometry. Native view-transition snapshots cannot do that on reversal.
export const DOCUMENT_DURATION = 500;
export const DOCUMENT_EASE = [0.39, 0.14, 0.26, 1];

export function documentEase(t) {
  const [x1, y1, x2, y2] = DOCUMENT_EASE;
  const cubic = (s, a, b) => 3 * (1 - s) ** 2 * s * a + 3 * (1 - s) * s * s * b + s ** 3;
  let lo = 0, hi = 1;
  for (let i = 0; i < 18; i++) { const m = (lo + hi) / 2; if (cubic(m, x1, x2) < t) lo = m; else hi = m; }
  return t <= 0 ? 0 : t >= 1 ? 1 : cubic((lo + hi) / 2, y1, y2);
}
const mix = (a, b, t) => a + (b - a) * t;
export function mixBox(a, b, t) {
  return Object.fromEntries(['x', 'y', 'width', 'height'].map(k => [k, mix(a[k], b[k], t)]));
}
const box = el => { const r = el.getBoundingClientRect(); return { x: r.x, y: r.y, width: r.width, height: r.height }; };
const cardSelector = id => `.doc-card[data-id="${CSS.escape(id)}"]`;
const paperSelector = id => `.document[data-document-id="${CSS.escape(id)}"]`;
const targetFor = (route, id) => document.querySelector('#app ' + (route === 'doc' ? paperSelector(id) : cardSelector(id)));

function capture(el, isPaper) {
  if (!el) return null;
  const title = el.querySelector(isPaper ? '.doc-title' : '.dc-title');
  const icon = el.querySelector(isPaper ? '.doc-icon .i' : '.dc-top > .i');
  if (!title || !icon) return null;
  const style = getComputedStyle(title);
  return { surface: box(el), title: box(title), icon: box(icon),
    fontSize: parseFloat(style.fontSize), lineHeight: parseFloat(style.lineHeight),
    radius: parseFloat(getComputedStyle(el).borderTopLeftRadius) || 14,
    titleStyle: { fontFamily: style.fontFamily, fontWeight: style.fontWeight, letterSpacing: style.letterSpacing, color: style.color },
    titleText: title.textContent, iconNode: icon.cloneNode(true), element: el };
}
function cleanClone(node) {
  const clone = node.cloneNode(true);
  [clone, ...clone.querySelectorAll('*')].forEach(el => {
    el.removeAttribute('id'); el.removeAttribute('autofocus');
    el.style.viewTransitionName = 'none'; el.style.animation = 'none'; el.style.transition = 'none';
  });
  clone.inert = true; clone.setAttribute('aria-hidden', 'true');
  return clone;
}

export function createDocumentMotion() {
  const reduced = matchMedia('(prefers-reduced-motion: reduce)');
  let active = null, boardScroll = null, lastId = null;
  const restoreBoardScroll = () => {
    if (!boardScroll) return;
    window.scrollTo(boardScroll.x, boardScroll.y);
    const main = document.getElementById('main'); if (main) main.scrollTop = boardScroll.main;
  };
  function release() {
    document.querySelectorAll('#app [data-document-flight-hidden]').forEach(el => el.removeAttribute('data-document-flight-hidden'));
  }
  function finish(focus = true) {
    if (!active) return;
    const flight = active; active = null;
    cancelAnimationFrame(flight.raf); release(); flight.layer.remove();
    document.documentElement.classList.remove('document-in-flight');
    const target = targetFor(flight.route, flight.id);
    if (focus) (flight.route === 'doc' ? target?.querySelector('.doc-title') : target)?.focus({ preventScroll: true });
  }
  function sync() {
    if (!active) return;
    const target = targetFor(active.route, active.id);
    target?.setAttribute('data-document-flight-hidden', '');
    target?.closest('.board, .page-pad')?.style.setProperty('animation', 'none');
    if (active.destination && target) {
      const next = capture(target, active.route === 'doc'), prior = active.destination.surface;
      if (next && ['x','y','width','height'].some(k => Math.abs(next.surface[k] - prior[k]) > .5)) {
        play(active, active.frame, { ...next, open: active.route === 'doc' ? 1 : 0 });
      }
    }
  }
  function draw(flight, frame) {
    const { surface: r, title: t, icon: i } = frame;
    flight.frame = frame;
    const sx = r.width / flight.base.width, sy = r.height / flight.base.height;
    Object.assign(flight.surface.style, {
      transform: `translate3d(${r.x}px,${r.y}px,0) scale(${sx},${sy})`,
      borderRadius: `${frame.radius / sx}px / ${frame.radius / sy}px`,
    });
    // Counter-scale the actual document content, so text never stretches as the
    // paper outline changes aspect ratio. Overflow reveals it like the original.
    flight.content.style.transform = `scale(${1 / sx},${1 / sy})`;
    flight.content.style.opacity = String(Math.min(1, frame.open * 2));
    flight.cardDetails.style.opacity = String(Math.max(0, 1 - frame.open * 3));
    flight.cardDetails.style.transform = `scale(${1 / sx},${1 / sy})`;
    Object.assign(flight.title.style, { transform: `translate3d(${t.x}px,${t.y}px,0)`, width: `${t.width}px`,
      fontSize: `${frame.fontSize}px`, lineHeight: `${frame.lineHeight}px` });
    Object.assign(flight.icon.style, { transform: `translate3d(${i.x}px,${i.y}px,0) scale(${i.width / flight.iconSize},${i.height / flight.iconSize})` });
    if (flight.background) flight.background.style.opacity = String(1 - frame.open);
  }
  function play(flight, from, to) {
    cancelAnimationFrame(flight.raf);
    flight.destination = to;
    const start = performance.now();
    const tick = now => {
      if (active !== flight) return;
      const time = Math.min(1, (now - start) / DOCUMENT_DURATION), t = documentEase(time);
      const frame = { surface: mixBox(from.surface, to.surface, t), title: mixBox(from.title, to.title, t), icon: mixBox(from.icon, to.icon, t) };
      for (const k of ['fontSize', 'lineHeight', 'radius', 'open']) frame[k] = mix(from[k], to[k], t);
      draw(flight, frame);
      if (time < 1) flight.raf = requestAnimationFrame(tick); else finish();
    };
    draw(flight, from); flight.raf = requestAnimationFrame(tick);
  }
  function makeLayer(id, route, from, to, paper, card, background) {
    const layer = document.createElement('div'); layer.className = 'document-flight';
    layer.setAttribute('aria-hidden', 'true'); layer.inert = true;
    const main = document.getElementById('main'); const bounds = main ? box(main) : {x:0,y:0,width:innerWidth,height:innerHeight};
    layer.style.clipPath = `inset(${Math.max(0,bounds.y)}px ${Math.max(0,innerWidth-bounds.x-bounds.width)}px ${Math.max(0,innerHeight-bounds.y-bounds.height)}px ${Math.max(0,bounds.x)}px)`;
    if (background) layer.append(background);
    const surface = document.createElement('div'); surface.className = 'document-flight-surface';
    const base = paper.surface;
    Object.assign(surface.style, { width: `${base.width}px`, height: `${base.height}px` });
    const content = cleanClone(paper.element); content.classList.add('document-flight-content');
    Object.assign(content.style, { width: `${base.width}px`, height: `${base.height}px`, maxWidth: 'none', margin: '0' });
    content.querySelector('.doc-title').style.visibility = 'hidden';
    content.querySelector('.doc-icon .i').style.visibility = 'hidden';
    const cardDetails = cleanClone(card.element); cardDetails.classList.add('document-flight-card');
    Object.assign(cardDetails.style, { width: `${card.surface.width}px`, height: `${card.surface.height}px`, margin: '0' });
    cardDetails.querySelector('.dc-title').style.visibility = 'hidden';
    cardDetails.querySelector('.dc-top > .i').style.visibility = 'hidden';
    surface.append(content, cardDetails);
    const title = document.createElement('div'); title.className = 'document-flight-title';
    title.textContent = paper.titleText; Object.assign(title.style, paper.titleStyle);
    const icon = document.createElement('div'); icon.className = 'document-flight-icon'; icon.append(paper.iconNode);
    const iconSize = paper.icon.width;
    Object.assign(icon.style, {width: `${iconSize}px`, height: `${iconSize}px`});
    Object.assign(paper.iconNode.style, {width: '100%', height: '100%'});
    layer.append(surface, title, icon); document.body.append(layer);
    return { id, route, layer, surface, content, cardDetails, title, icon, iconSize, background, base, raf: 0, frame: from };
  }
  function transition(fromRoute, toRoute, id, update) {
    const opening = fromRoute === 'work' && toRoute === 'doc';
    const closing = fromRoute === 'doc' && toRoute === 'work' && id === lastId;
    if (!opening && !closing) { finish(false); update(); return false; }
    const continuing = active?.id === id ? active : null;
    const from = continuing ? continuing.frame : capture(targetFor(fromRoute, id), !opening);
    if (opening && !continuing) {
      boardScroll = { x: scrollX, y: scrollY, main: document.getElementById('main')?.scrollTop || 0 };
      lastId = id;
    }
    let background = null;
    if (opening && from && !continuing && !reduced.matches) {
      const main = document.getElementById('main'); const r = box(main);
      background = cleanClone(main); background.classList.add('document-flight-background');
      Object.assign(background.style, { position: 'fixed', left: `${r.x}px`, top: `${r.y}px`, width: `${r.width}px`, height: `${r.height}px`, margin: '0', overflow: 'hidden' });
      background.querySelector(cardSelector(id))?.setAttribute('data-document-flight-hidden','');
    }
    if (!continuing) finish(false);
    if (from && !reduced.matches) document.documentElement.classList.add('document-in-flight');
    update();
    if (closing) {
      restoreBoardScroll();
      const card = targetFor('work', id), main = document.getElementById('main');
      if (card && main) {
        const r = box(card), bounds = box(main);
        if (r.y < bounds.y || r.y + r.height > bounds.y + bounds.height) {
          card.scrollIntoView({ block: 'nearest', behavior: 'instant' });
          window.scrollTo(0, 0);
        }
      }
    }
    const to = capture(targetFor(toRoute, id), opening);
    if (!from || !to || reduced.matches || !from.surface.width || !to.surface.width) {
      finish(false);
      document.documentElement.classList.remove('document-in-flight');
      (opening ? to?.element.querySelector('.doc-title') : to?.element)?.focus({ preventScroll: true });
      return true;
    }
    if (continuing) {
      release(); continuing.route = toRoute; active = continuing;
    } else {
      active = makeLayer(id, toRoute, from, to, opening ? to : from, opening ? from : to, background);
      if (background) background.scrollTop = boardScroll.main;
    }
    document.documentElement.classList.add('document-in-flight');
    sync();
    play(active, { ...from, open: continuing ? from.open : opening ? 0 : 1 }, { ...to, open: opening ? 1 : 0 });
    return true;
  }
  reduced.addEventListener('change', () => { if (reduced.matches) finish(); });
  document.addEventListener('scroll', event => {
    if (!active || event.target.id !== 'main') return;
    const to = capture(targetFor(active.route, active.id), active.route === 'doc');
    if (!to) return;
    const prior = active.destination.surface;
    if (Math.abs(to.surface.y - prior.y) > .5 || Math.abs(to.surface.x - prior.x) > .5) {
      play(active, active.frame, { ...to, open: active.route === 'doc' ? 1 : 0 });
    }
  }, true);
  window.addEventListener('resize', () => finish(false));
  return { transition, sync, cancel: () => finish(false), get active() { return !!active; } };
}
