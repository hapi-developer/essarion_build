# Internationalization (i18n)

- **Translate strings, not concatenations.** `"Welcome, " + name` doesn't translate (word order, gender, plurals). Use `t("welcome", { name })` with the whole sentence in the localization file.
- **Plurals via ICU / CLDR rules**, not `if (n === 1)`. Languages have up to six plural forms; `t("items", { count })` with an ICU plural template handles them all.
- **Don't bake formatting into the message.** Numbers, dates, currencies have locale-specific shapes — use `Intl.NumberFormat`, `Intl.DateTimeFormat`, `Intl.RelativeTimeFormat`. Never hand-roll "$X.YZ".
- **Translate by key, not by source text.** "Save" might be a button label or a verb in a sentence — they need different translations. Use stable keys (`button.save`, `sentence.save_action`); let the source language be just another translation.
- **String externalization is mechanical; pseudo-localization catches it.** Run the UI with `[!! Wèlcôme !!]` style replacements; anything that's still English is a hard-coded string you missed.
- **RTL is a layout concern, not just a string concern.** `dir="rtl"` flips the page; logical CSS properties (`margin-inline-start`, `padding-block-end`) follow the writing direction. Test in both directions.
- **Storage is Unicode, end to end.** UTF-8 in source files, UTF-8 in HTTP, UTF-8 in the database (`utf8mb4` on MySQL, not `utf8`). Never `latin1`.
- **Date/time: store UTC, render in the user's timezone.** ISO 8601 in transport. Don't trust client-supplied timezones for security-sensitive boundaries.
- **Avoid text in images.** Translators can't fix it without rebuilding the asset; screen readers can't read it. SVG with `<text>` is fine.
- **Pluralize, capitalize, sort, and search all change per locale.** Use the platform's `Intl.Collator` (browsers) or `ICU::Collator` (server) for sorting; never `String.compare()` directly when display order matters.
- **Locale fallback chain explicit.** `en-GB` → `en` → default. Missing translations should fall back deterministically, not blow up.
