from experta import *
import math

# ---------------------------------------------------------------------------
# CATALOG  (static: type → set of colors available for that type)
# ---------------------------------------------------------------------------
CATALOG = {
    "rose":   {"red", "white", "yellow"},
    "tulip":  {"red", "white", "yellow", "pink"},
    "goliat": {"yellow", "purple", "orange"},
}


# ---------------------------------------------------------------------------
# Bag  — immutable, hashable mapping used for both loads and pavilion needs
# ---------------------------------------------------------------------------
class Bag(frozenset):
    """Frozen multiset of (key, qty) pairs. Use Bag.make({key: qty}) to build."""

    @classmethod
    def make(cls, mapping):
        return cls((k, v) for k, v in mapping.items() if v)

    def to_dict(self):
        return dict(self)

    def total(self):
        return sum(v for _, v in self)

    def __repr__(self):
        items = sorted(self, key=lambda kv: str(kv[0]))
        parts = []
        for k, v in items:
            if isinstance(k, tuple):
                parts.append(f"{k[0]}·{k[1]}×{v}")
            else:
                parts.append(f"{k}×{v}")
        return "[" + ", ".join(parts) + "]" if parts else "[]"


def fmt_bag(fs):
    """Format any frozenset-of-(key,val)-pairs as Bag repr (Experta strips subclass)."""
    return Bag.__repr__(fs)


# ---------------------------------------------------------------------------
# Facts
# ---------------------------------------------------------------------------
class World(Fact):
    """Static grid info: width, height, warehouse, max_load, pavilions."""
    pass


class State(Fact):
    """
    One search-tree node.
    pos, load, needs  — semantic state
    g                 — cost so far
    op, parent, nid   — bookkeeping
    status            — 'open' | 'current' | 'closed'
    """
    pass


# ---------------------------------------------------------------------------
# Engine
# ---------------------------------------------------------------------------
_nid_counter = 0


def _next_nid():
    global _nid_counter
    _nid_counter += 1
    return _nid_counter


