"""Session materials live under s3://hermes/resources/<zettel-id>/."""
from __future__ import annotations

from hsengine.engine.resources_store import object_uri, resource_prefix


def test_resource_prefix_strips_md_and_rejects_dotdot():
    assert resource_prefix("scratch/2026-09-19/210000_catch-up.md") == (
        "resources/scratch/2026-09-19/210000_catch-up"
    )
    assert resource_prefix("../secret") == ""
    assert object_uri("scratch/x.md", "prompt.md") == (
        "s3://hermes/resources/scratch/x/prompt.md"
    )
