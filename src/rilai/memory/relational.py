"""
Relational Memory System

Evidence-linked memory that prevents confabulation by requiring
all hypotheses to cite evidence IDs.

Hybrid storage approach:
- High-confidence evidence → SQLite for long-term persistence
- Low-confidence evidence → JSON for session scope
"""

import json
import logging
import sqlite3
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional
import uuid

logger = logging.getLogger(__name__)


@dataclass
class EvidenceShard:
    """
    A piece of evidence extracted from user messages.

    Evidence shards are the ground truth that hypotheses must cite.
    They contain exact quotes from user messages.
    """
    id: str
    type: str  # vulnerability, preference, boundary, style, bio, fear, value
    quote: str  # Exact user text
    turn_id: int
    confidence: float  # [0, 1]
    timestamp: float = field(default_factory=time.time)
    context: str = ""  # Brief context around the quote

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "type": self.type,
            "quote": self.quote,
            "turn_id": self.turn_id,
            "confidence": self.confidence,
            "timestamp": self.timestamp,
            "context": self.context,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "EvidenceShard":
        return cls(
            id=data["id"],
            type=data.get("type", "unknown"),
            quote=data.get("quote", ""),
            turn_id=data.get("turn_id", 0),
            confidence=data.get("confidence", 0.5),
            timestamp=data.get("timestamp", time.time()),
            context=data.get("context", ""),
        )

    @classmethod
    def create(
        cls,
        quote: str,
        evidence_type: str,
        turn_id: int,
        confidence: float = 0.5,
        context: str = "",
    ) -> "EvidenceShard":
        """Create a new evidence shard with auto-generated ID."""
        return cls(
            id=f"ev_{uuid.uuid4().hex[:8]}",
            type=evidence_type,
            quote=quote,
            turn_id=turn_id,
            confidence=confidence,
            context=context,
        )


@dataclass
class RelationalHypothesis:
    """
    A hypothesis about the user or relationship.

    CRITICAL: Hypotheses MUST cite evidence_ids.
    Any hypothesis without evidence is considered confabulation.
    """
    h_id: str
    text: str
    p: float  # Probability [0, 1]
    evidence_ids: list[str]  # MUST cite evidence
    last_confirmed_turn: int
    decay: float = 0.95  # Per-turn decay rate
    created_turn: int = 0

    def to_dict(self) -> dict:
        return {
            "h_id": self.h_id,
            "text": self.text,
            "p": self.p,
            "evidence_ids": self.evidence_ids,
            "last_confirmed_turn": self.last_confirmed_turn,
            "decay": self.decay,
            "created_turn": self.created_turn,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "RelationalHypothesis":
        return cls(
            h_id=data["h_id"],
            text=data.get("text", ""),
            p=data.get("p", 0.5),
            evidence_ids=data.get("evidence_ids", []),
            last_confirmed_turn=data.get("last_confirmed_turn", 0),
            decay=data.get("decay", 0.95),
            created_turn=data.get("created_turn", 0),
        )

    @classmethod
    def create(
        cls,
        text: str,
        p: float,
        evidence_ids: list[str],
        turn_id: int,
    ) -> "RelationalHypothesis":
        """Create a new hypothesis with auto-generated ID."""
        if not evidence_ids:
            logger.warning(f"Creating hypothesis without evidence: {text[:50]}")
        return cls(
            h_id=f"h_{uuid.uuid4().hex[:8]}",
            text=text,
            p=p,
            evidence_ids=evidence_ids,
            last_confirmed_turn=turn_id,
            created_turn=turn_id,
        )

    def apply_decay(self, current_turn: int) -> "RelationalHypothesis":
        """Apply decay based on turns since last confirmation."""
        turns_since = current_turn - self.last_confirmed_turn
        decayed_p = self.p * (self.decay ** turns_since)
        return RelationalHypothesis(
            h_id=self.h_id,
            text=self.text,
            p=decayed_p,
            evidence_ids=self.evidence_ids,
            last_confirmed_turn=self.last_confirmed_turn,
            decay=self.decay,
            created_turn=self.created_turn,
        )

    def confirm(self, turn_id: int, new_p: Optional[float] = None) -> "RelationalHypothesis":
        """Confirm/strengthen a hypothesis."""
        return RelationalHypothesis(
            h_id=self.h_id,
            text=self.text,
            p=new_p if new_p is not None else min(1.0, self.p * 1.1),
            evidence_ids=self.evidence_ids,
            last_confirmed_turn=turn_id,
            decay=self.decay,
            created_turn=self.created_turn,
        )


@dataclass
class RelationshipMemory:
    """
    Complete relationship memory state.

    Contains:
    - summary: High-level relationship summary
    - evidence: All evidence shards
    - hypotheses: All hypotheses (must cite evidence)
    """
    summary: str = ""
    evidence: list[EvidenceShard] = field(default_factory=list)
    hypotheses: list[RelationalHypothesis] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "summary": self.summary,
            "evidence": [e.to_dict() for e in self.evidence],
            "hypotheses": [h.to_dict() for h in self.hypotheses],
        }

    @classmethod
    def from_dict(cls, data: dict) -> "RelationshipMemory":
        return cls(
            summary=data.get("summary", ""),
            evidence=[EvidenceShard.from_dict(e) for e in data.get("evidence", [])],
            hypotheses=[RelationalHypothesis.from_dict(h) for h in data.get("hypotheses", [])],
        )

    def get_evidence_by_id(self, evidence_id: str) -> Optional[EvidenceShard]:
        """Get evidence shard by ID."""
        for e in self.evidence:
            if e.id == evidence_id:
                return e
        return None

    def get_hypotheses_for_evidence(self, evidence_id: str) -> list[RelationalHypothesis]:
        """Get all hypotheses citing a specific evidence."""
        return [h for h in self.hypotheses if evidence_id in h.evidence_ids]

    def get_high_confidence_hypotheses(self, threshold: float = 0.6) -> list[RelationalHypothesis]:
        """Get hypotheses above confidence threshold."""
        return [h for h in self.hypotheses if h.p >= threshold]

    def apply_decay(self, current_turn: int) -> "RelationshipMemory":
        """Apply decay to all hypotheses."""
        return RelationshipMemory(
            summary=self.summary,
            evidence=self.evidence,
            hypotheses=[h.apply_decay(current_turn) for h in self.hypotheses],
        )

    def prune_weak_hypotheses(self, threshold: float = 0.1) -> "RelationshipMemory":
        """Remove hypotheses below threshold."""
        return RelationshipMemory(
            summary=self.summary,
            evidence=self.evidence,
            hypotheses=[h for h in self.hypotheses if h.p >= threshold],
        )


