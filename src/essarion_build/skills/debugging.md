# Debugging

- **Reproduce first.** A bug you can reproduce in 10 lines is half-fixed. If you can't reproduce, your next move is instrumentation, not a fix.
- **Read the error.** The first line of the stack trace, the actual exception class, the exact line. Skipping ahead to a hypothesis without reading is how you fix the wrong thing.
- **Bisect aggressively.** Git bisect for "when did it break." Comment-out bisect for "which line." Binary search beats linear hunting.
- **One variable at a time.** Don't change three things and test — you won't know which change fixed it (or which one will bite you in production).
- **Print debugging is fine; it's just slow.** When you have a debugger, use it. Inspect frames, step into the suspect call, watch state evolve.
- **The bug is in your code 95% of the time.** "Compiler bug" / "library bug" / "OS bug" is what you say after exhausting the easier explanations. Sometimes it's true; bet the other way until proven.
- **Write the failing test before the fix.** It pins the bug, proves the fix works, and prevents regression.
- **When you're stuck: explain the bug to a rubber duck.** Out loud. The act of articulating "I expected X but got Y because Z" surfaces where your model of the system diverges from reality.
- **Take a break.** Tired debugging is anti-debugging. The bug will still be there in 20 minutes; your pattern matching will be sharper.
