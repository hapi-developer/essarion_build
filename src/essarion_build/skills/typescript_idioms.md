# TypeScript idioms

- **`strict: true` and `noUncheckedIndexedAccess: true`.** The default `strict` is too loose; indexed access without `noUncheckedIndexedAccess` lies about possible `undefined`. Both on.
- **Prefer union types and discriminated unions over class hierarchies.** `type Result<T> = { ok: true; value: T } | { ok: false; error: string }` lets the narrower do its job and avoids inheritance complexity.
- **`unknown` over `any`.** `any` opts out of type-checking everywhere it touches; `unknown` forces a narrowing step. Use `any` only at FFI boundaries you can't type.
- **Narrow with predicates, not casts.** `function isUser(x: unknown): x is User { … }` lets the compiler propagate the narrowing. Casts (`x as User`) lie when wrong.
- **`readonly` and `as const` for immutability.** TS doesn't enforce deep immutability, but `readonly` arrays and `as const` literals prevent the common mistakes.
- **Branded types for IDs.** `type UserId = string & { __brand: 'UserId' }` stops you from passing `OrderId` where `UserId` is expected — compile-time, zero runtime cost.
- **`never` for exhaustiveness.** In a `switch` over a union, the `default` branch should assign to `never` — the compiler then errors if you add a case to the union and forget to handle it.
- **Don't fight inferred types.** If `const x = useState(0)` already infers `number`, don't annotate. Annotate at API boundaries (function args, return types) where inference is a contract.
- **Async over callbacks.** `Promise`/`async-await`, not `(err, result) => …`. Wrap callback-style APIs in a thin promise adapter.
- **Validate at the I/O boundary** with `zod` / `valibot` / `io-ts`. The compiler can't check JSON from the network.
- **ESM, not CJS, for new code.** `"type": "module"` in `package.json`. Tooling has caught up.
- **No `var`.** `let` or `const`; almost always `const`.
