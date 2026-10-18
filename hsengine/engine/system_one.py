# Copyright 2026 zndx
# SPDX-License-Identifier: Apache-2.0
"""Assign subtree IRIs to word sequences with TypeSafe system-one.

Development scoring stays off Mistral. The aperture genus is the root of
the schema. Each question is one contiguous word sequence.
"""

from __future__ import annotations

import json
import os
import re
import urllib.error
import urllib.request
from pathlib import Path

_URL = "https://api.typesafe.ai/v1/systemone"
_MODEL = "jev-latest"
_NONE = "none"


def typesafe_key() -> str:
    found = os.environ.get("TYPESAFE_API_KEY", "").strip()
    if found:
        return found
    path = Path.home() / "local" / ".env"
    if not path.is_file():
        return ""
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        if line.startswith("TYPESAFE_API_KEY="):
            return line.split("=", 1)[1].strip().strip('"').strip("'")
    return ""


def word_sequences(text: str, *, sizes: tuple[int, ...] = (6, 12), stride: int = 6, limit: int = 12) -> list[dict]:
    """Contiguous word spans, with character offsets into ``text``."""

    words = [(match.start(), match.end()) for match in re.finditer(r"\S+", text or "")]
    found: list[dict] = []
    seen: set[tuple[int, int]] = set()
    for size in sizes:
        step = 0
        while step < len(words):
            chunk = words[step : step + size]
            step += stride
            if len(chunk) < 4:
                continue
            start, end = chunk[0][0], chunk[-1][1]
            if (start, end) in seen:
                continue
            seen.add((start, end))
            found.append({"start": start, "end": end, "text": text[start:end]})
            if len(found) >= limit:
                return found
    if not found and (text or "").strip():
        stripped = text.strip()
        start = text.find(stripped)
        found.append({"start": start, "end": start + len(stripped), "text": stripped})
    return found


def choice_questions(sequences: list[dict], points: list[dict]) -> dict:
    """One Choice per word sequence. Criteria keys are IRI fragments."""

    criteria = {_NONE: "None of the ontology IRIs apply to this word sequence."}
    for point in points:
        fragment = str(point.get("iri") or "").rsplit("#", 1)[-1]
        if not fragment:
            continue
        criteria[fragment] = f"{point['iri']} | {point.get('code') or ''} | {point.get('label') or ''}"
    questions = {}
    for index, seq in enumerate(sequences):
        questions[f"w{index}"] = {
            "type": "choice",
            "instructions": (
                "Which SDG ontology IRI is warranted for this word sequence? "
                "Choose none when the sequence does not state that concept.\n\n"
                f"Word sequence: {seq['text']}"
            ),
            "criteria": criteria,
        }
    return questions


def _post(state: str, questions: dict, *, opener=urllib.request.urlopen) -> dict:
    key = typesafe_key()
    if not key:
        raise RuntimeError("TYPESAFE_API_KEY is unset")
    payload = {"model": _MODEL, "state": state, "questions": questions}
    request = urllib.request.Request(
        _URL,
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {key}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        },
        method="POST",
    )
    try:
        with opener(request, timeout=60) as response:
            body = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", "replace")[:300]
        raise RuntimeError(f"typesafe systemone HTTP {exc.code}: {detail}") from exc
    if not isinstance(body, dict):
        raise RuntimeError("typesafe systemone response is not an object")
    return body


def assignments_from(body: dict, sequences: list[dict], points: list[dict], *, floor: float = 0.55) -> list[dict]:
    """Keep choices that name a subtree IRI above the confidence floor."""

    by_fragment = {str(point["iri"]).rsplit("#", 1)[-1]: point for point in points}
    answers = body.get("answers") if isinstance(body.get("answers"), dict) else body
    if not isinstance(answers, dict):
        return []
    kept = []
    for key, seq in zip(answers, sequences):
        answer = answers.get(key)
        if not isinstance(answer, dict):
            continue
        choice = str(answer.get("choice") or "")
        if not choice or choice == _NONE:
            continue
        point = by_fragment.get(choice)
        if point is None:
            continue
        try:
            confidence = float(answer.get("confidence") or 0.0)
        except (TypeError, ValueError):
            confidence = 0.0
        if confidence < floor:
            continue
        kept.append({
            "start": seq["start"],
            "end": seq["end"],
            "text": seq["text"],
            "iri": point["iri"],
            "label": point.get("label") or "",
            "confidence": confidence,
        })
    return kept


def assign_word_sequences(text: str, points: list[dict], *, post=_post) -> list[dict]:
    sequences = word_sequences(text)
    if not sequences or not points:
        return []
    body = post(text, choice_questions(sequences, points))
    return assignments_from(body, sequences, points)
