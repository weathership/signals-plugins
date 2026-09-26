"""Nemotron 3 Diarization worker. Run with the dedicated cu129 venv, not the engine.

The engine process must not import torch or transformers. This file is the
substrate: ``hsengine.engine.diarization`` spawns it. Streaming Sortformer,
arrival order, up to eight speakers. One model, one GPU, shared with the
agent-rtc token (the same index Moshi leased).
"""
from __future__ import annotations

import json
import os
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

# Set by the supervisor before import of torch. Do not invent a CUDA path here.
os.environ.setdefault("CUDA_VISIBLE_DEVICES", "4")

import numpy as np
import torch
from transformers import AutoModelForAudioFrameClassification, AutoProcessor

MODEL_ID = "nvidia/Nemotron-3-Diarization"
_SR = 16000


class _Session:
    def __init__(self) -> None:
        self.buf = np.zeros((0,), dtype=np.float32)
        self.started = False
        self.cache = None
        self.logits: list[torch.Tensor] = []
        self.label = ""
        self.n_speakers = 0
        self.lock = threading.Lock()


class _Server:
    def __init__(self) -> None:
        self.processor = AutoProcessor.from_pretrained(MODEL_ID)
        self.processor.set_streaming_mode("low_latency")
        self.model = AutoModelForAudioFrameClassification.from_pretrained(
            MODEL_ID, device_map="auto", dtype=torch.bfloat16
        )
        self.model.eval()
        self.sessions: dict[str, _Session] = {}
        self.mu = threading.Lock()

    def session(self, sid: str) -> _Session:
        with self.mu:
            row = self.sessions.get(sid)
            if row is None:
                row = _Session()
                self.sessions[sid] = row
            return row

    def push(self, sid: str, pcm: np.ndarray) -> dict:
        row = self.session(sid)
        with row.lock:
            if pcm.size:
                row.buf = np.concatenate([row.buf, pcm])
            self._drain(row)
            return {"label": row.label, "n_speakers": row.n_speakers, "ok": True}

    def _drain(self, row: _Session) -> None:
        proc = self.processor
        while True:
            need = (
                proc.num_samples_first_audio_chunk
                if not row.started
                else proc.num_samples_per_audio_chunk
            )
            if row.buf.size < need:
                return
            chunk = row.buf[:need]
            row.buf = row.buf[need:]
            first = not row.started
            inputs = proc(
                chunk,
                sampling_rate=_SR,
                is_streaming=True,
                is_first_audio_chunk=first,
            )
            row.started = True
            inputs = inputs.to(self.model.device, dtype=self.model.dtype)
            with torch.inference_mode():
                outputs = self.model(**inputs, speaker_cache=row.cache)
            row.cache = outputs.speaker_cache
            row.logits.append(outputs.logits.detach().to("cpu"))
            del row.logits[:-12]
            self._label(row)

    def _label(self, row: _Session) -> None:
        if not row.logits:
            return
        logits = torch.cat(row.logits, dim=1)
        try:
            segments = self.processor.extract_speaker_dict(logits)[0]
        except Exception:
            return
        if not segments:
            return
        last = segments[-1]
        row.label = f"speaker_{int(last['Speaker'])}"
        row.n_speakers = len({int(seg["Speaker"]) for seg in segments})


def serve(port: int) -> None:
    server_state = _Server()

    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def log_message(self, fmt: str, *args) -> None:
            return

        def do_GET(self) -> None:  # noqa: N802
            if self.path.rstrip("/") == "/health":
                body = json.dumps({"ok": True, "model": MODEL_ID}).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
                return
            self.send_response(404)
            self.end_headers()

        def do_POST(self) -> None:  # noqa: N802
            if self.path.rstrip("/") != "/v1/pcm":
                self.send_response(404)
                self.end_headers()
                return
            n = int(self.headers.get("Content-Length") or "0")
            raw = self.rfile.read(n) if n else b""
            sid = self.headers.get("X-Session") or "default"
            pcm = np.frombuffer(raw, dtype=np.float32).copy() if raw else np.zeros((0,), dtype=np.float32)
            try:
                result = server_state.push(sid, pcm)
                code = 200
            except Exception as exc:
                result = {"ok": False, "label": "", "n_speakers": 0, "error": str(exc)}
                code = 500
            body = json.dumps(result).encode()
            self.send_response(code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    httpd = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    httpd.serve_forever()


if __name__ == "__main__":
    serve(int(os.environ.get("NEMOTRON_DIAR_PORT", "5092")))
