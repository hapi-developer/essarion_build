# Code smells

A smell is not a bug — it's a signal that something is more complex, brittle, or duplicated than it should be. Reach for these as review heuristics, not as automatic rewrite triggers.

- **Long parameter list.** Six positional args is hard to call; eight is impossible to remember. Group related args into a small struct/dataclass/options object. Or split the function — maybe it does two things.
- **Feature envy.** Method `A.foo()` mostly accesses fields from `B`. Move it to `B`. Watch for `b.x`, `b.y`, `b.z` clusters inside `A`.
- **Shotgun surgery.** Adding one feature touches twelve files. Concern is smeared; consolidate.
- **Divergent change.** One class changes for many unrelated reasons (auth, billing, UI). Split along the reasons.
- **Primitive obsession.** Every quantity is a `str` or an `int`. `UserId(int)`, `Email(str)`, `Cents(int)` catch bugs the type checker otherwise can't see.
- **Boolean trap.** `do_thing(force=True, recursive=False, dry_run=True)` — call sites are unreadable, parameter order risks silent swap. Use enums or keyword-only flags with descriptive names.
- **God class.** 800-line `UserService` that owns auth, profile, billing, notifications. Split by responsibility; let the smaller classes compose.
- **Switch on type.** `if isinstance(x, A): foo() elif isinstance(x, B): bar()` — usually wants a method on A and B, dispatched polymorphically.
- **Dead flags.** A boolean parameter that has always been called with the same value. Inline it.
- **Speculative generality.** A "framework" for the one place that uses it. Build the concrete thing first; extract when there are *three* callers.
- **Comments that explain code.** If a comment is needed to understand a block, the block needs a better name or extraction. Comments are for the *why*, not the *what*.
- **Mutable shared state.** Two paths can write the same field with no coordination. Either lock it, or split ownership.
- **Long method chain.** `a.b.c.d().e()` — coupled to the entire shape of `a`. The "Law of Demeter" rule of thumb: any object should only invoke methods of its immediate friends.
- **Magic numbers.** `if days > 7: …` — what's 7? Name it (`WEEK_DAYS = 7`) or extract to config.
- **Inconsistent abstraction levels.** A function that handles HTTP, calls a service, and SQL-encodes in the same body. Split: each layer has one job.
