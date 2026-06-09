from experta import *

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
    """
    A frozen multiset of (key, qty) pairs.
    Use Bag.make({key: qty, ...}) to build one.
    """

    @classmethod
    def make(cls, mapping):
        """Build a Bag from a plain dict, dropping zero/falsy entries."""
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
    """Format any frozenset-of-(key,val)-pairs as a Bag repr (Experta strips subclass)."""
    return Bag.__repr__(fs)


# ---------------------------------------------------------------------------
# Facts
# ---------------------------------------------------------------------------
class World(Fact):
    """
    Static grid info — declared once, never modified.
    Fields: width, height, warehouse (x,y), max_load,
            pavilions {id: {"type": t, "pos": (x,y)}}
    """
    pass


class State(Fact):
    """
    One search-tree node.
    Fields:
        pos    (x, y)
        load   Bag  {(type, color): qty}
        needs  Bag  {pavilion_id: Bag{color: qty}}   — remaining needs per pavilion
        g      int  cost so far
        op     str  operation that produced this node
        parent int  nid of parent node (None for root)
        nid    int  unique node id
        status str  'open' | 'current' | 'closed'
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

    def reset(self, instance):
        """
        instance = {
            "grid":        (width, height),
            "warehouse":   (wx, wy),
            "robot_start": (sx, sy),
            "pavilions":   {id: {"type": t, "pos": (x,y), "needs": {color: qty}}}
        }
        """
        global _nid_counter
        _nid_counter = 0

        self._instance  = instance
        self._nodes     = {}   # nid → State fact
        self._seen      = {}   # (pos, load, needs) → best_g

        max_load = max(
            sum(d["needs"].values())
            for d in instance["pavilions"].values()
        )
        self._max_load  = max_load

        self._pav_table = {
            pid: {"type": d["type"], "pos": d["pos"]}
            for pid, d in instance["pavilions"].items()
        }

        self._width, self._height = instance["grid"]
        self._warehouse = instance["warehouse"]

        super().reset()

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
        root_load = Bag.make({})
        nid = _next_nid()
        root = self.declare(State(
            pos=instance["robot_start"],
            load=root_load,
            needs=root_needs,
            g=0,
            op="start",
            parent=None,
            nid=nid,
            status="open",
        ))
        self._nodes[nid] = root

    # -----------------------------------------------------------------------
    # Helpers
    # -----------------------------------------------------------------------

    def _spawn(self, pos, load, needs, g, op, parent):
        """Declare a child State if in-bounds and not already dominated in seen."""
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
        print(f"  [{nid}] parent={parent}  op={op}  pos={pos}  g={g}"
              f"  load={fmt_bag(load)}  needs={fmt_bag(needs)}")

    def _candidate_loads(self, needs_fs):
        """Yield candidate load Bags: Option B (per-type) + Option A (cross-type, multi-type colors only)."""
        # Aggregate what's still needed: (type, color) → total_qty
        agg = {}
        for pid, color_bag in needs_fs:
            ptype = self._pav_table[pid]["type"]
            for color, qty in color_bag:
                key = (ptype, color)
                agg[key] = agg.get(key, 0) + qty

        max_load = self._max_load
        seen = set()

        # Option B: per flower type — bundle all needed colors of that type
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

        # Option A: per color — 1 unit per type (cross-type sharing)
        # Only when ≥2 types need the same color (otherwise Option B already covers it)
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
    # Successor rules
    # -----------------------------------------------------------------------

    @Rule(State(status="open", pos=MATCH.pos, load=MATCH.load,
                needs=MATCH.needs, g=MATCH.g, nid=MATCH.nid))
    def move_right(self, pos, load, needs, g, nid):
        self._spawn((pos[0]+1, pos[1]), load, needs, g+1, "move-right", nid)

    @Rule(State(status="open", pos=MATCH.pos, load=MATCH.load,
                needs=MATCH.needs, g=MATCH.g, nid=MATCH.nid))
    def move_left(self, pos, load, needs, g, nid):
        self._spawn((pos[0]-1, pos[1]), load, needs, g+1, "move-left", nid)

    @Rule(State(status="open", pos=MATCH.pos, load=MATCH.load,
                needs=MATCH.needs, g=MATCH.g, nid=MATCH.nid))
    def move_up(self, pos, load, needs, g, nid):
        self._spawn((pos[0], pos[1]+1), load, needs, g+1, "move-up", nid)

    @Rule(State(status="open", pos=MATCH.pos, load=MATCH.load,
                needs=MATCH.needs, g=MATCH.g, nid=MATCH.nid))
    def move_down(self, pos, load, needs, g, nid):
        self._spawn((pos[0], pos[1]-1), load, needs, g+1, "move-down", nid)

    @Rule(State(status="open", pos=MATCH.pos, load=MATCH.load,
                needs=MATCH.needs, g=MATCH.g, nid=MATCH.nid))
    def load_rule(self, pos, load, needs, g, nid):
        if pos != self._warehouse:
            return
        if load:          # must be empty-handed
            return
        if not needs:     # nothing left to deliver
            return
        for candidate in self._candidate_loads(needs):
            self._spawn(pos, candidate, needs, g+1, "load", nid)

    @Rule(State(status="open", pos=MATCH.pos, load=MATCH.load,
                needs=MATCH.needs, g=MATCH.g, nid=MATCH.nid))
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
            return   # pavilion already satisfied

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


# ---------------------------------------------------------------------------
# Smoke-test  (Milestone 2 check)
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    instance_A = {
        "grid":        (5, 5),
        "warehouse":   (0, 0),
        "robot_start": (0, 0),
        "pavilions": {
            "P1": {"type": "rose", "pos": (3, 2), "needs": {"red": 2}},
        },
    }

    print("=== Milestone 2: root expansion (halt after 12 generated nodes) ===")
    engine = FlowerEngine()
    engine.reset(instance_A)

    # Manually expand just the root so we can inspect its direct children
    # without running the full DFS.
    root_nid = 1
    root = engine._nodes[root_nid]
    pos   = root["pos"]
    load  = root["load"]
    needs = root["needs"]
    g     = root["g"]

    print(f"\nRoot: pos={pos}  load={fmt_bag(load)}  needs={fmt_bag(needs)}  g={g}")
    print("\nChildren of root:")
    for dx, dy, op in [(1,0,"move-right"),(-1,0,"move-left"),(0,1,"move-up"),(0,-1,"move-down")]:
        engine._spawn((pos[0]+dx, pos[1]+dy), load, needs, g+1, op, root_nid)
    if pos == engine._warehouse and not load and needs:
        for candidate in engine._candidate_loads(needs):
            engine._spawn(pos, candidate, needs, g+1, "load", root_nid)

    print(f"\nTotal nodes in memory (root + children): {len(engine._nodes)}")
    print(f"Seen set size: {len(engine._seen)}")
