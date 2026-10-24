# Shell: contracts every screen line builds on

The workbench is still native DOM (`app/ui.js` string templates plus TS modules). This folder is
the seam other lines plug into without adding cases to `ui.js`. Import everything from
`src/shell` (the index re-exports each module). The signatures marked **fixed** do not change
before the lines merge; additions are allowed.

## Actions — `registry.ts`

```ts
registerActions({ 'my-action': (el, ev) => { … } });   // fixed
dispatchRegistered(name, el, ev): Promise<boolean>;    // fixed; act() calls it first
runAction(name, id?, data?)                            // run any action from code (toast, island)
```

- A button `data-action="my-action" data-id="…"` anywhere in the page (native template or a
  React island) reaches your handler through the one document click listener. Registered names
  win over `ui.js` cases, so do not reuse an existing name unless you mean to replace it.
- Register at module top level and import the module from your screen's entry, so it runs before
  the first click.

## Routes — `registry.ts`

```ts
registerRoute('agent', (id) => '<section>…</section>', (stage) => { … });  // fixed
```

- `#/agent[/<id>]` is drawn **inside the workspace**: the topbar and the right rail stay, and
  your HTML becomes the main screen (`#ws-stage`). `mount(stage)` runs after every render of
  the route (also after partial redraws), with that element.
- Without a practice the route falls back to home.
- Your HTML is replaced on every redraw. Keep anything stateful in an island (below).

## React islands — `../islands/mount.tsx`

```ts
mountIsland(host, Component, props) → { update(p), destroy() }   // fixed; you own host
islandSlot('agent-stream')            → '<div class="rc-island-slot" data-island="agent-stream">'
keepIsland('agent-stream', Component, props, { persist? })        // call from mount()
```

- `ui.js` redraws regions with `innerHTML`. Put `islandSlot(key)` in the template and call
  `keepIsland(key, …)` from your mount. The island renders into its own container, which is moved
  into each new placeholder, so React state survives redraws. Focus inside the island comes back.
- After each render the shell unmounts islands whose placeholder did not return (one frame
  later). `persist: true` keeps one alive while off screen.
- Each island root has `class="rc-island"` (no box of its own, `display: contents`).

### Tailwind in islands

- Only in TSX, only prefixed: `tw:flex`, `tw:bg-paper`, `tw:hover:bg-fill-2`. No preflight.
- Never `dark:`. Colours come from our variables, so light/dark follow the page.
- Tokens (`islands/tw.css`): colours `ink ink-2 ink-3 ink-4 paper desk inst inst-2 inst-3 line
  line-2 fill fill-2 primary on-primary good warn bad unk manager business technical` (and
  `*-tint` for good/warn/bad); fonts `sans serif mono`; radii `rounded-paper` 3px, `rounded-key`
  8px, `rounded-panel` 12px, `rounded-dialog` 16px; shadows `shadow-paper shadow-card
  shadow-float`; easings `ease-out`, `ease-drawer`.
- Copied shadcn / Magic UI / AI Elements code: keep structure and behaviour, rewrite classes
  with the prefix and our tokens. `.rc-island` maps `--background --foreground --card --muted
  --muted-foreground --border --ring --radius` to ours for code that reads them raw. A portal
  (sheet, tooltip) renders outside the island: give its content `className="rc-portal"`.

## Signals ("Needs you") — `signals.ts`

```ts
registerSignals((attempt) => Signal[]);   // fixed; one provider per line
collectSignals(attempt): Signal[]         // the board line renders these (newest first)
dismissSignal(id); signalsChanged(); onSignalsChange(cb)
```

`source: 'person'` is drawn as a colleague's note, `'agent' | 'system'` as an instrument line.
`action` is an action name (see Actions). Providers must be cheap and pure; call
`signalsChanged()` when your data changes outside a render.

## Hat — `hat.ts`

