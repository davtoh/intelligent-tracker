"""
Repositories Package for Intelligent Tracker Persistence Subsystem.

Provides modular domain mixins for database schema management, entity CRUD,
Re-ID signatures, descriptor rollback, spatial analytics, active learning,
access control rules, offline whitelists, and hardware telemetry.
"""

from intelligent_tracker.repositories.connection import (
    SQLiteConnectionCoordinator,
    get_connection_coordinator,
)
from intelligent_tracker.repositories.schema_manager import SchemaMixin
from intelligent_tracker.repositories.entity_repo import EntityMixin
from intelligent_tracker.repositories.signature_repo import SignatureMixin
from intelligent_tracker.repositories.descriptor_repo import DescriptorMixin
from intelligent_tracker.repositories.analytics_repo import AnalyticsMixin
from intelligent_tracker.repositories.spatial_repo import SpatialMixin
from intelligent_tracker.repositories.learning_repo import LearningMixin
from intelligent_tracker.repositories.rsac_repo import RsacMixin
from intelligent_tracker.repositories.whitelist_repo import WhitelistMixin
from intelligent_tracker.repositories.telemetry_repo import TelemetryMixin
from intelligent_tracker.repositories.memory_repo import MemoryMixin

__all__ = [
    "SQLiteConnectionCoordinator",
    "get_connection_coordinator",
    "SchemaMixin",
    "EntityMixin",
    "SignatureMixin",
    "DescriptorMixin",
    "AnalyticsMixin",
    "SpatialMixin",
    "LearningMixin",
    "RsacMixin",
    "WhitelistMixin",
    "TelemetryMixin",
    "MemoryMixin",
]

