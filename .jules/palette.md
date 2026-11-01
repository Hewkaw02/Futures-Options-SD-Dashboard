## 2026-09-16 - Accessible Keyboard Shortcut Hints

**Learning:** When adding visible keyboard shortcuts to UI elements (e.g., `<span class="kbd-hint">1</span>`), assistive technologies will often read the hint as part of the element's accessible name (e.g., "GC 1"), which can be confusing.

**Action:** Hide the visual hint from assistive technology using `aria-hidden="true"` on the hint element, and expose the shortcut programmatically via `aria-keyshortcuts` on the parent interactive element to ensure correct screen reader announcements.
