// Shared registry for actions and routes. ui.js stays the dispatcher of record: act() asks
// here first, render() asks here for routes it does not know. Lines register their own
// actions and screens instead of adding cases to ui.js.

export type ActionHandler = (el: HTMLElement, ev: Event) => unknown | Promise<unknown>;
export type RouteRender = (id: string | null) => string;
export type RouteMount = (root: HTMLElement) => void;

const actions = new Map<string, ActionHandler>();
const routes = new Map<string, { render: RouteRender; mount?: RouteMount }>();

/** Adds handlers by action name (the button's data-action). A later registration of the same name wins. */
export function registerActions(map: Record<string, ActionHandler>): void {
  for (const [name, fn] of Object.entries(map)) actions.set(name, fn);
}

/**
 * The handler a line registered for this name, or null. ui.js checks this synchronously so an
 * action nobody registered runs without waiting a microtask (motion that starts on the click
 * itself, like the document flight, depends on it).
 */
export const registeredAction = (name: string): ActionHandler | null => actions.get(name) ?? null;

/** Runs a registered handler; false when no line registered this name (ui.js then handles it). */
export async function dispatchRegistered(
  name: string,
  el: HTMLElement,
  ev: Event,
): Promise<boolean> {
  const fn = actions.get(name);
  if (!fn) return false;
  await fn(el, ev);
  return true;
}

/**
 * Adds a screen at #/<name>[/<id>] inside a practice. The shell keeps the topbar and the right
 * rail; render returns only the main screen's HTML, and mount runs after every render of that
 * route with the main screen element (#ws-stage). Without a practice the route goes home.
 */
export function registerRoute(name: string, render: RouteRender, mount?: RouteMount): void {
  const known = routes.has(name);
  routes.set(name, { render, mount });
  if (!known) for (const cb of routeListeners) cb(name);
}

/* ---------- used by the shell (ui.js) ---------- */

const routeListeners = new Set<(name: string) => void>();
export const registeredRoute = (name: string) => routes.get(name) ?? null;
export const isRegisteredRoute = (name: string) => routes.has(name);
export const registeredRouteNames = () => [...routes.keys()];
/** ui.js learns of routes registered after it loaded (a line's module imported later). */
export function onRouteRegistered(cb: (name: string) => void): () => void {
  routeListeners.add(cb);
  return () => routeListeners.delete(cb);
}

let runner: ((el: HTMLElement, ev: Event) => unknown) | null = null;
/** ui.js hands its act() here once, so islands and toasts can run any action by name. */
export function setActionRunner(fn: (el: HTMLElement, ev: Event) => unknown): void {
  runner = fn;
}

/**
 * Runs an action by name from code that has no button of its own (a toast, an island). It goes
 * through the same path as a click: registered handlers first, then ui.js. The promise rejects
 * with the action's error, so the caller can say what went wrong.
 */
export function runAction(
  name: string,
  id?: string,
  data: Record<string, string> = {},
): Promise<unknown> {
  const el = document.createElement('button');
  el.dataset.action = name;
  if (id != null) el.dataset.id = id;
  for (const [k, v] of Object.entries(data)) el.dataset[k] = v;
  const ev = new Event('rc-action');
  return Promise.resolve(runner ? runner(el, ev) : dispatchRegistered(name, el, ev));
}
