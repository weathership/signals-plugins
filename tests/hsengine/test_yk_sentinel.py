"""Agent-rtc queue names and protocol GPU packing — no Kubernetes client."""
from __future__ import annotations

import os

import pytest

from hsengine.engine import federation, yk_sentinel as yk


def test_agent_rtc_queue_uses_the_requested_leaf():
    assert yk.QUEUE == "root.internal.inference.agent-rtc"
    assert yk.RESOURCE_CLASS == "internal.inference.agent-rtc"
    assert yk.WORKLOAD_ID == "hermes-agent-rtc"
    assert yk.CEREBRAS_QUEUE == "root.external.token-metered"
    assert yk.COMPUTE_QUEUE == "root.internal.compute"
    assert yk.GPU_TOKENS == 1
    assert yk.interactive_yk_claims() == [
        (yk.QUEUE, 1),
        (yk.CEREBRAS_QUEUE, 0),
        (yk.COMPUTE_QUEUE, 0),
    ]
    assert sum(gpu for _, gpu in yk.interactive_yk_claims()) == 1


def test_pick_agent_rtc_gpu_is_the_high_end_token():
    assert yk.pick_agent_rtc_gpu(set(), 6) == 5
    assert yk.pick_agent_rtc_gpu({0, 1, 2, 3}, 6) == 5
    assert yk.pick_agent_rtc_gpu({0, 1, 2, 3, 5}, 6) == 4


def test_pick_agent_rtc_gpu_denies_when_all_pinned():
    with pytest.raises(RuntimeError, match="no free GPU"):
        yk.pick_agent_rtc_gpu({0, 1, 2, 3, 4, 5}, 6)


def test_yk_sentinel_has_no_kubernetes_client():
    for name in (
        "apply_manifest",
        "apply_sentinel",
        "apply_cerebras_thinking",
        "wait_admitted",
        "delete_sentinel",
        "_kubectl",
        "application_yaml",
        "cerebras_thinking_yaml",
        "admit",
        "release",
        "parse_gpu_rows",
    ):
        assert not hasattr(yk, name), name


def test_lease_one_gpu_takes_the_agent_rtc_slot(tmp_path, monkeypatch):
    monkeypatch.setattr(yk, "LEASE_DIR", tmp_path)
    monkeypatch.setattr(
        "hsengine.engine.federation.peer_gpu_occupancy",
        lambda: (frozenset({0, 1, 2, 3}), 6),
    )
    idx = yk.lease_one_gpu(os.getpid())
    assert idx == 5
    assert yk.our_gpu_ids() == [5]


def test_moshi_ld_path_includes_cuda():
    from hsengine.engine.moshi_supervisor import _ld_library_path

    path = _ld_library_path(None)
    assert "/usr/local/cuda/lib64" in path
    assert "nvidia-libs" in path
