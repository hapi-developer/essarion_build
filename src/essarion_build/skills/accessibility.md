# Accessibility (a11y)

Default everything to accessible. Accessibility is a hard requirement in most jurisdictions and almost always a moral one.

- **Semantic HTML first.** `<button>` for actions, `<a>` for navigation, `<nav>` / `<main>` / `<aside>` for layout, `<label>` for inputs, `<h1>`–`<h6>` in correct order. Each carries built-in keyboard handling, screen-reader text, and focus management.
- **Keyboard everything.** Every interactive element must be reachable with `Tab`, activatable with `Enter` / `Space`, dismissable with `Escape`. If `Tab` skips it or your custom hotkey conflicts with `Alt+F4`, you have a bug.
- **Focus management on route change / modal open.** Move focus to the new region's heading (or the modal's close button). Trap focus inside modals; restore it on close. Don't make people Tab through the whole shell.
- **Alt text describes the picture's purpose**, not its appearance. Decorative? `alt=""`. Information-bearing? "Quarterly revenue chart showing 12% growth."
- **Color contrast: WCAG 2.2 AA at minimum (4.5:1 body text, 3:1 large text and UI components).** Don't rely on color alone — pair with an icon, a shape, or a label.
- **Visible focus indicator on every interactive element.** Never `outline: none` without a replacement. `:focus-visible` only when you genuinely want hover-only states distinct.
- **`aria-*` is a last resort.** Semantic HTML handles 90% of cases. Reach for `aria-label`, `aria-describedby`, `aria-live`, `aria-expanded` only when the element doesn't already convey the semantics.
- **Forms have labels, error messages associated with `aria-describedby`, and `aria-invalid` on bad fields.** Errors announced via a polite live region as the user moves between fields.
- **Skip-to-content link at the top of long shells.** Screen-reader and keyboard users shouldn't tab through the whole nav on every page.
- **Respect `prefers-reduced-motion`.** Wrap big animations in `@media (prefers-reduced-motion: no-preference) { ... }`. Vestibular disorders are real.
- **Test with the keyboard first, then a screen reader (VoiceOver / NVDA), then an automated tool (axe-core).** Automated tools catch ~30% of issues; manual catches the rest.
