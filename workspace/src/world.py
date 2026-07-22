"""
world.py — WorldGraph: single owner of world identity for one run.

Replaces the previous fragmentation where one real-world thing (e.g. yt-dlp)
lived in up to five flat, string-keyed stores that could not be joined:
  capabilities["yt-dlp"] · entities["c:/.../yt-dlp.exe"] · facts["tool_path:yt-dlp"]
  · reasoning.semantic_facts["tool_path:yt-dlp"] · beliefs["yt-dlp:exists"]

Design:
  - A WorldNode has ONE identity, reachable through any alias (name, name.exe,
    dash/underscore variants, canonical path). No substring scans anywhere.
  - Edges are typed (EdgeKind). All propagation is graph traversal — never regex.
  - Lifecycle invalidation is a deterministic cascade: a PACKAGE transitioning to
    DELETED/MISSING propagates MISSING to every node it PROVIDES, transitively.
  - The overwrite-binary invariant (architecture.md invariant 3) has exactly one
    implementation: write_block_reason(). SystemState.assert_safe_overwrite and
    ExecutionPolicyGuard both delegate here — one fact, one owner.

Owns the EntityKind / EntityState enums (state.py re-exports them).
Stdlib only. In-RAM, per-run (architecture.md invariant 1: filesystem is not memory).
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Iterable, Optional

# ── Lifecycle enums (moved from state.py — world.py is their owner now) ───────


class EntityKind(str, Enum):
    EXECUTABLE = "executable"
    FILE = "file"
    DIRECTORY = "directory"
    PACKAGE = "package"
    ENV_VAR = "env_var"


class EntityState(str, Enum):
    DISCOVERED = "discovered"  # found via locate/probe, existence confirmed
    VERIFIED = "verified"  # post-action check confirmed correct state
    DIRTY = "dirty"  # exists but known-corrupt or invalid
    DELETED = "deleted"  # confirmed absent after delete step
    INSTALLED = "installed"  # package/tool confirmed installed
    MISSING = "missing"  # probed and confirmed absent


# States that a plain re-discovery must never downgrade (positive knowledge is sticky).
_STICKY_STATES = frozenset({EntityState.INSTALLED, EntityState.VERIFIED, EntityState.DIRTY})
# States meaning "this thing is not on the system".
_ABSENT_STATES = frozenset({EntityState.DELETED, EntityState.MISSING})


class EdgeKind(str, Enum):
    DEPENDS_ON = "depends_on"
    OWNS = "owns"
    USES = "uses"
    PROVIDES = "provides"  # package → executable/file it ships
    LISTENS_ON = "listens_on"
    CONFIGURES = "configures"
    CREATES = "creates"
    MODIFIES = "modifies"
    INSTALLS = "installs"
    CONFLICTS_WITH = "conflicts_with"
    REQUIRES = "requires"
    GENERATES = "generates"
    READS = "reads"
    WRITES = "writes"
    INVALIDATES = "invalidates"
    SATISFIES = "satisfies"
    BLOCKS = "blocks"


# ── Data model ─────────────────────────────────────────────────────────────────


@dataclass
class WorldNode:
    """A typed thing in the world with one identity and a lifecycle FSM."""

    id: str
    kind: EntityKind
    state: EntityState
    confidence: float = 1.0
    provenance: str = ""
    path: str = ""  # canonical fs path if known
    aliases: set[str] = field(default_factory=set)  # normalized names
    observations: list[str] = field(default_factory=list)  # bounded, human-readable
    created: float = field(default_factory=time.time)
    updated: float = field(default_factory=time.time)
    version: int = 1

    MAX_OBSERVATIONS = 8

    @property
    def exists(self) -> bool:
        return self.state not in _ABSENT_STATES

    def observe(self, note: str) -> None:
        self.observations.append(note[:120])
        self.observations = self.observations[-self.MAX_OBSERVATIONS :]
        self.updated = time.time()

    def _set_state(self, new_state: EntityState) -> None:
        self.state = new_state
        self.version += 1
        self.updated = time.time()

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "kind": self.kind.value,
            "state": self.state.value,
            "confidence": self.confidence,
            "provenance": self.provenance,
            "path": self.path,
            "aliases": sorted(self.aliases),
            "version": self.version,
            "exists": self.exists,
        }


@dataclass
class WorldEdge:
    src: str
    kind: EdgeKind
    dst: str
    provenance: str = ""
    ts: float = field(default_factory=time.time)


@dataclass
class Transition:
    """One state change, possibly caused by a cascade from another node."""

    node_id: str
    old: EntityState
    new: EntityState
    cause: str = ""  # "" = direct; otherwise the node_id whose change cascaded here


# ── Normalization (the ONLY place name/path canonicalization lives) ───────────


def norm_alias(name: str) -> str:
    """Canonical alias: basename, lowercase, no .exe, dashes folded to underscores
    (pip normalizes yt-dlp → yt_dlp; both must resolve to the same node)."""
    # Model output and persisted observations may use a different platform's separator.
    # `os.path.basename` understands only the host spelling, so Windows paths became one
    # giant basename on Linux and escaped executable overwrite protection.
    n = (name or "").strip().strip("'\"").replace("\\", "/").rsplit("/", 1)[-1]
    n = n.lower().removesuffix(".exe")
    return n.replace("-", "_")


def _norm_path(path: str) -> str:
    return (path or "").strip().strip("'\"").lower().replace("\\", "/").rstrip("/")


def _looks_like_path(s: str) -> bool:
    return ("/" in s) or ("\\" in s) or (len(s) > 1 and s[1] == ":")


# Preference order when one alias (e.g. "yt_dlp") names nodes of several kinds:
# runtime call sites (DIRTY-marking, write-block, $VAR paths) care about the
# executable first, then the package.
_RESOLVE_PREFERENCE = (
    EntityKind.EXECUTABLE,
    EntityKind.PACKAGE,
    EntityKind.FILE,
    EntityKind.DIRECTORY,
    EntityKind.ENV_VAR,
)


# ── The graph ──────────────────────────────────────────────────────────────────


class WorldGraph:
    """Typed adjacency-list graph. One node per real-world thing."""

    def __init__(self):
        self._nodes: dict[str, WorldNode] = {}
        self._out: dict[str, list[WorldEdge]] = {}
        self._in: dict[str, list[WorldEdge]] = {}
        # One alias may legitimately name nodes of different kinds
        # (package yt_dlp PROVIDES executable yt_dlp) — never merge across kinds.
        self._alias: dict[str, list[str]] = {}  # normalized alias/path → node ids
        # Canonical names the run has reasoned about, whether or not a node exists for them.
        # The belief layer registers here, so beliefs and entities share one population of
        # things rather than two string spaces that happen to look alike. See note_subject.
        self._subjects: set[str] = set()

    # ── Identity ───────────────────────────────────────────────────────────────

    def node(self, node_id: str) -> Optional[WorldNode]:
        return self._nodes.get(node_id)

    def resolve(self, name_or_path: str, kind: Optional[EntityKind] = None) -> Optional[WorldNode]:
        """Resolve any alias, name variant, or path to its node.
        Exact index lookups only — no substring scans. When several kinds share
        the alias, `kind` selects; otherwise executables win (see preference)."""
        if not name_or_path:
            return None
        candidates: list[WorldNode] = []
        if _looks_like_path(name_or_path):
            for nid in self._alias.get(_norm_path(name_or_path), []):
                candidates.append(self._nodes[nid])
        if not candidates:
            for nid in self._alias.get(norm_alias(name_or_path), []):
                candidates.append(self._nodes[nid])
        if not candidates:
            return None
        if kind is not None:
            for n in candidates:
                if n.kind == kind:
                    return n
            return None
        for preferred in _RESOLVE_PREFERENCE:
            for n in candidates:
                if n.kind == preferred:
                    return n
        return candidates[0]

    def _index(self, node: WorldNode, *names: str) -> None:
        for n in names:
            if not n:
                continue
            key = _norm_path(n) if _looks_like_path(n) else norm_alias(n)
            if not key:
                continue
            ids = self._alias.setdefault(key, [])
            if node.id not in ids:
                ids.append(node.id)
            if not _looks_like_path(n):
                node.aliases.add(key)

    # ── Mutation ───────────────────────────────────────────────────────────────

    def ensure(
        self,
        kind: EntityKind,
        *,
        name: str = "",
        path: str = "",
        state: EntityState = EntityState.DISCOVERED,
        confidence: float = 1.0,
        provenance: str = "",
    ) -> WorldNode:
        """Create or merge a node of this kind. Merging is same-kind only —
        a package never merges into an executable. Positive knowledge is sticky:
        a re-discovery (state=DISCOVERED) never downgrades INSTALLED/VERIFIED/DIRTY.
        An explicit non-DISCOVERED state (a real observation) always applies —
        an absent node that gets located again becomes present."""
        existing = self.resolve(path, kind=kind) or self.resolve(name, kind=kind)
        if existing is not None:
            if path and not existing.path:
                existing.path = path
            self._index(existing, name, path, existing.path)
            if not (existing.state in _STICKY_STATES and state == EntityState.DISCOVERED):
                if existing.state != state:
                    existing._set_state(state)
            existing.confidence = max(existing.confidence, confidence)
            if provenance:
                existing.observe(provenance)
            existing.updated = time.time()
            return existing

        node_id = _norm_path(path) if path else f"{kind.value}:{norm_alias(name)}"
        # Path collision across kinds is impossible (a path is one thing);
        # name-only ids are kind-prefixed so kinds never collide.
        node = WorldNode(
            id=node_id,
            kind=kind,
            state=state,
            confidence=confidence,
            provenance=provenance,
            path=path,
        )
        self._nodes[node_id] = node
        self._index(node, name, path, node_id)
        return node

    def link(self, src_id: str, kind: EdgeKind, dst_id: str, provenance: str = "") -> None:
        """Add a typed edge (idempotent per (src, kind, dst))."""
        if src_id not in self._nodes or dst_id not in self._nodes:
            return
        for e in self._out.get(src_id, []):
            if e.kind == kind and e.dst == dst_id:
                return
        edge = WorldEdge(src=src_id, kind=kind, dst=dst_id, provenance=provenance)
        self._out.setdefault(src_id, []).append(edge)
        self._in.setdefault(dst_id, []).append(edge)

    def set_state(
        self, node_ref: str, new_state: EntityState, provenance: str = ""
    ) -> list[Transition]:
        """Explicit lifecycle transition + deterministic invalidation cascade.

        Cascade rule (traversal, not regex): when a node becomes DELETED or
        MISSING, every node it PROVIDES becomes MISSING, transitively — a
        removed package cannot still provide a working executable.
        Returns every transition applied (direct + cascaded) so callers can
        propagate to the belief layer.
        """
        node = self.node(node_ref) or self.resolve(node_ref)
        if node is None:
            return []
        transitions: list[Transition] = []
        if node.state != new_state:
            transitions.append(Transition(node.id, node.state, new_state))
            node._set_state(new_state)
            if provenance:
                node.observe(provenance)

        if new_state in _ABSENT_STATES:
            # BFS over PROVIDES edges; visited-set bounds the traversal.
            queue = [node.id]
            visited = {node.id}
            while queue:
                cur = queue.pop(0)
                for e in self._out.get(cur, []):
                    if e.kind != EdgeKind.PROVIDES or e.dst in visited:
                        continue
                    visited.add(e.dst)
                    dep = self._nodes[e.dst]
                    if dep.state not in _ABSENT_STATES:
                        transitions.append(
                            Transition(dep.id, dep.state, EntityState.MISSING, cause=cur)
                        )
                        dep._set_state(EntityState.MISSING)
                        dep.observe(f"cascade: provider {cur} became {new_state.value}")
                    queue.append(e.dst)
        return transitions

    # ── Queries (these replace the old heuristic scans) ────────────────────────

    def provided_by(self, node_ref: str) -> list[WorldNode]:
        node = self.node(node_ref) or self.resolve(node_ref)
        if node is None:
            return []
        return [
            self._nodes[e.src] for e in self._in.get(node.id, []) if e.kind == EdgeKind.PROVIDES
        ]

    def provides(self, node_ref: str) -> list[WorldNode]:
        node = self.node(node_ref) or self.resolve(node_ref)
        if node is None:
            return []
        return [
            self._nodes[e.dst] for e in self._out.get(node.id, []) if e.kind == EdgeKind.PROVIDES
        ]

    def write_block_reason(self, path: str) -> str:
        """THE single implementation of invariant 3 (no overwrite of executables).
        Returns "" when the write is safe, otherwise the block reason."""
        node = self.resolve(path, kind=EntityKind.EXECUTABLE)
        if node is None:
            return ""
        if node.exists:
            return (
                f"SAFETY BLOCK: {path!r} is a tracked executable "
                f"(state={node.state.value}). "
                "Delete it first, then reinstall — never overwrite a binary with text."
            )
        return ""

    def latest_path(self, kinds: Iterable[EntityKind] = ()) -> str:
        """Most recently updated existing node that has a filesystem path.
        Deterministic replacement for the old 'grep facts for -> arrows' fallback
        used to fill $DISCOVERED_PATH-style vars."""
        kinds = tuple(kinds) or (EntityKind.EXECUTABLE, EntityKind.FILE, EntityKind.DIRECTORY)
        best: Optional[WorldNode] = None
        for n in self._nodes.values():
            if n.path and n.exists and n.kind in kinds:
                if best is None or n.updated > best.updated:
                    best = n
        return best.path if best else ""

    # ── High-level observations (the runtime's ingestion points) ──────────────

    def note_subject(self, alias: str) -> str:
        """Register a canonical alias as a thing the world knows about.

        The belief layer calls this for every subject it records. It deliberately creates no
        NODE: "the agent holds a belief about yt-dlp" is not the same claim as "yt-dlp exists
        as an executable at a path", and conflating them would make the world graph assert
        things nobody observed. What it guarantees is that the two layers agree on the
        population of nameable things, and on the canonical spelling of each.
        """
        canonical = norm_alias(alias)
        if canonical:
            self._subjects.add(canonical)
        return canonical

    def known_subjects(self) -> set[str]:
        return set(self._subjects)

    def observe_executable(self, name: str, path: str, provenance: str = "") -> WorldNode:
        """locate/verify found a real executable at a real path."""
        return self.ensure(
            EntityKind.EXECUTABLE,
            name=name,
            path=path,
            state=EntityState.DISCOVERED,
            confidence=1.0,
            provenance=provenance,
        )

    def observe_package(self, package: str, scope: str = "", provenance: str = "") -> WorldNode:
        """A package manager reported this package installed. Creates the package
        node, ensures the executable node of the same name (identity converges
        with any later/earlier locate via the shared alias), and records the
        PROVIDES edge that powers uninstall-invalidation cascades."""
        pkg = self.ensure(
            EntityKind.PACKAGE,
            name=package,
            state=EntityState.INSTALLED,
            confidence=0.95,
            provenance=provenance,
        )
        if scope:
            pkg.observe(f"scope={scope}")
        exe = self.ensure(
            EntityKind.EXECUTABLE,
            name=package,
            state=EntityState.INSTALLED,
            confidence=0.9,
            provenance=provenance or f"provided by package {package}",
        )
        self.link(pkg.id, EdgeKind.PROVIDES, exe.id, provenance=provenance or f"package {package}")
        return pkg

    # ── Projections ────────────────────────────────────────────────────────────

    def summary(self, limit: int = 12) -> str:
        """Compact world snapshot for prompts/telemetry."""
        if not self._nodes:
            return ""
        nodes = sorted(self._nodes.values(), key=lambda n: n.updated, reverse=True)[:limit]
        lines = ["WORLD_GRAPH:"]
        for n in nodes:
            loc = f" @ {n.path}" if n.path else ""
            lines.append(f"  [{n.kind.value}/{n.state.value}] {n.id}{loc}")
        edge_count = sum(len(v) for v in self._out.values())
        if edge_count:
            lines.append(f"  ({len(self._nodes)} nodes, {edge_count} edges)")
        return "\n".join(lines)

    def to_dict(self) -> dict:
        return {
            "nodes": {nid: n.to_dict() for nid, n in self._nodes.items()},
            "edges": [
                {"src": e.src, "kind": e.kind.value, "dst": e.dst}
                for edges in self._out.values()
                for e in edges
            ],
        }
