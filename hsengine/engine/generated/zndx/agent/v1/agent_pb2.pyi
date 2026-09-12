from hsengine.engine.generated.zndx.engine.v1 import engine_pb2 as _engine_pb2
from google.protobuf.internal import containers as _containers
from google.protobuf.internal import enum_type_wrapper as _enum_type_wrapper
from google.protobuf import descriptor as _descriptor
from google.protobuf import message as _message
from collections.abc import Iterable as _Iterable, Mapping as _Mapping
from typing import ClassVar as _ClassVar, Optional as _Optional, Union as _Union

DESCRIPTOR: _descriptor.FileDescriptor

class AgentTransport(int, metaclass=_enum_type_wrapper.EnumTypeWrapper):
    __slots__ = ()
    AGENT_TRANSPORT_UNSPECIFIED: _ClassVar[AgentTransport]
    AGENT_TRANSPORT_ACP: _ClassVar[AgentTransport]
    AGENT_TRANSPORT_SDK: _ClassVar[AgentTransport]
    AGENT_TRANSPORT_CLI: _ClassVar[AgentTransport]
    AGENT_TRANSPORT_ENGINE: _ClassVar[AgentTransport]

class McpTransport(int, metaclass=_enum_type_wrapper.EnumTypeWrapper):
    __slots__ = ()
    MCP_TRANSPORT_UNSPECIFIED: _ClassVar[McpTransport]
    MCP_TRANSPORT_HTTP: _ClassVar[McpTransport]
    MCP_TRANSPORT_STDIO: _ClassVar[McpTransport]

class Billing(int, metaclass=_enum_type_wrapper.EnumTypeWrapper):
    __slots__ = ()
    BILLING_UNSPECIFIED: _ClassVar[Billing]
    BILLING_LOCAL: _ClassVar[Billing]
    BILLING_SUBSCRIPTION: _ClassVar[Billing]
    BILLING_TOKEN_METERED: _ClassVar[Billing]

class RunState(int, metaclass=_enum_type_wrapper.EnumTypeWrapper):
    __slots__ = ()
    RUN_STATE_UNSPECIFIED: _ClassVar[RunState]
    RUN_QUEUED: _ClassVar[RunState]
    RUN_RUNNING: _ClassVar[RunState]
    RUN_COMPLETED: _ClassVar[RunState]
    RUN_FAILED: _ClassVar[RunState]
    RUN_CANCELLED: _ClassVar[RunState]
    RUN_BUDGET_EXHAUSTED: _ClassVar[RunState]
AGENT_TRANSPORT_UNSPECIFIED: AgentTransport
AGENT_TRANSPORT_ACP: AgentTransport
AGENT_TRANSPORT_SDK: AgentTransport
AGENT_TRANSPORT_CLI: AgentTransport
AGENT_TRANSPORT_ENGINE: AgentTransport
MCP_TRANSPORT_UNSPECIFIED: McpTransport
MCP_TRANSPORT_HTTP: McpTransport
MCP_TRANSPORT_STDIO: McpTransport
BILLING_UNSPECIFIED: Billing
BILLING_LOCAL: Billing
BILLING_SUBSCRIPTION: Billing
BILLING_TOKEN_METERED: Billing
RUN_STATE_UNSPECIFIED: RunState
RUN_QUEUED: RunState
RUN_RUNNING: RunState
RUN_COMPLETED: RunState
RUN_FAILED: RunState
RUN_CANCELLED: RunState
RUN_BUDGET_EXHAUSTED: RunState

class AgentOffer(_message.Message):
    __slots__ = ("agent_id", "project", "name", "version", "transport", "model_capabilities", "mcp", "workspace", "behaviours", "kwargs_schema_json", "billing", "note")
    AGENT_ID_FIELD_NUMBER: _ClassVar[int]
    PROJECT_FIELD_NUMBER: _ClassVar[int]
    NAME_FIELD_NUMBER: _ClassVar[int]
    VERSION_FIELD_NUMBER: _ClassVar[int]
    TRANSPORT_FIELD_NUMBER: _ClassVar[int]
    MODEL_CAPABILITIES_FIELD_NUMBER: _ClassVar[int]
    MCP_FIELD_NUMBER: _ClassVar[int]
    WORKSPACE_FIELD_NUMBER: _ClassVar[int]
    BEHAVIOURS_FIELD_NUMBER: _ClassVar[int]
    KWARGS_SCHEMA_JSON_FIELD_NUMBER: _ClassVar[int]
    BILLING_FIELD_NUMBER: _ClassVar[int]
    NOTE_FIELD_NUMBER: _ClassVar[int]
    agent_id: str
    project: str
    name: str
    version: str
    transport: AgentTransport
    model_capabilities: _containers.RepeatedScalarFieldContainer[str]
    mcp: _containers.RepeatedScalarFieldContainer[McpTransport]
    workspace: bool
    behaviours: _containers.RepeatedScalarFieldContainer[str]
    kwargs_schema_json: str
    billing: Billing
    note: str
    def __init__(self, agent_id: _Optional[str] = ..., project: _Optional[str] = ..., name: _Optional[str] = ..., version: _Optional[str] = ..., transport: _Optional[_Union[AgentTransport, str]] = ..., model_capabilities: _Optional[_Iterable[str]] = ..., mcp: _Optional[_Iterable[_Union[McpTransport, str]]] = ..., workspace: _Optional[bool] = ..., behaviours: _Optional[_Iterable[str]] = ..., kwargs_schema_json: _Optional[str] = ..., billing: _Optional[_Union[Billing, str]] = ..., note: _Optional[str] = ...) -> None: ...

