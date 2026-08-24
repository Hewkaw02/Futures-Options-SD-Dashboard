
## 2024-05-18 - Exposing Active Element States Programmatically

**Learning:** When elements act as toggles within a group (like the asset selector tabs `GC`, `ES`, `NQ`), visual indications (like an `.active` CSS class) are insufficient for screen readers. The active state must be programmatically communicated.

**Action:** Add `role="group"` and an appropriate `aria-label` to the container. Apply `aria-pressed="true"` to the currently active toggle and `aria-pressed="false"` to inactive toggles. Ensure any JavaScript responsible for toggling visual classes (e.g., `switchAsset` in `app.js`) is also updated to keep the `aria-pressed` states synchronized.

## 2024-08-05 - Continuous Animations & Reduced Motion

**Learning:** The dashboard utilizes continuous, infinite CSS animations (`pulse-dot`, `blink`, `pulse-glow`) for various status indicators and loaders. These can cause distraction or discomfort for users with motion sensitivities.

**Action:** Always append a `@media (prefers-reduced-motion: reduce)` block to the end of stylesheets. Within this block, disable animations (`animation: none !important;`) and transitions (`transition: none !important;`) for animated indicators and interactive elements to ensure the UI respects accessibility preferences.

## 2025-01-20 - Exposing Keyboard Shortcuts Programmatically

**Learning:** When interactive controls contain visible keyboard shortcuts (like `GC <span class="kbd-hint">1</span>`), screen readers will read the shortcut text as part of the element's accessible name (e.g. "GC 1"), causing confusion.

**Action:** Add `aria-hidden="true"` to the element containing the visible shortcut to hide it from assistive technology. Expose the shortcut programmatically by adding the `aria-keyshortcuts` attribute (e.g., `aria-keyshortcuts="1"`) to the parent interactive element (like the `<button>`).
