# State management

- **State has a source of truth.** Server state lives on the server; cache it client-side, but the server is canonical. Client state lives in one place per concept; duplicates drift.
- **Separate server cache from client UI state.** TanStack Query / SWR / RTK Query for server data (refetch, invalidate, dedupe). `useState` / Zustand / Redux for UI state (modal open, draft form, selected tab). Mixing them creates "the modal won't open because the API is loading" bugs.
- **Lift state to the lowest common ancestor of its readers.** Premature lifting causes prop drilling and unrelated re-renders; late lifting causes stale UI when siblings need the same value. Start local; lift when there's a real need.
- **Derived state is computed, not stored.** `filtered = items.filter(p)` — recompute on render. Storing it creates two sources of truth that desync. If the computation is expensive, `useMemo` (or `createSelector` with reselect).
- **Atomic state updates over multi-step.** `setUser(u => ({...u, name: 'X'}))`, not `setUser({...user, name: 'X'})`. Avoids races and stale closures.
- **Reducers when state transitions are non-trivial.** When state has many fields that move together (or have invariants like "only one tab can be active"), a reducer enforces the shape. Use a `useReducer` (or Zustand / Redux Toolkit slice) and discrimianted-union action types.
- **Forms have their own state model.** Don't put every keystroke in the global store. Local component state (or a form library: React Hook Form / Formik / TanStack Form) until submit, then promote the result.
- **Global state is for genuinely global concerns** — auth, theme, current org. Everything else should be local first; promote only when you measure prop-drilling pain.
- **Immutability isn't dogma — it's predictability.** When you mutate, React (or Redux, or Zustand without Immer) can miss the change. Stick to `{...obj, key: val}` and `[...arr, x]` patterns; reach for Immer if nesting hurts.
- **Persisted state is part of the data model.** `localStorage` / `sessionStorage` / IndexedDB are storage; they need schemas, migrations, and error handling like any DB.
- **Hydration mismatches are a real bug class in SSR.** The server-rendered HTML must match the client's first render exactly; any state that differs (random IDs, locale-dependent dates) must be deferred to `useEffect`.
