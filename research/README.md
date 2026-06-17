# research/ - exploration and experiment logs

Notebooks, scratch analysis, and dated experiment notes. Nothing here is load-bearing for production; promote anything that becomes real into `features/`, `models/`, or `validation/`.

## Rules

- Exploratory work still obeys point-in-time discipline. A leaky notebook produces a misleading prior even if it never ships.
- Log experiments with dates and outcomes so dead ends aren't silently re-run.
- The hold-out set is **not** for exploration. It is touched once, in `validation/`, after freeze.