class ListAgentsRequest(_message.Message):
    __slots__ = ()
    def __init__(self) -> None: ...

class ListAgentsResponse(_message.Message):
    __slots__ = ("project", "agents")
    PROJECT_FIELD_NUMBER: _ClassVar[int]
    AGENTS_FIELD_NUMBER: _ClassVar[int]
    project: str
    agents: _containers.RepeatedCompositeFieldContainer[AgentOffer]
    def __init__(self, project: _Optional[str] = ..., agents: _Optional[_Iterable[_Union[AgentOffer, _Mapping]]] = ...) -> None: ...

class McpServerRef(_message.Message):
    __slots__ = ("name", "transport", "url", "command", "args", "env", "description")
    class EnvEntry(_message.Message):
        __slots__ = ("key", "value")
        KEY_FIELD_NUMBER: _ClassVar[int]
        VALUE_FIELD_NUMBER: _ClassVar[int]
        key: str
        value: str
        def __init__(self, key: _Optional[str] = ..., value: _Optional[str] = ...) -> None: ...
    NAME_FIELD_NUMBER: _ClassVar[int]
    TRANSPORT_FIELD_NUMBER: _ClassVar[int]
    URL_FIELD_NUMBER: _ClassVar[int]
    COMMAND_FIELD_NUMBER: _ClassVar[int]
    ARGS_FIELD_NUMBER: _ClassVar[int]
    ENV_FIELD_NUMBER: _ClassVar[int]
    DESCRIPTION_FIELD_NUMBER: _ClassVar[int]
    name: str
    transport: McpTransport
    url: str
    command: str
    args: _containers.RepeatedScalarFieldContainer[str]
    env: _containers.ScalarMap[str, str]
    description: str
    def __init__(self, name: _Optional[str] = ..., transport: _Optional[_Union[McpTransport, str]] = ..., url: _Optional[str] = ..., command: _Optional[str] = ..., args: _Optional[_Iterable[str]] = ..., env: _Optional[_Mapping[str, str]] = ..., description: _Optional[str] = ...) -> None: ...

class RunBudget(_message.Message):
    __slots__ = ("max_turns", "max_tokens", "max_seconds")
    MAX_TURNS_FIELD_NUMBER: _ClassVar[int]
    MAX_TOKENS_FIELD_NUMBER: _ClassVar[int]
    MAX_SECONDS_FIELD_NUMBER: _ClassVar[int]
    max_turns: int
    max_tokens: int
    max_seconds: int
    def __init__(self, max_turns: _Optional[int] = ..., max_tokens: _Optional[int] = ..., max_seconds: _Optional[int] = ...) -> None: ...

