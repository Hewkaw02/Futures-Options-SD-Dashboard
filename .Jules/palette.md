## 2024-05-22 - Focus Visible States for Custom Styled Elements
**Learning:** When creating highly customized UI elements with `outline: none`, keyboard navigation becomes invisible. However, simply using `:focus` can be annoying for mouse users. `:focus-visible` is the perfect solution to only show focus outlines when navigating via keyboard.
**Action:** Always pair `outline: none` with a corresponding `:focus-visible` outline that uses the design system's accent colors to maintain accessibility without compromising visual aesthetics for pointer users.
