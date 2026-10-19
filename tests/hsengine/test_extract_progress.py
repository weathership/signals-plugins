# Copyright 2026 zndx
# SPDX-License-Identifier: Apache-2.0

from hsengine.engine.source_drop import extraction_stage


def test_running_with_a_progress_query_names_the_stage() -> None:
    assert extraction_stage("RUNNING", {"stage": "ocr"}) == "ocr"
    assert extraction_stage("RUNNING", {"stage": "summary"}) == "summary"


def test_a_retry_and_a_failure_are_their_own_stages() -> None:
    assert extraction_stage("RETRYING_AFTER_ERROR", None) == "retrying"
    assert extraction_stage("FAILED", None) == "failed"


def test_running_without_a_query_stays_running() -> None:
    assert extraction_stage("RUNNING", None) == "running"
