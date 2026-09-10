"""FastAPI dependencies for repository and service injection."""
from __future__ import annotations

import sqlite3
from typing import Generator
from fastapi import Depends
from backend.database import get_db
from backend.repositories.library_repo import LibraryRepository
from backend.repositories.image_repo import ImageRepository
from backend.repositories.domain_rule_repo import DomainRuleRepository
from backend.repositories.match_repo import MatchRepository
from backend.repositories.usage_repo import UsageRepository
from backend.repositories.settings_repo import SettingsRepository
from backend.services.thumbnail_cache import ThumbnailCache
from backend.services.image_service import ImageService
from backend.services.library_indexer import LibraryIndexer
from backend.services.domain_rules_engine import DomainRulesEngine
from backend.services.usage_tracker import UsageTracker
from backend.services.scan_engine import ScanEngine

def get_db_conn() -> Generator[sqlite3.Connection, None, None]:
    with get_db() as conn:
        yield conn

def get_library_repo(conn: sqlite3.Connection = Depends(get_db_conn)) -> LibraryRepository:
    return LibraryRepository(conn)

def get_image_repo(conn: sqlite3.Connection = Depends(get_db_conn)) -> ImageRepository:
    return ImageRepository(conn)

def get_domain_rule_repo(conn: sqlite3.Connection = Depends(get_db_conn)) -> DomainRuleRepository:
    return DomainRuleRepository(conn)

def get_match_repo(conn: sqlite3.Connection = Depends(get_db_conn)) -> MatchRepository:
    return MatchRepository(conn)

def get_usage_repo(conn: sqlite3.Connection = Depends(get_db_conn)) -> UsageRepository:
    return UsageRepository(conn)

def get_settings_repo(conn: sqlite3.Connection = Depends(get_db_conn)) -> SettingsRepository:
    return SettingsRepository(conn)

def get_thumbnail_cache() -> ThumbnailCache:
    return ThumbnailCache()

def get_image_service(
    lib_repo: LibraryRepository = Depends(get_library_repo),
) -> ImageService:
    return ImageService(lib_repo)

def get_library_indexer(
    lib_repo: LibraryRepository = Depends(get_library_repo),
    img_repo: ImageRepository = Depends(get_image_repo),
    thumb_cache: ThumbnailCache = Depends(get_thumbnail_cache),
) -> LibraryIndexer:
    return LibraryIndexer(lib_repo, img_repo, thumb_cache)

def get_domain_rules_engine(
    rule_repo: DomainRuleRepository = Depends(get_domain_rule_repo),
) -> DomainRulesEngine:
    return DomainRulesEngine(rule_repo)

def get_usage_tracker(
    usage_repo: UsageRepository = Depends(get_usage_repo),
    settings_repo: SettingsRepository = Depends(get_settings_repo),
) -> UsageTracker:
    return UsageTracker(usage_repo, settings_repo)

def get_scan_engine(
    img_repo: ImageRepository = Depends(get_image_repo),
    match_repo: MatchRepository = Depends(get_match_repo),
    rule_repo: DomainRuleRepository = Depends(get_domain_rule_repo),
    usage_repo: UsageRepository = Depends(get_usage_repo),
    settings_repo: SettingsRepository = Depends(get_settings_repo),
    lib_repo: LibraryRepository = Depends(get_library_repo),
) -> ScanEngine:
    return ScanEngine(img_repo, match_repo, rule_repo, usage_repo, settings_repo, lib_repo)