class RunRequest(_message.Message):
    __slots__ = ("agent", "model_capability", "method_capability", "instruction", "system_prompt", "workspace_uri", "mcp_servers", "kwargs_json", "budget", "run_id", "tx_id", "reason", "timezone", "clock_json")
    AGENT_FIELD_NUMBER: _ClassVar[int]
    MODEL_CAPABILITY_FIELD_NUMBER: _ClassVar[int]
    METHOD_CAPABILITY_FIELD_NUMBER: _ClassVar[int]
    INSTRUCTION_FIELD_NUMBER: _ClassVar[int]
    SYSTEM_PROMPT_FIELD_NUMBER: _ClassVar[int]
    WORKSPACE_URI_FIELD_NUMBER: _ClassVar[int]
    MCP_SERVERS_FIELD_NUMBER: _ClassVar[int]
    KWARGS_JSON_FIELD_NUMBER: _ClassVar[int]
    BUDGET_FIELD_NUMBER: _ClassVar[int]
    RUN_ID_FIELD_NUMBER: _ClassVar[int]
    TX_ID_FIELD_NUMBER: _ClassVar[int]
    REASON_FIELD_NUMBER: _ClassVar[int]
    TIMEZONE_FIELD_NUMBER: _ClassVar[int]
    CLOCK_JSON_FIELD_NUMBER: _ClassVar[int]
    agent: str
    model_capability: str
    method_capability: str
    instruction: str
    system_prompt: str
    workspace_uri: str
    mcp_servers: _containers.RepeatedCompositeFieldContainer[McpServerRef]
    kwargs_json: str
    budget: RunBudget
    run_id: str
    tx_id: str
    reason: str
    timezone: str
    clock_json: str
    def __init__(self, agent: _Optional[str] = ..., model_capability: _Optional[str] = ..., method_capability: _Optional[str] = ..., instruction: _Optional[str] = ..., system_prompt: _Optional[str] = ..., workspace_uri: _Optional[str] = ..., mcp_servers: _Optional[_Iterable[_Union[McpServerRef, _Mapping]]] = ..., kwargs_json: _Optional[str] = ..., budget: _Optional[_Union[RunBudget, _Mapping]] = ..., run_id: _Optional[str] = ..., tx_id: _Optional[str] = ..., reason: _Optional[str] = ..., timezone: _Optional[str] = ..., clock_json: _Optional[str] = ...) -> None: ...

class RunAccepted(_message.Message):
    __slots__ = ("run_id", "agent_id", "model", "model_peer", "profile", "activity_id", "workspace_uri")
    RUN_ID_FIELD_NUMBER: _ClassVar[int]
    AGENT_ID_FIELD_NUMBER: _ClassVar[int]
    MODEL_FIELD_NUMBER: _ClassVar[int]
    MODEL_PEER_FIELD_NUMBER: _ClassVar[int]
    PROFILE_FIELD_NUMBER: _ClassVar[int]
    ACTIVITY_ID_FIELD_NUMBER: _ClassVar[int]
    WORKSPACE_URI_FIELD_NUMBER: _ClassVar[int]
    run_id: str
    agent_id: str
    model: str
    model_peer: str
    profile: _engine_pb2.OperatingProfile
    activity_id: str
    workspace_uri: str
    def __init__(self, run_id: _Optional[str] = ..., agent_id: _Optional[str] = ..., model: _Optional[str] = ..., model_peer: _Optional[str] = ..., profile: _Optional[_Union[_engine_pb2.OperatingProfile, _Mapping]] = ..., activity_id: _Optional[str] = ..., workspace_uri: _Optional[str] = ...) -> None: ...

class Message(_message.Message):
    __slots__ = ("turn", "role", "text")
    TURN_FIELD_NUMBER: _ClassVar[int]
    ROLE_FIELD_NUMBER: _ClassVar[int]
    TEXT_FIELD_NUMBER: _ClassVar[int]
    turn: int
    role: str
    text: str
    def __init__(self, turn: _Optional[int] = ..., role: _Optional[str] = ..., text: _Optional[str] = ...) -> None: ...

class ToolCall(_message.Message):
    __slots__ = ("turn", "call_id", "name", "arguments_json", "server")
    TURN_FIELD_NUMBER: _ClassVar[int]
    CALL_ID_FIELD_NUMBER: _ClassVar[int]
    NAME_FIELD_NUMBER: _ClassVar[int]
    ARGUMENTS_JSON_FIELD_NUMBER: _ClassVar[int]
    SERVER_FIELD_NUMBER: _ClassVar[int]
    turn: int
    call_id: str
    name: str
    arguments_json: str
    server: str
    def __init__(self, turn: _Optional[int] = ..., call_id: _Optional[str] = ..., name: _Optional[str] = ..., arguments_json: _Optional[str] = ..., server: _Optional[str] = ...) -> None: ...

class ToolResult(_message.Message):
    __slots__ = ("turn", "call_id", "content", "is_error", "latency_ms")
    TURN_FIELD_NUMBER: _ClassVar[int]
    CALL_ID_FIELD_NUMBER: _ClassVar[int]
    CONTENT_FIELD_NUMBER: _ClassVar[int]
    IS_ERROR_FIELD_NUMBER: _ClassVar[int]
    LATENCY_MS_FIELD_NUMBER: _ClassVar[int]
    turn: int
    call_id: str
    content: str
    is_error: bool
    latency_ms: int
    def __init__(self, turn: _Optional[int] = ..., call_id: _Optional[str] = ..., content: _Optional[str] = ..., is_error: _Optional[bool] = ..., latency_ms: _Optional[int] = ...) -> None: ...

