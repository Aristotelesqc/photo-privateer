"""Domain rules router."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from backend.models import DomainRuleCreate, DomainRuleOut
from backend.repositories.domain_rule_repo import DomainRuleRepository, normalize_domain
from backend.repositories.match_repo import MatchRepository
from backend.config import VALID_CLASSIFICATIONS
from backend.api.deps import get_domain_rule_repo, get_match_repo

router = APIRouter(prefix="/api/rules", tags=["rules"])

@router.get("", response_model=list[DomainRuleOut])
def list_rules(repo: DomainRuleRepository = Depends(get_domain_rule_repo)):
    return repo.list_rules()

@router.post("", response_model=DomainRuleOut)
def create_or_update_rule(
    payload: DomainRuleCreate,
    rule_repo: DomainRuleRepository = Depends(get_domain_rule_repo),
    match_repo: MatchRepository = Depends(get_match_repo),
):
    if payload.classification not in VALID_CLASSIFICATIONS:
        raise HTTPException(status_code=400, detail=f"Invalid classification: {payload.classification}")

    clean_domain = normalize_domain(payload.domain)
    if not clean_domain:
        raise HTTPException(status_code=400, detail="Invalid domain")

    rule = rule_repo.upsert_rule(
        domain=clean_domain,
        classification=payload.classification,
        notes=payload.notes,
    )

    # Automatically retroactively classify unreviewed matches for this domain
    match_repo.apply_rule_to_unreviewed_matches(
        domain=clean_domain,
        classification=payload.classification,
        rule_id=rule.id,
    )

    return rule

@router.delete("/{rule_id}")
def delete_rule(rule_id: int, repo: DomainRuleRepository = Depends(get_domain_rule_repo)):
    success = repo.delete_rule(rule_id)
    if not success:
        raise HTTPException(status_code=404, detail="Rule not found")
    return {"status": "success", "message": "Rule removed"}
