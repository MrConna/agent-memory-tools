---
name: develop-test-first
description: Implement behavior in small red-green-refactor cycles with tests at public boundaries. Use for features, bug fixes, and behavior-preserving refactors where automated verification is practical.
---

# Develop Test First

1. Define one observable behavior and choose the narrowest public boundary that proves it.
2. Write a focused test and run it to confirm it fails for the intended reason.
3. Implement the smallest coherent change that makes the test pass.
4. Run the focused test, then the relevant suite. Refactor only while tests remain green.
5. Repeat vertically for the next behavior; avoid writing a large test batch before implementation.
6. Prefer real collaborators and stable interfaces. Mock only slow, unsafe, or genuinely external boundaries.
7. Do not weaken assertions to accommodate an incorrect implementation.