```ts
hatOf(sessionKey): 'pm' | 'engineer';  setHat(sessionKey, hat);  onHatChange(cb) → unsubscribe  // fixed
everEngineer(sessionKey)               // home's continue slip
```

`sessionKey` is the practice id (`attempt.id`). Front-end only, per browser.

## Stage and the primary key — `stage.ts`

```ts
registerStage('engineer', (attempt) => ({ title?: [zh, en], steps: [...], primary: { label: [zh, en], action, id?, disabledReason? } }));  // fixed; title is an addition
stageOf(hat, attempt): Stage | null
```

The topbar draws the scale and the one primary key from the current hat's stage. The product
`title` (optional) replaces the topbar title for that hat; without it the engineer's hat shows
the situation's name, never the product manager's question. An action's error may carry
`toastAction: { label, action, data }`; the hat switch shows it as the toast's key. The product
manager's stage is the shell's (`pm-stage.ts`): Investigate (no draft) → Decide (a draft) →
Delivered (submitted); primary Submit → See the result → Revise. 201 registers the engineer's.

## Agent bus — `agent-bus.ts`

```ts
emitAgentEvent(e: AgentEvent); onAgentEvent(cb) → unsubscribe; agentConnection()   // fixed
setAgentConnection(c); onAgentConnection(cb); recentAgentEvents(); resetAgentBus()
```

The agent line polls the server and emits one event per real tool call (ids are de-duplicated,
so overlapping pages are fine) and reports the connection. The topbar lamp, the board's tray and
`TransmissionStream` subscribe; a view mounted late reads `recentAgentEvents()` first.

## Toasts — `toast.ts`

```ts
toast(text, { action?: { label, action }, undo? });   // fixed
showToast(text, { label, run, long, lead });  dismissToasts()   // for function callbacks
```

One Sonner toaster for the whole app, bottom centre of the main screen (clear of the right
rail). 3.2s, or 6.5s with an action or `undo`. One toast at a time; at most one action.
`ui.js`'s `notify()` already goes through it.

## The topbar — `bar.tsx`, `bar.css`, `shellBar()` in `ui.js`

Every screen inside a practice gets the same bar from `topbar()` / `wsToolbar()`; a registered
route gets it automatically. It reads `hatOf` / `stageOf` and `agentConnection()`; you never draw
it. Actions it sends, which you may register to take over:

| action | sent by | default in `ui.js` |
|---|---|---|
| `hat-switch` (`data-hat`) | the hat switch, ⋯ at phone width | board, or the desk's last ticket / the seeded one |
| `stage-pm` (`data-step`) | a step on the product manager's scale | Delivered → result, others → board |
| `stage-engineer` (`data-step`) | a step on the engineer's scale | nothing — 201 registers it |
| `open-agent` | the agent lamp | `#/agent` once registered, else the rail's Agent tab |
| `records` | ⏱ | the rail's Activity tab — the board line registers its drawer (and `records-close`, which returns focus to ⏱) |

The primary key runs `stage.primary.action` like any button. The lamp pulses on every
`emitAgentEvent`; its label follows `setAgentConnection`.

## Keys and island components

- Native: `.btn` (secondary), `.btn.primary`, `.btn.quiet` (ghost), `.btn.icon` (32px). A reason
  under a disabled key: `<span class="key-reason">…</span>`. Loading / done:
  `setKeyState(button, 'loading' | 'done' | 'idle')`.
- Islands: `src/ui-kit` — `Button` (four variants, `state`, `reason`), `Segmented`, `Tabs` /
  `TabPanel`, `Tooltip` / `TooltipProvider`, `Sheet*` (`container` to cover only the main
  screen), `Collapsible*`, and `cn()` for merging prefixed classes.

## Rules that come with the shell

- Motion: 160 / 280 / 520ms, `--spring`, `--ease-out`, drawer `cubic-bezier(.32,.72,0,1)`;
  transform and opacity only; reduced motion → 160ms fade, no movement.
- `styles.css` `:root` belongs to the shell. Put your CSS in your own file.