class Deliverable(_message.Message):
    __slots__ = ("turn", "uri", "content_type", "bytes", "sha256", "product_id", "inline", "note")
    TURN_FIELD_NUMBER: _ClassVar[int]
    URI_FIELD_NUMBER: _ClassVar[int]
    CONTENT_TYPE_FIELD_NUMBER: _ClassVar[int]
    BYTES_FIELD_NUMBER: _ClassVar[int]
    SHA256_FIELD_NUMBER: _ClassVar[int]
    PRODUCT_ID_FIELD_NUMBER: _ClassVar[int]
    INLINE_FIELD_NUMBER: _ClassVar[int]
    NOTE_FIELD_NUMBER: _ClassVar[int]
    turn: int
    uri: str
    content_type: str
    bytes: int
    sha256: str
    product_id: str
    inline: bytes
    note: str
    def __init__(self, turn: _Optional[int] = ..., uri: _Optional[str] = ..., content_type: _Optional[str] = ..., bytes: _Optional[int] = ..., sha256: _Optional[str] = ..., product_id: _Optional[str] = ..., inline: _Optional[bytes] = ..., note: _Optional[str] = ...) -> None: ...

class Progress(_message.Message):
    __slots__ = ("phase", "step", "turn", "detail")
    PHASE_FIELD_NUMBER: _ClassVar[int]
    STEP_FIELD_NUMBER: _ClassVar[int]
    TURN_FIELD_NUMBER: _ClassVar[int]
    DETAIL_FIELD_NUMBER: _ClassVar[int]
    phase: str
    step: str
    turn: int
    detail: str
    def __init__(self, phase: _Optional[str] = ..., step: _Optional[str] = ..., turn: _Optional[int] = ..., detail: _Optional[str] = ...) -> None: ...

class Usage(_message.Message):
    __slots__ = ("turns", "prompt_tokens", "completion_tokens", "tool_calls", "wall_ms")
    TURNS_FIELD_NUMBER: _ClassVar[int]
    PROMPT_TOKENS_FIELD_NUMBER: _ClassVar[int]
    COMPLETION_TOKENS_FIELD_NUMBER: _ClassVar[int]
    TOOL_CALLS_FIELD_NUMBER: _ClassVar[int]
    WALL_MS_FIELD_NUMBER: _ClassVar[int]
    turns: int
    prompt_tokens: int
    completion_tokens: int
    tool_calls: int
    wall_ms: int
    def __init__(self, turns: _Optional[int] = ..., prompt_tokens: _Optional[int] = ..., completion_tokens: _Optional[int] = ..., tool_calls: _Optional[int] = ..., wall_ms: _Optional[int] = ...) -> None: ...

class RunDone(_message.Message):
    __slots__ = ("state", "stop_reason", "result_text", "usage", "trajectory_uri", "trajectory_format", "trajectory_product_id", "error")
    STATE_FIELD_NUMBER: _ClassVar[int]
    STOP_REASON_FIELD_NUMBER: _ClassVar[int]
    RESULT_TEXT_FIELD_NUMBER: _ClassVar[int]
    USAGE_FIELD_NUMBER: _ClassVar[int]
    TRAJECTORY_URI_FIELD_NUMBER: _ClassVar[int]
    TRAJECTORY_FORMAT_FIELD_NUMBER: _ClassVar[int]
    TRAJECTORY_PRODUCT_ID_FIELD_NUMBER: _ClassVar[int]
    ERROR_FIELD_NUMBER: _ClassVar[int]
    state: RunState
    stop_reason: str
    result_text: str
    usage: Usage
    trajectory_uri: str
    trajectory_format: str
    trajectory_product_id: str
    error: str
    def __init__(self, state: _Optional[_Union[RunState, str]] = ..., stop_reason: _Optional[str] = ..., result_text: _Optional[str] = ..., usage: _Optional[_Union[Usage, _Mapping]] = ..., trajectory_uri: _Optional[str] = ..., trajectory_format: _Optional[str] = ..., trajectory_product_id: _Optional[str] = ..., error: _Optional[str] = ...) -> None: ...