class RelationalMemoryStore:
    """
    Hybrid storage for relational memory.

    High-confidence evidence and hypotheses → SQLite
    Session-scoped data → JSON
    """

    CONFIDENCE_THRESHOLD = 0.7  # Above this → SQLite

    def __init__(self, db_path: Path, session_path: Path):
        self.db_path = db_path
        self.session_path = session_path
        self._init_db()
        self._session_memory = self._load_session()

    def _init_db(self) -> None:
        """Initialize SQLite schema."""
        self.db_path.parent.mkdir(parents=True, exist_ok=True)

        conn = sqlite3.connect(self.db_path)
        try:
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS evidence (
                    id TEXT PRIMARY KEY,
                    type TEXT NOT NULL,
                    quote TEXT NOT NULL,
                    turn_id INTEGER NOT NULL,
                    confidence REAL NOT NULL,
                    timestamp REAL NOT NULL,
                    context TEXT,
                    session_id TEXT
                );

                CREATE TABLE IF NOT EXISTS hypotheses (
                    h_id TEXT PRIMARY KEY,
                    text TEXT NOT NULL,
                    p REAL NOT NULL,
                    evidence_ids TEXT NOT NULL,  -- JSON array
                    last_confirmed_turn INTEGER NOT NULL,
                    decay REAL NOT NULL,
                    created_turn INTEGER NOT NULL,
                    session_id TEXT
                );

                CREATE INDEX IF NOT EXISTS idx_evidence_type ON evidence(type);
                CREATE INDEX IF NOT EXISTS idx_evidence_confidence ON evidence(confidence);
                CREATE INDEX IF NOT EXISTS idx_hypotheses_p ON hypotheses(p);
            """)
            conn.commit()
        finally:
            conn.close()

    def _load_session(self) -> RelationshipMemory:
        """Load session-scoped memory from JSON."""
        if self.session_path.exists():
            try:
                with open(self.session_path) as f:
                    return RelationshipMemory.from_dict(json.load(f))
            except Exception as e:
                logger.warning(f"Failed to load session memory: {e}")
        return RelationshipMemory()

    def _save_session(self) -> None:
        """Save session-scoped memory to JSON."""
        self.session_path.parent.mkdir(parents=True, exist_ok=True)
        with open(self.session_path, 'w') as f:
            json.dump(self._session_memory.to_dict(), f, indent=2)

    def add_evidence(self, evidence: EvidenceShard, session_id: str = "") -> None:
        """Add evidence shard to appropriate storage."""
        if evidence.confidence >= self.CONFIDENCE_THRESHOLD:
            # High confidence → SQLite
            conn = sqlite3.connect(self.db_path)
            try:
                conn.execute("""
                    INSERT OR REPLACE INTO evidence
                    (id, type, quote, turn_id, confidence, timestamp, context, session_id)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    evidence.id,
                    evidence.type,
                    evidence.quote,
                    evidence.turn_id,
                    evidence.confidence,
                    evidence.timestamp,
                    evidence.context,
                    session_id,
                ))
                conn.commit()
            finally:
                conn.close()
        else:
            # Low confidence → session JSON
            self._session_memory.evidence.append(evidence)
            self._save_session()

    def add_hypothesis(self, hypothesis: RelationalHypothesis, session_id: str = "") -> None:
        """Add hypothesis to appropriate storage."""
        if hypothesis.p >= self.CONFIDENCE_THRESHOLD:
            # High confidence → SQLite
            conn = sqlite3.connect(self.db_path)
            try:
                conn.execute("""
                    INSERT OR REPLACE INTO hypotheses
                    (h_id, text, p, evidence_ids, last_confirmed_turn, decay, created_turn, session_id)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    hypothesis.h_id,
                    hypothesis.text,
                    hypothesis.p,
                    json.dumps(hypothesis.evidence_ids),
                    hypothesis.last_confirmed_turn,
                    hypothesis.decay,
                    hypothesis.created_turn,
                    session_id,
                ))
                conn.commit()
            finally:
                conn.close()
        else:
            # Low confidence → session JSON
            self._session_memory.hypotheses.append(hypothesis)
            self._save_session()

    def get_all_evidence(self, session_id: str = "") -> list[EvidenceShard]:
        """Get all evidence from both stores."""
        evidence = list(self._session_memory.evidence)

        conn = sqlite3.connect(self.db_path)
        try:
            cursor = conn.execute("""
                SELECT id, type, quote, turn_id, confidence, timestamp, context
                FROM evidence
                WHERE session_id = ? OR session_id = ''
                ORDER BY turn_id DESC
            """, (session_id,))

            for row in cursor:
                evidence.append(EvidenceShard(
                    id=row[0],
                    type=row[1],
                    quote=row[2],
                    turn_id=row[3],
                    confidence=row[4],
                    timestamp=row[5],
                    context=row[6] or "",
                ))
        finally:
            conn.close()

        return evidence

    def get_all_hypotheses(self, session_id: str = "") -> list[RelationalHypothesis]:
        """Get all hypotheses from both stores."""
        hypotheses = list(self._session_memory.hypotheses)

        conn = sqlite3.connect(self.db_path)
        try:
            cursor = conn.execute("""
                SELECT h_id, text, p, evidence_ids, last_confirmed_turn, decay, created_turn
                FROM hypotheses
                WHERE session_id = ? OR session_id = ''
                ORDER BY p DESC
            """, (session_id,))

            for row in cursor:
                hypotheses.append(RelationalHypothesis(
                    h_id=row[0],
                    text=row[1],
                    p=row[2],
                    evidence_ids=json.loads(row[3]),
                    last_confirmed_turn=row[4],
                    decay=row[5],
                    created_turn=row[6],
                ))
        finally:
            conn.close()

        return hypotheses

    def get_memory(self, session_id: str = "") -> RelationshipMemory:
        """Get complete relationship memory."""
        return RelationshipMemory(
            summary=self._session_memory.summary,
            evidence=self.get_all_evidence(session_id),
            hypotheses=self.get_all_hypotheses(session_id),
        )

    def update_summary(self, summary: str) -> None:
        """Update the relationship summary."""
        self._session_memory.summary = summary
        self._save_session()

    def clear_session(self) -> None:
        """Clear session-scoped memory."""
        self._session_memory = RelationshipMemory()
        if self.session_path.exists():
            self.session_path.unlink()


def create_memory_store(data_dir: Path) -> RelationalMemoryStore:
    """Create a memory store with default paths."""
    return RelationalMemoryStore(
        db_path=data_dir / "relational.db",
        session_path=data_dir / "current" / "relational_session.json",
    )
