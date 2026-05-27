# Python idioms

- **Comprehensions over `map`/`filter` + `lambda`.** `[x*2 for x in xs if x > 0]` reads better than `list(map(lambda x: x*2, filter(lambda x: x > 0, xs)))`.
- **Generators over lists when you don't need indexing.** `sum(x*x for x in xs)` is constant memory; `sum([x*x for x in xs])` materializes the whole list.
- **EAFP, not LBYL.** "Easier to Ask Forgiveness than Permission" — `try: d[k] / d.get(k)` over `if k in d:`. The check-then-act pattern races and double-walks the structure.
- **`with` for every resource.** Files, locks, DB connections, sockets — context managers guarantee cleanup even on exception. Don't write `try/finally close()` by hand when a `with` exists.
- **f-strings beat `.format()` and `%`.** Faster, more readable, harder to misuse. Use them.
- **Pathlib over `os.path` string-mangling.** `Path("a") / "b"` reads cleaner than `os.path.join("a", "b")` and gives you typed methods.
- **`dataclass` / `attrs` / `pydantic` over hand-rolled `__init__`.** You'll get `__repr__`, `__eq__`, and type hints for free.
- **Type hints everywhere on public APIs.** Even if you don't run a checker. They double as documentation that can't lie.
- **`enum.Enum` over string constants** for closed sets. Typo-proof and exhaustive in match statements.
- **Mutable default arguments are a trap.** `def f(x=[]):` shares the list across calls. Use `def f(x=None): x = x or []`.
- **`__all__` controls `from module import *`** and signals public API. Leading underscore on private names; the linter and your future self both check it.
- **`pyproject.toml` is the modern home.** Not `setup.py`, not `setup.cfg`, not split configs. One file.