class FlowerEngine(KnowledgeEngine):

    def reset(self, instance, mode="dfs"):
        """
        instance = {
            "grid":        (width, height),
            "warehouse":   (wx, wy),
            "robot_start": (sx, sy),
            "pavilions":   {id: {"type": t, "pos": (x,y), "needs": {color: qty}}}
        }
        mode = "dfs" | "astar"
        """
        global _nid_counter
        _nid_counter = 0

        self._mode      = mode
        self._verbose   = True  # set False to suppress per-node prints
        self._instance  = instance
        self._nodes     = {}    # nid → State fact
        self._seen      = {}    # (pos, load, needs) → best_g

        max_load = max(
            sum(d["needs"].values())
            for d in instance["pavilions"].values()
        )
        self._max_load = max_load

        self._pav_table = {
            pid: {"type": d["type"], "pos": d["pos"]}
            for pid, d in instance["pavilions"].items()
        }

        self._width, self._height = instance["grid"]
        self._warehouse = instance["warehouse"]

        super().reset()

        self.declare(Fact(mode=mode))           # used by mode-specific rules
        self.declare(World(
            width=self._width,
            height=self._height,
            warehouse=self._warehouse,
            max_load=max_load,
            pavilions=self._pav_table,
        ))

        root_needs = Bag.make({
            pid: Bag.make(d["needs"])
            for pid, d in instance["pavilions"].items()
        })
        nid = _next_nid()
        root = self.declare(State(
            pos=instance["robot_start"],
            load=Bag.make({}),
            needs=root_needs,
            g=0,
            op="start",
            parent=None,
            nid=nid,
            status="open",
        ))
        self._nodes[nid] = root

    # -----------------------------------------------------------------------
    # Heuristic  h(n) = LB_unload + LB_load + LB_move
    # -----------------------------------------------------------------------

    def _h(self, pos, load, needs):
        if not needs:
            return 0

        warehouse  = self._warehouse
        max_load   = self._max_load
        load_dict  = dict(load)   # (type, color) → qty

        # Aggregate total needed per (type, color) across all pavilions
        needed_tc = {}
        for pid, color_bag in needs:
            ptype = self._pav_table[pid]["type"]
            for color, qty in color_bag:
                key = (ptype, color)
                needed_tc[key] = needed_tc.get(key, 0) + qty

        total_needed = sum(needed_tc.values())
        # How much of the current load is actually useful toward those needs
        useful = sum(min(load_dict.get(k, 0), v) for k, v in needed_tc.items())
        not_carried = max(0, total_needed - useful)

        lb_unload = len(dict(needs))                                    # one unload per unsatisfied pavilion
        lb_load   = math.ceil(not_carried / max_load) if not_carried else 0  # ceil(uncarried / cap)

        # Mandatory visit targets: every unsatisfied pavilion + warehouse if more loads needed
        targets = [self._pav_table[pid]["pos"] for pid, _ in needs]
        if lb_load > 0:
            targets.append(warehouse)
        lb_move = max(abs(pos[0]-t[0]) + abs(pos[1]-t[1]) for t in targets)

        return lb_unload + lb_load + lb_move

    # -----------------------------------------------------------------------
    # spawn helper
    # -----------------------------------------------------------------------

    def _spawn(self, pos, load, needs, g, op, parent):
        x, y = pos
        if not (0 <= x < self._width and 0 <= y < self._height):
            return
        key = (pos, load, needs)
        if self._seen.get(key, float("inf")) <= g:
            return
        self._seen[key] = g
        nid = _next_nid()
        fact = self.declare(State(
            pos=pos, load=load, needs=needs, g=g,
            op=op, parent=parent, nid=nid, status="open",
        ))
        self._nodes[nid] = fact
        if self._verbose:
            h = self._h(pos, load, needs)
            print(f"  [{nid}] parent={parent}  op={op}  pos={pos}"
                  f"  g={g}  h={h}  f={g+h}"
                  f"  load={fmt_bag(load)}  needs={fmt_bag(needs)}")

    # -----------------------------------------------------------------------
    # Load candidates helper
    # -----------------------------------------------------------------------

    def _candidate_loads(self, needs_fs):
        agg = {}
        for pid, color_bag in needs_fs:
            ptype = self._pav_table[pid]["type"]
            for color, qty in color_bag:
                key = (ptype, color)
                agg[key] = agg.get(key, 0) + qty

        max_load = self._max_load
        seen = set()

        # Option B: per type — all needed colors of that type
        by_type = {}
        for (ft, c), q in agg.items():
            by_type.setdefault(ft, []).append((c, q))
        for ft in sorted(by_type):
            d, total = {}, 0
            for c, q in sorted(by_type[ft]):
                take = min(q, max_load - total)
                if take:
                    d[(ft, c)] = take
                    total += take
            if d:
                bag = Bag.make(d)
                if bag not in seen:
                    seen.add(bag)
                    yield bag

        # Option A: per color — 1 unit per type (cross-type sharing, ≥2 types)
        by_color = {}
        for (ft, c), _ in agg.items():
            by_color.setdefault(c, []).append(ft)
        for c in sorted(by_color):
            types = sorted(by_color[c])
            if len(types) < 2:
                continue
            d, total = {}, 0
            for ft in types:
                if total >= max_load:
                    break
                d[(ft, c)] = 1
                total += 1
            if d:
                bag = Bag.make(d)
                if bag not in seen:
                    seen.add(bag)
                    yield bag

    # -----------------------------------------------------------------------
    # Goal check (salience 30) — fires before generators on goal states
    # -----------------------------------------------------------------------

    @Rule(
        State(status="current", nid=MATCH.nid, g=MATCH.g,
              load=MATCH.load, needs=MATCH.needs),
        TEST(lambda load, needs: not load and not needs),
        salience=30,
    )
    def goal_check(self, nid, g, load, needs):
        path = []
        cur = nid
        while cur is not None:
            node = self._nodes[cur]
            path.append((node["op"], node["pos"], node["g"]))
            cur = node["parent"]
        path.reverse()
        print("\n=== SOLUTION ===")
        for op, pos, cost in path:
            print(f"  g={cost:3d}  {op}  @{pos}")
        print(f"Total cost: {g}")
        self.halt()

    # -----------------------------------------------------------------------
    # Generators (salience 20) — expand whichever state is current
    # -----------------------------------------------------------------------

    @Rule(State(status="current", pos=MATCH.pos, load=MATCH.load,
                needs=MATCH.needs, g=MATCH.g, nid=MATCH.nid), salience=20)
    def move_right(self, pos, load, needs, g, nid):
        self._spawn((pos[0]+1, pos[1]), load, needs, g+1, "move-right", nid)

    @Rule(State(status="current", pos=MATCH.pos, load=MATCH.load,
                needs=MATCH.needs, g=MATCH.g, nid=MATCH.nid), salience=20)
    def move_left(self, pos, load, needs, g, nid):
        self._spawn((pos[0]-1, pos[1]), load, needs, g+1, "move-left", nid)

    @Rule(State(status="current", pos=MATCH.pos, load=MATCH.load,
                needs=MATCH.needs, g=MATCH.g, nid=MATCH.nid), salience=20)
    def move_up(self, pos, load, needs, g, nid):
        self._spawn((pos[0], pos[1]+1), load, needs, g+1, "move-up", nid)

    @Rule(State(status="current", pos=MATCH.pos, load=MATCH.load,
                needs=MATCH.needs, g=MATCH.g, nid=MATCH.nid), salience=20)
    def move_down(self, pos, load, needs, g, nid):
        self._spawn((pos[0], pos[1]-1), load, needs, g+1, "move-down", nid)

    @Rule(State(status="current", pos=MATCH.pos, load=MATCH.load,
                needs=MATCH.needs, g=MATCH.g, nid=MATCH.nid), salience=20)
    def load_rule(self, pos, load, needs, g, nid):
        if pos != self._warehouse:
            return
        if load:
            return
        if not needs:
            return
        for candidate in self._candidate_loads(needs):
            self._spawn(pos, candidate, needs, g+1, "load", nid)

    @Rule(State(status="current", pos=MATCH.pos, load=MATCH.load,
                needs=MATCH.needs, g=MATCH.g, nid=MATCH.nid), salience=20)
    def unload_rule(self, pos, load, needs, g, nid):
        if not load:
            return
        pid = next((p for p, info in self._pav_table.items()
                    if info["pos"] == pos), None)
        if pid is None:
            return

        pav_type   = self._pav_table[pid]["type"]
        needs_dict = dict(needs)
        pav_bag    = needs_dict.get(pid)
        if pav_bag is None:
            return

        pav_needs = dict(pav_bag)
        load_dict = dict(load)

        deliver = {
            (ft, c): min(q, pav_needs[c])
            for (ft, c), q in load_dict.items()
            if ft == pav_type and c in pav_needs
        }
        if not deliver:
            return

        new_load_dict = dict(load_dict)
        for k, q in deliver.items():
            new_load_dict[k] -= q
            if not new_load_dict[k]:
                del new_load_dict[k]

        new_pav = dict(pav_needs)
        for (_, c), q in deliver.items():
            new_pav[c] -= q
            if not new_pav[c]:
                del new_pav[c]

        new_needs_dict = dict(needs_dict)
        if new_pav:
            new_needs_dict[pid] = Bag.make(new_pav)
        else:
            del new_needs_dict[pid]

        self._spawn(pos, Bag.make(new_load_dict), Bag.make(new_needs_dict),
                    g+1, f"unload@{pid}", nid)

    # -----------------------------------------------------------------------
    # Close current (salience 10)
    # -----------------------------------------------------------------------

    @Rule(AS.state_fact << State(status="current"), salience=10)
    def close_current(self, state_fact):
        self.modify(state_fact, status="closed")

    # -----------------------------------------------------------------------
    # DFS control: promote most-recently-declared open state (salience 5)
    # -----------------------------------------------------------------------

    @Rule(
        AS.state_fact << State(status="open"),
        NOT(State(status="current")),
        Fact(mode="dfs"),
        salience=5,
    )
    def dfs_promote(self, state_fact):
        self.modify(state_fact, status="current")

    # -----------------------------------------------------------------------
    # A* control: promote min-f open state (salience 0)
    # -----------------------------------------------------------------------

    @Rule(
        NOT(State(status="current")),
        Fact(mode="astar"),
        salience=0,
    )
    def select_best(self):
        best_fact, best_f = None, float("inf")
        for fact in self.facts.values():
            if isinstance(fact, State) and fact["status"] == "open":
                h = self._h(fact["pos"], fact["load"], fact["needs"])
                f = fact["g"] + h
                # tie-break: prefer deeper node (higher g) to reduce open-set scanning
                if f < best_f or (f == best_f and best_fact is not None
                                  and fact["g"] > best_fact["g"]):
                    best_f = f
                    best_fact = fact
        if best_fact is None:
            print("No solution found.")
            self.halt()
        else:
            self.modify(best_fact, status="current")


