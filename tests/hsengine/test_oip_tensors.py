"""OIP llm_tools_v1 tensors round-trip on the zndx profile."""
from __future__ import annotations

from types import SimpleNamespace

from hsengine.engine import oip_tensors as T
from hsengine.engine.generated.inference.v2 import open_inference_grpc_pb2 as oip_pb


def test_build_extract_tools_and_messages():
    req = T.build_infer_request(
        oip_pb,
        model_name="thinking",
        prompt="hi",
        system_prompt="sys",
        tools_json='[{"type":"function","function":{"name":"terminal"}}]',
        messages_json='[{"role":"user","content":"hi"}]',
        tool_choice="auto",
        capability="thinking",
    )
    fields = T.extract_llm_inputs(req)
    assert fields["prompt"] == "hi"
    assert fields["system_prompt"] == "sys"
    assert "terminal" in fields["tools_json"]
    assert fields["messages_json"].startswith("[")
    assert fields["tool_choice"] == "auto"


def test_response_tool_calls_json():
    resp = T.build_infer_response(
        oip_pb,
        model_name="thinking",
        completion="calling",
        finish_reason="tool_calls",
        tool_calls_json='[{"id":"1","name":"terminal","arguments":"{}"}]',
    )
    assert T.response_text(resp)[0] == "calling"
    assert "terminal" in T.response_tool_calls_json(resp)


def test_text_only_request_omits_tools_tensors():
    req = T.build_infer_request(oip_pb, model_name="thinking", prompt="x")
    names = [t.name for t in req.inputs]
    assert names == ["prompt"]
    assert "tools" not in names