class AgentEvent(_message.Message):
    __slots__ = ("run_id", "seq", "at_unix_ms", "accepted", "thought", "message", "tool_call", "tool_result", "deliverable", "progress", "done")
    RUN_ID_FIELD_NUMBER: _ClassVar[int]
    SEQ_FIELD_NUMBER: _ClassVar[int]
    AT_UNIX_MS_FIELD_NUMBER: _ClassVar[int]
    ACCEPTED_FIELD_NUMBER: _ClassVar[int]
    THOUGHT_FIELD_NUMBER: _ClassVar[int]
    MESSAGE_FIELD_NUMBER: _ClassVar[int]
    TOOL_CALL_FIELD_NUMBER: _ClassVar[int]
    TOOL_RESULT_FIELD_NUMBER: _ClassVar[int]
    DELIVERABLE_FIELD_NUMBER: _ClassVar[int]
    PROGRESS_FIELD_NUMBER: _ClassVar[int]
    DONE_FIELD_NUMBER: _ClassVar[int]
    run_id: str
    seq: int
    at_unix_ms: int
    accepted: RunAccepted
    thought: _engine_pb2.ReasoningLayer
    message: Message
    tool_call: ToolCall
    tool_result: ToolResult
    deliverable: Deliverable
    progress: Progress
    done: RunDone
    def __init__(self, run_id: _Optional[str] = ..., seq: _Optional[int] = ..., at_unix_ms: _Optional[int] = ..., accepted: _Optional[_Union[RunAccepted, _Mapping]] = ..., thought: _Optional[_Union[_engine_pb2.ReasoningLayer, _Mapping]] = ..., message: _Optional[_Union[Message, _Mapping]] = ..., tool_call: _Optional[_Union[ToolCall, _Mapping]] = ..., tool_result: _Optional[_Union[ToolResult, _Mapping]] = ..., deliverable: _Optional[_Union[Deliverable, _Mapping]] = ..., progress: _Optional[_Union[Progress, _Mapping]] = ..., done: _Optional[_Union[RunDone, _Mapping]] = ...) -> None: ...

class CancelRequest(_message.Message):
    __slots__ = ("run_id", "reason")
    RUN_ID_FIELD_NUMBER: _ClassVar[int]
    REASON_FIELD_NUMBER: _ClassVar[int]
    run_id: str
    reason: str
    def __init__(self, run_id: _Optional[str] = ..., reason: _Optional[str] = ...) -> None: ...

class CancelResponse(_message.Message):
    __slots__ = ("accepted", "state", "error")
    ACCEPTED_FIELD_NUMBER: _ClassVar[int]
    STATE_FIELD_NUMBER: _ClassVar[int]
    ERROR_FIELD_NUMBER: _ClassVar[int]
    accepted: bool
    state: RunState
    error: str
    def __init__(self, accepted: _Optional[bool] = ..., state: _Optional[_Union[RunState, str]] = ..., error: _Optional[str] = ...) -> None: ...

class GetRunRequest(_message.Message):
    __slots__ = ("run_id",)
    RUN_ID_FIELD_NUMBER: _ClassVar[int]
    run_id: str
    def __init__(self, run_id: _Optional[str] = ...) -> None: ...

class RunRecord(_message.Message):
    __slots__ = ("run_id", "agent_id", "state", "started_unix_ms", "ended_unix_ms", "usage", "trajectory_uri", "activity_id", "tx_id", "error")
    RUN_ID_FIELD_NUMBER: _ClassVar[int]
    AGENT_ID_FIELD_NUMBER: _ClassVar[int]
    STATE_FIELD_NUMBER: _ClassVar[int]
    STARTED_UNIX_MS_FIELD_NUMBER: _ClassVar[int]
    ENDED_UNIX_MS_FIELD_NUMBER: _ClassVar[int]
    USAGE_FIELD_NUMBER: _ClassVar[int]
    TRAJECTORY_URI_FIELD_NUMBER: _ClassVar[int]
    ACTIVITY_ID_FIELD_NUMBER: _ClassVar[int]
    TX_ID_FIELD_NUMBER: _ClassVar[int]
    ERROR_FIELD_NUMBER: _ClassVar[int]
    run_id: str
    agent_id: str
    state: RunState
    started_unix_ms: int
    ended_unix_ms: int
    usage: Usage
    trajectory_uri: str
    activity_id: str
    tx_id: str
    error: str
    def __init__(self, run_id: _Optional[str] = ..., agent_id: _Optional[str] = ..., state: _Optional[_Union[RunState, str]] = ..., started_unix_ms: _Optional[int] = ..., ended_unix_ms: _Optional[int] = ..., usage: _Optional[_Union[Usage, _Mapping]] = ..., trajectory_uri: _Optional[str] = ..., activity_id: _Optional[str] = ..., tx_id: _Optional[str] = ..., error: _Optional[str] = ...) -> None: ...
