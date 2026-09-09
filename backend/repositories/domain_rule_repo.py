"""Repository for domain-level classification rules."""
from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from typing import Optional
from backend.models import DomainRuleOut

def normalize_domain(domain: str) -> str:
    cleaned = domain.strip().lower()
    if cleaned.startswith("http://") or cleaned.startswith("https://"):
        from urllib.parse import urlparse
        cleaned = urlparse(cleaned).netloc
    if ":" in cleaned:
        cleaned = cleaned.split(":")[0]
    if cleaned.startswith("www."):
        cleaned = cleaned[4:]
    return cleaned

class DomainRuleRepository:
    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn

    def list_rules(self) -> list[DomainRuleOut]:
        cur = self.conn.cursor()
        cur.execute("SELECT * FROM domain_rules ORDER BY domain ASC")
        return [
            DomainRuleOut(
                id=r["id"],
                domain=r["domain"],
                classification=r["classification"],
                created_at=r["created_at"],
                updated_at=r["updated_at"],
                notes=r["notes"],
            )
            for r in cur.fetchall()
        ]

    def get_by_id(self, rule_id: int) -> Optional[DomainRuleOut]:
        cur = self.conn.cursor()
        cur.execute("SELECT * FROM domain_rules WHERE id = ?", (rule_id,))
        r = cur.fetchone()
        if not r:
            return None
        return DomainRuleOut(
            id=r["id"],
            domain=r["domain"],
            classification=r["classification"],
            created_at=r["created_at"],
            updated_at=r["updated_at"],
            notes=r["notes"],
        )

    def get_by_domain(self, domain: str) -> Optional[DomainRuleOut]:
        clean = normalize_domain(domain)
        cur = self.conn.cursor()
        cur.execute("SELECT * FROM domain_rules WHERE domain = ?", (clean,))
        r = cur.fetchone()
        if not r:
            return None
        return DomainRuleOut(
            id=r["id"],
            domain=r["domain"],
            classification=r["classification"],
            created_at=r["created_at"],
            updated_at=r["updated_at"],
            notes=r["notes"],
        )

    def find_rule_for_domain(self, domain: str) -> Optional[DomainRuleOut]:
        """Finds exact domain match or ancestor domain match (e.g. blog.foo.com -> foo.com)."""
        clean = normalize_domain(domain)
        # Try exact match first
        exact = self.get_by_domain(clean)
        if exact:
            return exact

        # Check ancestor domain parts (e.g., sub.example.com -> example.com)
        parts = clean.split(".")
        for i in range(1, len(parts) - 1):
            parent = ".".join(parts[i:])
            parent_rule = self.get_by_domain(parent)
            if parent_rule:
                return parent_rule

        return None

    def upsert_rule(self, domain: str, classification: str, notes: Optional[str] = None) -> DomainRuleOut:
        clean = normalize_domain(domain)
        now = datetime.now(timezone.utc).isoformat()
        cur = self.conn.cursor()
        cur.execute("""
            INSERT INTO domain_rules (domain, classification, created_at, updated_at, notes)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(domain) DO UPDATE SET
                classification = excluded.classification,
                updated_at = excluded.updated_at,
                notes = COALESCE(excluded.notes, domain_rules.notes)
        """, (clean, classification, now, now, notes))
        return self.get_by_domain(clean)  # type: ignore

    def delete_rule(self, rule_id: int) -> bool:
        cur = self.conn.cursor()
        cur.execute("DELETE FROM domain_rules WHERE id = ?", (rule_id,))
        return cur.rowcount > 0
