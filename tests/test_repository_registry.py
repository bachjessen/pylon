from pathlib import Path

import pytest

from src.repository_registry import (
    AmbiguousProjectMatch,
    ProjectCandidate,
    RepositoryRegistry,
    normalize_project_name,
    suggest_project,
)


def test_normalize_project_name() -> None:
    assert normalize_project_name("iCloudPD HA") == "icloudpdha"
    assert normalize_project_name("icloudpd-ha") == "icloudpdha"


def test_suggest_project_matches_normalized_name() -> None:
    projects = [ProjectCandidate("p1", "IPH", "iCloudPD HA")]
    assert suggest_project("icloudpd-ha", projects) == projects[0]


def test_suggest_project_returns_none_instead_of_guessing() -> None:
    projects = [ProjectCandidate("p1", "SR", "Session Relay")]
    assert suggest_project("unrelated", projects) is None


def test_suggest_project_rejects_ambiguous_match() -> None:
    projects = [
        ProjectCandidate("p1", "SR", "Session Relay"),
        ProjectCandidate("p2", "SESSIONRELAY", "Other"),
    ]
    with pytest.raises(AmbiguousProjectMatch):
        suggest_project("session-relay", projects)


def test_repository_rename_preserves_mapping(tmp_path: Path) -> None:
    registry = RepositoryRegistry(tmp_path / "registry.sqlite3")
    registry.initialize()
    project = ProjectCandidate("p1", "SR", "Session Relay")

    registry.register_repository(123, "bachjessen/session-relay")
    registry.set_mapping(123, project, source="automatic")
    registry.register_repository(123, "bachjessen/session-relay-renamed")

    mapping = registry.get_mapping(123)
    assert mapping is not None
    assert mapping.full_name == "bachjessen/session-relay-renamed"
    assert mapping.project_id == "p1"


def test_delivery_claim_is_idempotent(tmp_path: Path) -> None:
    registry = RepositoryRegistry(tmp_path / "registry.sqlite3")
    registry.initialize()
    registry.register_repository(123, "bachjessen/session-relay")

    assert registry.claim_delivery("delivery-1", "issues", 123) is True
    assert registry.claim_delivery("delivery-1", "issues", 123) is False