# ---------------------------------------------------------------------------
# Instances
# ---------------------------------------------------------------------------

# Example A: single rose pavilion.  Optimal cost = 6.
EXAMPLE_A = {
    "grid":        (5, 5),
    "warehouse":   (0, 0),
    "robot_start": (0, 0),
    "pavilions": {
        "P1": {"type": "rose", "pos": (2, 2), "needs": {"red": 2}},
    },
}

# Example B: P2 tulip + P3 goliat share yellow.  Optimal cost = 9.
# Optimal: load tulip×2 → P2(1,0) → return → load goliat×2 → P3(3,0)
EXAMPLE_B = {
    "grid":        (5, 5),
    "warehouse":   (0, 0),
    "robot_start": (0, 0),
    "pavilions": {
        "P2": {"type": "tulip",  "pos": (1, 0), "needs": {"yellow": 2}},
        "P3": {"type": "goliat", "pos": (3, 0), "needs": {"yellow": 2}},
    },
}

# 4-Pavilion example: P2+P3 share yellow (Option-A load possible),
# P1 and P4 use different colors → mixed and single-type trips combined.
EXAMPLE_4PAV = {
    "grid":        (5, 3),
    "warehouse":   (0, 0),
    "robot_start": (0, 0),
    "pavilions": {
        "P1": {"type": "rose",   "pos": (1, 0), "needs": {"red":   2}},
        "P2": {"type": "tulip",  "pos": (2, 0), "needs": {"yellow": 1}},
        "P3": {"type": "goliat", "pos": (3, 0), "needs": {"yellow": 1}},
        "P4": {"type": "rose",   "pos": (4, 0), "needs": {"white":  1}},
    },
}

