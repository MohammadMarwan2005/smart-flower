# Smart Flower Exhibition — Experta Project Plan

A rule-based expert system that plans a delivery robot's path with **DFS** (uninformed) and **A\*** (optimal), built in Experta.

---

## 0. Guiding principles

These two rules win over everything else below if there's ever a conflict:

1. **Keep it simple.** This is a university project whose point is *using Experta to do search* — not building a fast or general planner. Always pick the simplest thing that works. No premature abstraction, no optimization we don't need, no cleverness for its own sake. The "easy" example instances are the target; we don't engineer for scale.
2. **Comment only when it helps.** Write a comment when it explains a *why* that the code can't (e.g. *why* we accept the goal on selection, *why* the load bound is pooled). Never narrate *what* obvious code already says.
3. **Work in confirmable steps.** Finish one milestone at a time. At the end of each, I'll tell you *exactly* what to run or look at, and wait for your **"good" / "not good"** before starting the next. Nothing moves forward unconfirmed — if a check fails, we fix that milestone before touching the next one.

A couple of structural choices that follow from "keep it simple":

- The **frontier lives in working memory as `State` facts** — that's also what req 5 (print all generated states) wants. We don't keep a separate Python queue.
- **DFS and A\* share the same rules.** Only the *control* differs. Build and validate DFS first, then layer A\* on top.
- One or two `.py` files is fine. No package structure.

---

## 1. Conventions & assumptions

