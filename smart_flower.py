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
        """Build a Bag from a plain dict, dropping zero-qty entries."""
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
            "grid":      (width, height),
            "warehouse": (wx, wy),
            "robot_start": (sx, sy),
            "pavilions": {id: {"type": t, "pos": (x,y), "needs": {color: qty}}}
        }
        """
        global _nid_counter
        _nid_counter = 0

        self._instance = instance
        self._nodes = {}          # nid → State fact
        self._seen  = {}          # (pos, load, needs) → best_g

        # Compute max_load = largest single-pavilion total bouquet need
        max_load = max(
            sum(instance["pavilions"][pid]["needs"].values())
            for pid in instance["pavilions"]
        )
        self._max_load = max_load

        # Static pavilion table  id → {"type": t, "pos": (x,y)}
        pav_table = {
            pid: {"type": d["type"], "pos": d["pos"]}
            for pid, d in instance["pavilions"].items()
        }
        self._pav_table = pav_table

        width, height = instance["grid"]
        self._width  = width
        self._height = height
        self._warehouse = instance["warehouse"]

        super().reset()

        # Declare World fact
        self.declare(World(
            width=width,
            height=height,
            warehouse=instance["warehouse"],
            max_load=max_load,
            pavilions=pav_table,
        ))

        # Build root needs: pavilion_id → Bag{color: qty}
        root_needs_dict = {
            pid: Bag.make(d["needs"])
            for pid, d in instance["pavilions"].items()
        }
        root_needs = Bag.make(root_needs_dict)

        root_load = Bag.make({})
        root_pos  = instance["robot_start"]
        nid = _next_nid()

        root = self.declare(State(
            pos=root_pos,
            load=root_load,
            needs=root_needs,
            g=0,
            op="start",
            parent=None,
            nid=nid,
            status="open",
        ))
        self._nodes[nid] = root


# ---------------------------------------------------------------------------
# Quick smoke-test
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

    engine = FlowerEngine()
    engine.reset(instance_A)

    # Print the World fact
    for f in engine.facts.values():
        if isinstance(f, World):
            print("World:", dict(f))

    # Print the root State
    for f in engine.facts.values():
        if isinstance(f, State):
            s = f
            print("\nRoot State:")
            print(f"  nid    = {s['nid']}")
            print(f"  pos    = {s['pos']}")
            print(f"  load   = {fmt_bag(s['load'])}")
            print(f"  needs  = {fmt_bag(s['needs'])}")
            print(f"  g      = {s['g']}")
            print(f"  op     = {s['op']}")
            print(f"  status = {s['status']}")