# No-shared-color: P1 needs rose-red, P2 needs tulip-pink — no overlap.
# Optimal is the N-trip baseline (single-type loads only); mixing never helps.
# Optimal cost = 4 (trip1: load→P1→back) + 4 (trip2: load→P2) = 8.
EXAMPLE_NO_SHARED = {
    "grid":        (5, 1),
    "warehouse":   (0, 0),
    "robot_start": (0, 0),
    "pavilions": {
        "P1": {"type": "rose",  "pos": (1, 0), "needs": {"red":  2}},
        "P2": {"type": "tulip", "pos": (2, 0), "needs": {"pink": 2}},
    },
}


# ---------------------------------------------------------------------------
# Helper: run one instance and print a compact result line
# ---------------------------------------------------------------------------
def run_instance(name, instance, mode, show_tree=False):
    print(f"\n{'='*55}")
    print(f"  {name}  [{mode.upper()}]")
    print(f"{'='*55}")
    engine = FlowerEngine()
    engine.reset(instance, mode=mode)
    engine._verbose = show_tree
    engine.run()
    print(f"  (nodes explored: {len(engine._nodes)})")
    return engine


# ---------------------------------------------------------------------------
# Smoke-test  (Milestone 7: generality pass)
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    # Example B — already validated; run quickly as a sanity check
    run_instance("Example B", EXAMPLE_B, "dfs")
    run_instance("Example B", EXAMPLE_B, "astar")

    # 4-Pavilion example
    run_instance("4-Pavilion", EXAMPLE_4PAV, "dfs")
    run_instance("4-Pavilion", EXAMPLE_4PAV, "astar")

    # No-shared-color: A* cost must equal the N-trip baseline
    run_instance("No-shared-color", EXAMPLE_NO_SHARED, "dfs")
    run_instance("No-shared-color", EXAMPLE_NO_SHARED, "astar")
