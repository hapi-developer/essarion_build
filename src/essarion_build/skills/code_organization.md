# Code organization

- **Modules group code that changes together, not code that looks alike.** A "models/" folder with one file per model invites unrelated changes; a `billing/` folder that owns models, services, and tests for billing changes in one place. Optimize for change-locality, not categorical purity.
- **The dependency graph should be acyclic at the module level.** Cycles mean two modules are pretending to be separate but aren't. Find the abstraction they really share and put it in a third module.
- **Public surface lives at the package root; everything else is `_` prefixed.** `from mylib import Client` works; `from mylib._internal import ...` is a "you know what you're doing" signal. Linter or import check in CI to keep this honest.
- **`__init__.py` is the table of contents.** Re-export the things you want callers to find; nothing else. Hide implementation modules behind underscores. The `__all__` list is the contract.
- **One concept per file. Big files are unfocused files.** 1000-line modules usually want to be 3-4 files. Split by *responsibility*, not by line count — splitting `models.py` into `models_a.py` and `models_b.py` is rearranging, not organizing.
- **Tests mirror the source tree.** `src/billing/invoice.py` ↔ `tests/billing/test_invoice.py`. Helps reviewers find the related test; helps the test runner find the right code.
- **Configuration is separate from code.** Code is checked in; config is per-environment. Tying them together (`if env == "prod":`) is the seed of every "the deploy broke because dev ≠ prod" bug.
- **Boundaries between layers are explicit, not implicit.** Domain layer doesn't import the HTTP layer; the HTTP layer can import domain. When the rule is enforced in the linter or with a package check, you stop having "domain leaked into the controller" PRs.
- **The "do not edit" file is a signal.** Generated code in repo? Mark it, include the generator command in the file header, and check the regenerated output is identical in CI. Generated code that nobody knows how to regenerate becomes unmaintainable.
- **Move toward composition, away from inheritance.** A class hierarchy three deep usually has overlapping responsibilities; flatten by injecting collaborators. Inheritance is reserved for "is-a" relationships, not "shares-some-behavior" ones.
- **`README.md` per module is overkill; one per package is right.** Caller-facing docs at the top; implementation notes inside. A doc that has to explain the whole module to be useful is documenting a too-large module.
