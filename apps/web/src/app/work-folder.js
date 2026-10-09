// Folder cover: React Bits by David Haz, MIT + Commons Clause.
// Notice: apps/web/licenses/react-bits-folder.txt.
// Readable horizontal cards replace the tiny fan per the user's 2026-10-05 refinement.
import { T } from './i18n';
import { purposeLabel } from './vocab.js';
const esc = (v) =>
  String(v ?? '').replace(
    /[&<>"']/g,
    (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' })[c],
  );
const id = (task, kind, work = '') =>
  `work-folder-${encodeURIComponent(task)}-${kind}${work ? '-' + encodeURIComponent(work) : ''}`;
const selector = '[data-work-folder]';
const paperIcon =
  '<svg data-work-flight-icon viewBox="0 0 20 20" fill="none" aria-hidden="true"><path d="M5 2.5h6l4 4v11H5zM11 2.5v4h4M7.5 10h5M7.5 13h5" stroke="currentColor" stroke-width="1.3" stroke-linejoin="round"/></svg>';
const arrow =
  '<svg viewBox="0 0 20 20" fill="none" aria-hidden="true"><path d="M4 10h11m-4-4 4 4-4 4" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"/></svg>';
const excerpt = (body) =>
  String(body || '')
    .replace(/```[\s\S]*?```/g, '')
    .replace(/!\[([^\]]*)\]\([^)]*\)/g, '$1')
    .replace(/\[([^\]]+)\]\([^)]*\)/g, '$1')
    .replace(/^[#>*\-\s]+/gm, '')
    .replace(/[*_`]/g, '')
    .replace(/\s+/g, ' ')
    .trim()
    .slice(0, 280);

/** Receives taskWorks(), projected with shown() so drafts remain visible. */
export function workFolderMarkup({ taskId, title = '', works = [] }) {
  const current = works
    .filter((w) => w.id && !w.removedAt)
    .map((w) => ({
      id: String(w.id),
      title: String(w.title || T('未命名作品', 'Untitled work')),
      kind:
        w.kind === 'test_set'
          ? T('测试计划', 'Test plan')
          : w.kind === 'investigation'
            ? T('调查', 'Investigation')
            : purposeLabel(w.purpose),
      version: Number.isFinite(Number(w.revision)) ? Number(w.revision) : 1,
      pending: w.source !== 'user' && !w.adopted,
      summary: excerpt(w.body) || T('还没有正文', 'No text yet'),
    }));
  if (current.length < 2) return '';
  const data = JSON.stringify({
    taskId: String(taskId),
    title,
    works: current.slice().reverse(),
  }).replace(/</g, '\\u003c');
  const name = T(current.length + ' 份作品', current.length + ' works');
  return `<div class="work-folder-host" data-work-folder="${esc(taskId)}"><script type="application/json" data-folder-record>${data}</script>
    <div class="work-folder-stage"><div class="work-folder-scale"><div class="work-folder">
      <button type="button" id="${esc(id(taskId, 'toggle'))}" class="work-folder-toggle" data-folder-toggle draggable="false" aria-expanded="false" aria-controls="${esc(id(taskId, 'tray'))}" aria-label="${esc(T('展开' + name, 'Open ' + name))}" data-open-label="${esc(T('展开' + name, 'Open ' + name))}" data-close-label="${esc(T('收起' + name, 'Close ' + name))}"><span class="work-folder-cover-mark" aria-hidden="true">${current.length}</span></button>
      <div class="work-folder-back">${current
        .slice(-3)
        .map(
          (w, i) =>
            `<span class="work-folder-thumb work-folder-thumb-${i + 1}" data-folder-thumb="${esc(w.id)}" aria-hidden="true"><i></i><i></i><i></i></span>`,
        )
        .join(
          '',
        )}<span class="work-folder-front" aria-hidden="true"></span><span class="work-folder-front work-folder-front-right" aria-hidden="true"></span></div>
    </div></div></div><span class="work-folder-label">${esc(name)}</span></div>`;
}

/** Each native button opens one actual work; titles are never truncated. */
export function workFolderTrayMarkup({ taskId, title = '', works }) {
  return `<section id="${esc(id(taskId, 'tray'))}" class="work-folder-tray" data-folder-tray="${esc(taskId)}" role="region" aria-labelledby="${esc(id(taskId, 'heading'))}">
    <header class="work-folder-tray-head"><div><h2 id="${esc(id(taskId, 'heading'))}">${esc(title || T('这件事的作品', 'Work for this task'))}</h2><p>${T(works.length + ' 份作品 · 选择一份打开', works.length + ' works · Choose one to open')}</p></div><button type="button" id="${esc(id(taskId, 'close'))}" class="work-folder-tray-close" data-folder-close aria-label="${esc(T('收起作品', 'Close works'))}"><span>${T('收起', 'Close')}</span><span aria-hidden="true">×</span></button></header>
    <div class="work-folder-tray-row" data-folder-row>${works.map((w) => `<div class="work-folder-slot" data-folder-slot="${esc(w.id)}"><button type="button" id="${esc(id(taskId, 'paper', w.id))}" class="work-folder-card" data-folder-card="${esc(w.id)}" data-folder-task="${esc(taskId)}" draggable="false"><span class="work-folder-card-meta">${paperIcon}<span>${esc(w.kind)}</span><span>v${esc(w.version)}</span>${w.pending ? `<span class="work-folder-pending">${T('待检查', 'To check')}</span>` : ''}</span><span class="work-folder-card-title" data-work-flight-title>${esc(w.title)}</span><span class="work-folder-card-summary">${esc(w.summary)}</span><span class="work-folder-card-open">${T('打开作品', 'Open work')}${arrow}</span></button></div>`).join('')}</div></section>`;
}

/** Call sync() after board rendering, before the application's focus restoration. */
export function installWorkFolders(root = document, { onSelect, onInteract } = {}) {
  const doc = root.nodeType === 9 ? root : root.ownerDocument,
    win = doc.defaultView;
  const reduced = win.matchMedia('(prefers-reduced-motion: reduce)');
  const listeners = [],
    locks = new Map(),
    states = new Map();
  let active = null,
    pointerHost = null;
  const listen = (target, type, fn, options) => {
    target.addEventListener(type, fn, options);
    listeners.push(() => target.removeEventListener(type, fn, options));
  };
  const hostFor = (target) => target?.closest?.(selector);
  const read = (host) => JSON.parse(host.querySelector('[data-folder-record]').textContent);
  const mark = (host, open) => {
    if (!host) return;
    states.set(host.dataset.workFolder, open);
    host.classList.toggle('is-open', open);
    const button = host.querySelector('[data-folder-toggle]');
    button.setAttribute('aria-expanded', String(open));
    button.setAttribute('aria-label', open ? button.dataset.closeLabel : button.dataset.openLabel);
  };
  const bounds = () => {
    const r = doc.querySelector('#main')?.getBoundingClientRect() || {
      left: 0,
      top: 56,
      right: win.innerWidth,
      bottom: win.innerHeight,
    };
    const left = Math.max(0, r.left),
      top = Math.max(56, r.top),
      right = Math.min(win.innerWidth, r.right),
      bottom = Math.min(win.innerHeight, r.bottom);
    return { left, top, right, bottom, width: right - left, height: bottom - top };
  };
  const sourceRect = (r) =>
    r.host?.querySelector('.work-folder-back')?.getBoundingClientRect() || r.source;
  const position = (r) => {
    const main = bounds(),
      source = sourceRect(r),
      width = Math.min(800, Math.max(240, main.width - 32));
    const above = source.top - main.top - 28,
      below = main.bottom - source.bottom - 28;
    const placeAbove = above >= 340 || above >= below,
      maxHeight = Math.max(180, Math.min(main.height - 32, placeAbove ? above : below));
    Object.assign(r.tray.style, {
      width: width + 'px',
      maxHeight: maxHeight + 'px',
      '--tray-max-height': maxHeight + 'px',
    });
    const height = Math.min(r.tray.offsetHeight, maxHeight);
    const left = Math.max(
      main.left + 16,
      Math.min(source.left + source.width / 2 - width / 2, main.right - width - 16),
    );
    const top = Math.max(
      main.top + 16,
      Math.min(
        placeAbove ? source.top - height - 12 : source.bottom + 12,
        main.bottom - height - 16,
      ),
    );
    Object.assign(r.tray.style, { left: left + 'px', top: top + 'px' });
    Object.assign(r.layer.style, {
      left: main.left + 'px',
      top: main.top + 'px',
      width: main.width + 'px',
      height: main.height + 'px',
    });
    r.main = main;
  };
  const transform = (from, to) =>
    `translate(${from.left - to.left}px, ${from.top - to.top}px) scale(${from.width / to.width}, ${from.height / to.height})`;
  const frame = (card) => ({
    rect: card.getBoundingClientRect(),
    opacity: Number(win.getComputedStyle(card).opacity),
  });
  const settle = (item) => {
    const focused = doc.activeElement === item.card;
    item.animation?.cancel();
    item.animation = null;
    item.card.removeAttribute('style');
    item.card.classList.remove('is-flying');
    item.slot.append(item.card);
    item.slot.style.minHeight = '';
    if (focused) item.card.focus({ preventScroll: true });
  };
  const cancel = (r) => {
    r.cards.forEach((item) => {
      item.animation?.cancel();
      item.animation = null;
    });
    r.background?.cancel();
    r.background = null;
  };
  const finishOpen = (r) => {
    r.generation++;
    cancel(r);
    r.cards.forEach(settle);
    r.tray.style.opacity = '1';
    r.phase = 'open';
  };
  const remove = (r, defer = false) => {
    if (!r) return;
    r.generation++;
    cancel(r);
    mark(r.host, false);
    if (active === r) active = null;
    r.tray.style.pointerEvents = 'none';
    r.layer.style.pointerEvents = 'none';
    const cleanup = () => {
      r.tray.remove();
      r.layer.remove();
    };
    if (defer) win.requestAnimationFrame(cleanup);
    else cleanup();
  };
  const fly = (r, item, target) => {
    r.layer.append(item.card);
    item.card.classList.add('is-flying');
    Object.assign(item.card.style, {
      position: 'absolute',
      left: target.left - r.main.left + 'px',
      top: target.top - r.main.top + 'px',
      width: target.width + 'px',
      height: target.height + 'px',
      margin: '0',
      transformOrigin: '0 0',
    });
  };
  const animate = (r, opening, captured = null) => {
    const generation = ++r.generation;
    const snapshots = new Map(
      r.cards.map((item) => [item.workId, captured?.get(item.workId) || frame(item.card)]),
    );
    const destinations = new Map(
      r.cards.map((item) => [item.workId, item.slot.getBoundingClientRect()]),
    );
    r.cards.forEach((item) => {
      item.slot.style.minHeight = destinations.get(item.workId).height + 'px';
    });
    const source = sourceRect(r);
    r.source = source;
    r.phase = opening ? 'opening' : 'closing';
    const opacity = Number(win.getComputedStyle(r.tray).opacity);
    r.background?.cancel();
    r.background = r.tray.animate([{ opacity }, { opacity: opening ? 1 : 0 }], {
      duration: reduced.matches ? 0 : 220,
      fill: 'forwards',
      easing: 'ease-out',
    });
    const rowRect = r.tray.querySelector('[data-folder-row]').getBoundingClientRect();
    const jobs = r.cards.map((item) => {
      const shot = snapshots.get(item.workId),
        slot = destinations.get(item.workId);
      item.animation?.cancel();
      item.animation = null;
      const visible = slot.right > rowRect.left && slot.left < rowRect.right;
      if (!visible) {
        settle(item);
        item.card.style.opacity = opening ? '1' : '0';
        return Promise.resolve();
      }
      const target = { left: slot.left, top: slot.top, width: slot.width, height: slot.height };
      fly(r, item, target);
      item.card.style.pointerEvents = opening ? 'auto' : 'none';
      const animation = item.card.animate(
        [
          {
            transform: transform(shot?.rect || source, target),
            opacity: shot?.opacity ?? 0,
            borderRadius: '14px',
          },
          {
            transform: opening ? 'none' : transform(source, target),
            opacity: opening ? 1 : 0,
            borderRadius: opening ? '14px' : '10px',
          },
        ],
        {
          duration: reduced.matches ? 0 : 500,
          easing: 'cubic-bezier(.39,.14,.26,1)',
          fill: 'both',
        },
      );
      item.animation = animation;
      return animation.finished
        .catch(() => {})
        .then(() => {
          if (r.generation === generation && opening) settle(item);
        });
    });
    Promise.all(jobs).then(() => {
      if (r.generation !== generation || active !== r) return;
      if (opening) {
        r.phase = 'open';
        r.tray.style.opacity = '1';
        r.background?.cancel();
        r.background = null;
      } else remove(r);
    });
  };
  const close = ({ restoreFocus = false, immediate = false, defer = false } = {}) => {
    const r = active;
    if (!r) return;
    mark(r.host, false);
    if (restoreFocus) r.host?.querySelector('[data-folder-toggle]')?.focus({ preventScroll: true });
    if (immediate || reduced.matches) remove(r, defer);
    else animate(r, false);
  };
  const create = (host, data) => {
    const box = doc.createElement('div');
    box.innerHTML = workFolderTrayMarkup(data);
    const tray = box.firstElementChild,
      layer = doc.createElement('div');
    layer.className = 'work-folder-flight-layer';
    layer.dataset.folderFlights = data.taskId;
    tray.style.opacity = '0';
    doc.body.append(tray, layer);
    const r = {
      taskId: data.taskId,
      host,
      data,
      fingerprint: JSON.stringify(data),
      tray,
      layer,
      source: sourceRect({ host }),
      cards: [],
      phase: 'opening',
      generation: 0,
    };
    r.cards = [...tray.querySelectorAll('[data-folder-slot]')].map((slot) => ({
      slot,
      card: slot.firstElementChild,
      workId: slot.dataset.folderSlot,
      animation: null,
    }));
    position(r);
    return r;
  };
  const open = (host, keyboard = false) => {
    const data = read(host);
    if (active?.taskId === data.taskId) {
      if (active.phase === 'closing') {
        mark(host, true);
        active.host = host;
        animate(active, true, new Map(active.cards.map((item) => [item.workId, frame(item.card)])));
      } else close();
      return;
    }
    if (active) remove(active);
    const r = create(host, data);
    active = r;
    mark(host, true);
    animate(r, true, new Map(r.cards.map((item) => [item.workId, { rect: r.source, opacity: 0 }])));
    if (keyboard) r.cards[0]?.card.focus({ preventScroll: true });
  };
  const sync = () => {
    const hosts = [...root.querySelectorAll(selector)].filter(
        (host) => !host.closest('.document-flight'),
      ),
      present = new Map(hosts.map((host) => [host.dataset.workFolder, host]));
    states.forEach((_, key) => {
      if (!present.has(key)) states.delete(key);
    });
    if (active && !present.has(active.taskId)) {
      remove(active, true);
      return;
    }
    hosts.forEach((host) => mark(host, !!states.get(host.dataset.workFolder)));
    if (!active) return;
    active.host = present.get(active.taskId);
    const data = read(active.host),
      fingerprint = JSON.stringify(data);
    if (fingerprint !== active.fingerprint) {
      const old = active,
        scroll = old.tray.querySelector('[data-folder-row]').scrollLeft,
        focusId = doc.activeElement?.id,
        captured = new Map(old.cards.map((item) => [item.workId, frame(item.card)]));
      const wasClosing = old.phase === 'closing',
        host = old.host;
      remove(old);
      active = create(host, data);
      mark(host, !wasClosing);
      active.tray.querySelector('[data-folder-row]').scrollLeft = scroll;
      animate(active, !wasClosing, captured);
      if (focusId) doc.getElementById(focusId)?.focus({ preventScroll: true });
    }
    position(active);
  };
  const release = () => {
    locks.forEach((value, card) => {
      if (value === null) card.removeAttribute('draggable');
      else card.setAttribute('draggable', value);
    });
    locks.clear();
  };
  const inside = (target) =>
    active &&
    (active.tray.contains(target) ||
      active.layer.contains(target) ||
      active.host?.contains(target));
  listen(
    root,
    'pointerdown',
    (e) => {
      const host = hostFor(e.target);
      pointerHost = host;
      if (active && !inside(e.target)) close();
      const card = host?.closest('[draggable="true"]');
      if (card && !locks.has(card)) {
        locks.set(card, card.getAttribute('draggable'));
        card.setAttribute('draggable', 'false');
      }
    },
    true,
  );
  listen(
    win,
    'pointerup',
    () => {
      release();
      const ended = pointerHost;
      setTimeout(() => {
        if (pointerHost === ended) pointerHost = null;
      }, 0);
    },
    true,
  );
  listen(
    win,
    'pointercancel',
    () => {
      release();
      pointerHost = null;
    },
    true,
  );
  listen(win, 'blur', () => {
    release();
    pointerHost = null;
  });
  listen(
    root,
    'dragstart',
    (e) => {
      if (hostFor(e.target) || e.target.closest?.('[data-folder-card]') || locks.size) {
        e.preventDefault();
        e.stopImmediatePropagation();
        release();
      } else if (active) close();
    },
    true,
  );
  listen(
    root,
    'click',
    (e) => {
      const button = e.target.closest?.('button');
      if (!button) return;
      if (button.matches('[data-folder-toggle]')) {
        e.stopPropagation();
        const host = hostFor(button);
        onInteract?.(host, e);
        open(host, e.detail === 0);
      } else if (button.matches('[data-folder-close]') && active?.tray.contains(button)) {
        e.stopPropagation();
        close({ restoreFocus: true });
      } else if (button.matches('[data-folder-card]') && active && active.phase !== 'closing') {
        e.stopPropagation();
        const r = active;
        onSelect?.(r.taskId, button.dataset.folderCard, e, button);
        if (active === r) close({ immediate: true, defer: true });
      }
    },
    true,
  );
  listen(
    root,
    'keydown',
    (e) => {
      const host = hostFor(e.target);
      if (e.key === 'Escape' && active) {
        e.preventDefault();
        e.stopImmediatePropagation();
        close({ restoreFocus: true });
        return;
      }
      if (host && e.target.matches('[data-folder-toggle]') && e.key === 'ArrowDown') {
        e.preventDefault();
        e.stopPropagation();
        onInteract?.(host, e);
        if (!active || active.taskId !== host.dataset.workFolder || active.phase === 'closing')
          open(host, true);
        else active.cards[0]?.card.focus({ preventScroll: true });
        return;
      }
      const card = e.target.closest?.('[data-folder-card]');
      if (
        !card ||
        !active ||
        active.phase === 'closing' ||
        !['ArrowLeft', 'ArrowRight', 'Home', 'End'].includes(e.key)
      )
        return;
      e.preventDefault();
      e.stopPropagation();
      // Keyboard navigation changes the scroll destination; finish the initial
      // flight first so it cannot later land at the earlier measured position.
      if (active.phase === 'opening') finishOpen(active);
      const index = active.cards.findIndex((item) => item.card === card);
      const next =
        e.key === 'Home'
          ? 0
          : e.key === 'End'
            ? active.cards.length - 1
            : Math.max(
                0,
                Math.min(active.cards.length - 1, index + (e.key === 'ArrowRight' ? 1 : -1)),
              );
      const item = active.cards[next],
        row = active.tray.querySelector('[data-folder-row]');
      item.card.focus({ preventScroll: true });
      const r = row.getBoundingClientRect(),
        s = item.slot.getBoundingClientRect();
      if (s.left < r.left || s.right > r.right)
        row.scrollBy({
          left: s.left < r.left ? s.left - r.left - 2 : s.right - r.right + 2,
          behavior: reduced.matches ? 'auto' : 'smooth',
        });
    },
    true,
  );
  listen(root, 'focusout', (e) => {
    if (!active || !inside(e.target)) return;
    const r = active;
    queueMicrotask(() => {
      if (
        active !== r ||
        !r.host?.isConnected ||
        pointerHost === r.host ||
        inside(doc.activeElement)
      )
        return;
      if (doc.activeElement !== doc.body) close();
    });
  });
  listen(
    root,
    'scroll',
    (e) => {
      if (!active) return;
      const r = active;
      if (e.target === r.tray.querySelector('[data-folder-row]')) {
        if (r.phase === 'opening') finishOpen(r);
        return;
      }
      if (e.target?.id !== 'main') return;
      const source = sourceRect(r),
        main = bounds();
      if (source.bottom <= main.top || source.top >= main.bottom) {
        close({ immediate: true });
        return;
      }
      const captured = new Map(r.cards.map((item) => [item.workId, frame(item.card)]));
      position(r);
      if (r.phase === 'opening' || r.phase === 'closing')
        animate(r, r.phase === 'opening', captured);
    },
    { capture: true, passive: true },
  );
  listen(win, 'resize', () => {
    if (!active) return;
    const r = active,
      captured = new Map(r.cards.map((item) => [item.workId, frame(item.card)]));
    position(r);
    if (r.phase === 'opening' || r.phase === 'closing') animate(r, r.phase === 'opening', captured);
  });
  listen(reduced, 'change', () => {
    if (!active) return;
    if (active.phase === 'closing') remove(active);
    else finishOpen(active);
  });
  return {
    sync,
    dispose: () => {
      if (active) remove(active);
      release();
      listeners.forEach((unlisten) => unlisten());
      states.clear();
    },
  };
}
