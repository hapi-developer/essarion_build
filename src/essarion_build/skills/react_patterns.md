# React patterns

- **Components are functions of props → UI; keep them pure.** Side effects belong in `useEffect`, event handlers, or external store subscriptions — never in render. Re-rendering must be safe and idempotent.
- **State lives at the lowest common ancestor of its readers.** Lifting too early creates prop-drilling; lifting too late creates stale UI. Start local; lift only when a sibling needs to read the same value.
- **`useEffect` is for synchronizing with the outside world**, not for "running code after render". If it doesn't talk to the DOM, the network, a subscription, or a timer, you probably don't need it.
- **Dependencies in `useEffect`/`useCallback`/`useMemo` must be complete.** The lint rule is correct; the trick is restructuring so the deps are small (often by reading state via a setter callback or moving the effect into an event handler).
- **Keys for lists must be stable across renders.** `key={index}` is a bug whenever items can be reordered or removed. Use the data's id.
- **Server-state vs client-state are different problems.** Server state (fetch from API) wants caching, retries, revalidation — use TanStack Query / SWR. Client state (modal open?) wants `useState` / context / Zustand. Don't mix.
- **Controlled vs uncontrolled inputs, pick one.** Controlled (`value` + `onChange`) is the default; uncontrolled (`ref`) only when interop with non-React code demands it. Mixing leads to "value not updating" bugs.
- **`useMemo`/`useCallback` are not free.** They cost a dependency comparison and a closure allocation every render. Reach for them only when profiling shows a real win, or when stability is required by a downstream `useEffect` dep list.
- **Suspense is the future of async UI.** Wrap data-loading components in `<Suspense fallback={…}>`. Combined with TanStack Query or React Router data loaders, it eliminates manual `if (loading)` branches.
- **Accessibility: semantic HTML first.** `<button>` over `<div onClick>`, `<label>` paired with inputs, `alt` on images, focus management on route changes. ARIA second, semantic HTML first.
- **Form libraries pay for themselves.** React Hook Form (or TanStack Form) handles uncontrolled state, validation, and submission with one hook. Manually wiring it leaks bugs.
- **Strict mode catches bugs.** Wrap the dev app in `<StrictMode>`. Double-invocation in dev surfaces effects that weren't idempotent.