- **Coordinates:** `(x, y)`, `x` = column (right = `+x`), `y` = row (up = `+y`). So `move-right` is `x+1`, `move-up` is `y+1`. Convert any instance input into this convention **once**, at setup. (The spec's own notation is inconsistent — we just pick this and stick to it.)
- **Load only when empty:** one full batch per warehouse visit. Keeps the load state well-defined.
- **Warehouse supply is unlimited.**
- **Max load** = the largest total number of bouquets any single pavilion needs. Computed once from the instance.
- **A pavilion's `type` and `position` are static**; only its *remaining needs* change during search.

---

## 2. Components

Build them in this order. Reqs from the assignment are noted in brackets.

### 2.1 Foundations

- **`Bag`** — one small frozen, hashable class with a readable `__repr__`. Reused for two things:
  - a **load**: keys are `(type, color)` → quantity
  - a pavilion's **needs**: keys are `color` → quantity

  Frozen+hashable is required so it can be part of the closed-set key. The readable repr is what makes the printed search tree (req 5) legible, e.g. `[tulip·yellow×2, goliat·yellow×2]`.

- **`State(Fact)`** — one fact = one search-tree node. Fields:

  | Field | Role |
  |---|---|
  | `pos`, `load`, `needs` | the **semantic** state (`needs` maps pavilion_id → `Bag` of remaining colors) |
  | `g` | cost so far |
  | `op`, `parent`, `nid` | **bookkeeping** for path reconstruction |
  | `status` | `open` / `current` / `closed` |

  Two nodes are "the same state" iff `(pos, load, needs)` match — bookkeeping doesn't count. That identity is the closed-set key.

- **`CATALOG`** — a plain module-level dict, `type → set(colors)`. Static, so it's a constant, not a fact. Rules read it directly.

### 2.2 Initial state [req 1]

- A `DefFacts` declares:
  - one **`World`** fact (grid size, warehouse position, `max_load`, and the static pavilion table `id → (type, position)`) — this is the "initial state as facts" the rubric asks for, and it prints nicely.
  - the **root `State`** node (`status='open'`, `g=0`, robot's start `pos`, empty `load`, full `needs`).
- For convenience, also cache the same static data (`World`) as a plain attribute on the engine in `reset`, so rule bodies and the heuristic can read it without threading it through every rule's LHS.

### 2.3 Successor generators [req 2]

All match the node being expanded and call one shared `spawn(...)` helper (see 2.5). Keep each rule short.

- **`move_right / move_left / move_up / move_down`** — compute the new cell, `spawn` a child with `g+1`.
- **`load`** — only when at the warehouse **and** carrying nothing. Generate candidate loads **restricted to `(type, color)` pairs some pavilion still needs** (never load what nobody wants — this is the single biggest tree-pruner). Candidates, kept simple:
  - **Option B** loads: per flower type, bundle that type's still-needed colors, capped at `max_load`.
  - **Option A** loads: per color, bundle that color across the still-needed types, capped at `max_load`.
- **`unload`** — only when on a pavilion's cell. Drop the carried bouquets whose **type matches that pavilion** and that it still needs (partial unload allowed). One `unload` op regardless of how many colors are dropped.

### 2.4 Constraints [req 3]

Simplest correct approach: **prevent illegal children at generation** rather than generate-then-reject.

- Out-of-grid moves → blocked inside `spawn` (bounds check).
- Illegal load combos → never generated (the `load` rule only builds valid Option A / Option B bundles within `max_load`).
- Unloading a non-matching type → never generated (the `unload` rule only drops matching bouquets).

> If the grader specifically wants *visibly separate* constraint-violation rules, we add a thin "reject" rule or two for demonstration — but prevention is the simple, correct default and we lead with it.

### 2.5 Closed set

- A plain Python `dict` on the engine: `seen[(pos, load, needs)] = best_g`.
- `spawn(...)` builds the child, checks bounds, then **skips it if the key was already seen with an equal-or-lower `g`**; otherwise records it and `declare`s the `State`.
- Our heuristic is **consistent**, so "first time closed = optimal" — no re-opening logic needed. This is what keeps the printed tree free of duplicate states.

### 2.6 Goal + solution output [req 4]

- A `goal_check` rule fires when a node has **empty needs and empty load**.
- On goal: walk the `parent` links (nodes kept in a `nid → State` dict) to rebuild the operation sequence, **print the path + total cost**, then `halt()`.

### 2.7 DFS control + tree printing [req 5]

- Use Experta's **default recency strategy** (which dives depth-first, as the spec notes).
- Generators match `open` states directly — *no* `current` gating in this mode.
- Print each state as it's generated (that's the search tree).
- Halt at the **first** goal found. This solution is valid but **not** guaranteed optimal — which is exactly the contrast that motivates A\*.

### 2.8 A\* control [req 6]

- **Heuristic** `h(n) = LB_unload + LB_load + LB_move`, summing three independent lower bounds (sum of lower bounds stays admissible because total cost is additive):
  - `LB_unload` = number of pavilions still unsatisfied (≥1 unload each).
  - `LB_load` = `ceil(bouquets_still_needed_but_not_already_carried / max_load)` — **pooled**, so one load can serve several pavilions. This is the term that makes the Option-A saving visible; a per-pavilion load count would **over**estimate and break optimality.
  - `LB_move` = max Manhattan distance from `pos` to any mandatory point (remaining pavilions; + warehouse if a load is still needed).

  This `h` is **admissible and consistent** → A\* returns the optimal solution and the closed set is safe.

- **Control = a 3-state lifecycle (`open / current / closed`) driven by phase salience.** Salience orders the *phases*, not the states; the actual best-first pick is a `min(...)` over the open facts inside one rule.

  | Rule | Salience | Matches | Does |
  |---|---|---|---|
  | `goal_check` | 30 | `current` + empty needs & load | reconstruct + halt |
  | generators | 20 | `current` | spawn successors as `open` |
  | `close_current` | 10 | `current` | flip to `closed` |
  | `select_best` | 0 | `NOT(current)` | scan `open`, pick min‑`f` → `current`; none → no solution |

  Cycle: `select_best` promotes the cheapest open node → if it's a goal, `goal_check` halts; otherwise generators expand it, `close_current` closes it, and `select_best` runs again.

- **Correctness landmine:** accept a goal **only when it is *selected* as `current`**, never when generated. (First goal generated ≠ optimal; first goal popped at min‑`f` = optimal.) This is why `goal_check` matches `current`.

> Note for the report: Experta's salience is *static*, so `f(n)` literally **cannot** be encoded in salience. The honest design is salience-for-phases + a Python `min()` for the priority pick. Stating this limitation is worth marks.

### 2.9 Runner / demo

- A small setup that defines an instance (World + pavilions), builds the engine, `reset()`s, and runs.
- Run **DFS** then **A\***, printing both results so the optimality gap is visible.
- Validate on:
  - **Example A** — single rose pavilion → expected cost **6**.
  - **Example B** — P2 (tulip) + P3 (goliat) share *yellow* → A\* finds the **2-trip** plan (cost **9**), DFS likely finds a worse one.
  - The assignment's **4-pavilion** example.
  - One instance with **no shared color**, where the N-trip baseline *is* optimal (proves generality).

---

## 3. Build milestones (incremental, one confirmable step at a time)

Each milestone ends with a concrete **Check & confirm** — I'll point you at exactly this, and we don't proceed until you say it's good.

1. **Foundations** — `Bag`, `State`, `CATALOG`, `World` + `DefFacts`.
   - *Check & confirm:* `reset()` declares the root `State`; printing it shows readable `pos / load / needs` (via `Bag.__repr__`). Does the root match the instance?

2. **Generators + constraints + closed set + `spawn`.**
   - *Check & confirm:* expand the root once by hand — are the children exactly the legal successors (no out-of-bounds moves, no illegal or useless loads), with no duplicates?

3. **Goal check + path/cost printing.**
   - *Check & confirm:* feed a near-goal state by hand — does `goal_check` fire, and are the printed operation path and total cost correct?

4. **DFS end-to-end** (default recency strategy).
   - *Check & confirm:* run Example A — does it find a valid solution and print the search tree? (Cost may be ≥ 6; optimality isn't expected yet.)

5. **Heuristic `h(n)` + A\* control** (lifecycle + salience).
   - *Check & confirm:* print `g`, `h`, `f` for a few states (including Example B's n4) — does `h` ever exceed the true remaining cost (it must not), and does it match the values we hand-computed?

6. **A\* end-to-end.**
   - *Check & confirm:* run Example B — does A\* return cost **9** (the 2-trip plan), and is DFS's result ≥ that?

7. **Generality pass** — remaining demo instances.
   - *Check & confirm:* do the 4-pavilion example and the no-shared-color instance return sensible optimal costs?

If any check fails, we fix that milestone before moving on.
