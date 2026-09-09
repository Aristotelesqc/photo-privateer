"""Domain rule evaluation engine."""
from __future__ import annotations

from typing import Optional
from backend.repositories.domain_rule_repo import DomainRuleRepository
from backend.models import DomainRuleOut

class DomainRulesEngine:
    def __init__(self, rule_repo: DomainRuleRepository):
        self.rule_repo = rule_repo

    def evaluate_domain(self, domain: str) -> Optional[DomainRuleOut]:
        """Finds matching domain rule (exact domain or parent domain)."""
        return self.rule_repo.find_rule_for_domain(domain)
