from google.protobuf.internal import containers as _containers
from google.protobuf.internal import enum_type_wrapper as _enum_type_wrapper
from google.protobuf import descriptor as _descriptor
from google.protobuf import message as _message
from collections.abc import Iterable as _Iterable, Mapping as _Mapping
from typing import ClassVar as _ClassVar, Optional as _Optional, Union as _Union

DESCRIPTOR: _descriptor.FileDescriptor

class Billing(int, metaclass=_enum_type_wrapper.EnumTypeWrapper):
    __slots__ = ()
    BILLING_UNSPECIFIED: _ClassVar[Billing]
    BILLING_LOCAL: _ClassVar[Billing]
    BILLING_SUBSCRIPTION: _ClassVar[Billing]
    BILLING_TOKEN_METERED: _ClassVar[Billing]

class CallState(int, metaclass=_enum_type_wrapper.EnumTypeWrapper):
    __slots__ = ()
    CALL_STATE_UNSPECIFIED: _ClassVar[CallState]
    CALL_RUNNING: _ClassVar[CallState]
    CALL_COMPLETED: _ClassVar[CallState]
    CALL_FAILED: _ClassVar[CallState]
    CALL_CANCELLED: _ClassVar[CallState]
    CALL_NEEDS_INPUT: _ClassVar[CallState]
    CALL_BUDGET_EXHAUSTED: _ClassVar[CallState]
BILLING_UNSPECIFIED: Billing
BILLING_LOCAL: Billing
BILLING_SUBSCRIPTION: Billing
BILLING_TOKEN_METERED: Billing
CALL_STATE_UNSPECIFIED: CallState
CALL_RUNNING: CallState
CALL_COMPLETED: CallState
CALL_FAILED: CallState
CALL_CANCELLED: CallState
CALL_NEEDS_INPUT: CallState
CALL_BUDGET_EXHAUSTED: CallState

class PlatformOffer(_message.Message):
    __slots__ = ("platform_id", "project", "vendor", "account", "billing", "products", "note")
    PLATFORM_ID_FIELD_NUMBER: _ClassVar[int]
    PROJECT_FIELD_NUMBER: _ClassVar[int]
    VENDOR_FIELD_NUMBER: _ClassVar[int]
    ACCOUNT_FIELD_NUMBER: _ClassVar[int]
    BILLING_FIELD_NUMBER: _ClassVar[int]
    PRODUCTS_FIELD_NUMBER: _ClassVar[int]
    NOTE_FIELD_NUMBER: _ClassVar[int]
    platform_id: str
    project: str
    vendor: str
    account: str
    billing: Billing
    products: _containers.RepeatedScalarFieldContainer[str]
    note: str
    def __init__(self, platform_id: _Optional[str] = ..., project: _Optional[str] = ..., vendor: _Optional[str] = ..., account: _Optional[str] = ..., billing: _Optional[_Union[Billing, str]] = ..., products: _Optional[_Iterable[str]] = ..., note: _Optional[str] = ...) -> None: ...

class ListPlatformsRequest(_message.Message):
    __slots__ = ()
    def __init__(self) -> None: ...

class ListPlatformsResponse(_message.Message):
    __slots__ = ("project", "platforms")
    PROJECT_FIELD_NUMBER: _ClassVar[int]
    PLATFORMS_FIELD_NUMBER: _ClassVar[int]
    project: str
    platforms: _containers.RepeatedCompositeFieldContainer[PlatformOffer]
    def __init__(self, project: _Optional[str] = ..., platforms: _Optional[_Iterable[_Union[PlatformOffer, _Mapping]]] = ...) -> None: ...

class PlatformHint(_message.Message):
    __slots__ = ("platform_id", "project", "vendor", "account", "billing", "products")
    PLATFORM_ID_FIELD_NUMBER: _ClassVar[int]
    PROJECT_FIELD_NUMBER: _ClassVar[int]
    VENDOR_FIELD_NUMBER: _ClassVar[int]
    ACCOUNT_FIELD_NUMBER: _ClassVar[int]
    BILLING_FIELD_NUMBER: _ClassVar[int]
    PRODUCTS_FIELD_NUMBER: _ClassVar[int]
    platform_id: str
    project: str
    vendor: str
    account: str
    billing: str
    products: _containers.RepeatedScalarFieldContainer[str]
    def __init__(self, platform_id: _Optional[str] = ..., project: _Optional[str] = ..., vendor: _Optional[str] = ..., account: _Optional[str] = ..., billing: _Optional[str] = ..., products: _Optional[_Iterable[str]] = ...) -> None: ...

class ForeignObject(_message.Message):
    __slots__ = ("product", "foreign_id", "name", "description", "tool_types", "handoff_ids")
    PRODUCT_FIELD_NUMBER: _ClassVar[int]
    FOREIGN_ID_FIELD_NUMBER: _ClassVar[int]
    NAME_FIELD_NUMBER: _ClassVar[int]
    DESCRIPTION_FIELD_NUMBER: _ClassVar[int]
    TOOL_TYPES_FIELD_NUMBER: _ClassVar[int]
    HANDOFF_IDS_FIELD_NUMBER: _ClassVar[int]
    product: str
    foreign_id: str
    name: str
    description: str
    tool_types: _containers.RepeatedScalarFieldContainer[str]
    handoff_ids: _containers.RepeatedScalarFieldContainer[str]
    def __init__(self, product: _Optional[str] = ..., foreign_id: _Optional[str] = ..., name: _Optional[str] = ..., description: _Optional[str] = ..., tool_types: _Optional[_Iterable[str]] = ..., handoff_ids: _Optional[_Iterable[str]] = ...) -> None: ...

class DescribeRequest(_message.Message):
    __slots__ = ("platform_id", "vendor")
    PLATFORM_ID_FIELD_NUMBER: _ClassVar[int]
    VENDOR_FIELD_NUMBER: _ClassVar[int]
    platform_id: str
    vendor: str
    def __init__(self, platform_id: _Optional[str] = ..., vendor: _Optional[str] = ...) -> None: ...

class DescribeResponse(_message.Message):
    __slots__ = ("platform", "verbs", "objects")
    PLATFORM_FIELD_NUMBER: _ClassVar[int]
    VERBS_FIELD_NUMBER: _ClassVar[int]
    OBJECTS_FIELD_NUMBER: _ClassVar[int]
    platform: PlatformOffer
    verbs: _containers.RepeatedScalarFieldContainer[str]
    objects: _containers.RepeatedCompositeFieldContainer[ForeignObject]
    def __init__(self, platform: _Optional[_Union[PlatformOffer, _Mapping]] = ..., verbs: _Optional[_Iterable[str]] = ..., objects: _Optional[_Iterable[_Union[ForeignObject, _Mapping]]] = ...) -> None: ...

class RunBudget(_message.Message):
    __slots__ = ("max_seconds",)
    MAX_SECONDS_FIELD_NUMBER: _ClassVar[int]
    max_seconds: int
    def __init__(self, max_seconds: _Optional[int] = ...) -> None: ...

class PlatformCall(_message.Message):
    __slots__ = ("platform_id", "vendor", "product", "verb", "foreign_id", "input_json", "workspace_uri", "budget", "call_id", "tx_id", "reason")
    PLATFORM_ID_FIELD_NUMBER: _ClassVar[int]
    VENDOR_FIELD_NUMBER: _ClassVar[int]
    PRODUCT_FIELD_NUMBER: _ClassVar[int]
    VERB_FIELD_NUMBER: _ClassVar[int]
    FOREIGN_ID_FIELD_NUMBER: _ClassVar[int]
    INPUT_JSON_FIELD_NUMBER: _ClassVar[int]
    WORKSPACE_URI_FIELD_NUMBER: _ClassVar[int]
    BUDGET_FIELD_NUMBER: _ClassVar[int]
    CALL_ID_FIELD_NUMBER: _ClassVar[int]
    TX_ID_FIELD_NUMBER: _ClassVar[int]
    REASON_FIELD_NUMBER: _ClassVar[int]
    platform_id: str
    vendor: str
    product: str
    verb: str
    foreign_id: str
    input_json: str
    workspace_uri: str
    budget: RunBudget
    call_id: str
    tx_id: str
    reason: str
    def __init__(self, platform_id: _Optional[str] = ..., vendor: _Optional[str] = ..., product: _Optional[str] = ..., verb: _Optional[str] = ..., foreign_id: _Optional[str] = ..., input_json: _Optional[str] = ..., workspace_uri: _Optional[str] = ..., budget: _Optional[_Union[RunBudget, _Mapping]] = ..., call_id: _Optional[str] = ..., tx_id: _Optional[str] = ..., reason: _Optional[str] = ...) -> None: ...

class PlatformEvent(_message.Message):
    __slots__ = ("call_id", "seq", "at_unix_ms", "accepted", "progress", "entry", "handoff", "needs_input", "deliverable", "done")
    CALL_ID_FIELD_NUMBER: _ClassVar[int]
    SEQ_FIELD_NUMBER: _ClassVar[int]
    AT_UNIX_MS_FIELD_NUMBER: _ClassVar[int]
    ACCEPTED_FIELD_NUMBER: _ClassVar[int]
    PROGRESS_FIELD_NUMBER: _ClassVar[int]
    ENTRY_FIELD_NUMBER: _ClassVar[int]
    HANDOFF_FIELD_NUMBER: _ClassVar[int]
    NEEDS_INPUT_FIELD_NUMBER: _ClassVar[int]
    DELIVERABLE_FIELD_NUMBER: _ClassVar[int]
    DONE_FIELD_NUMBER: _ClassVar[int]
    call_id: str
    seq: int
    at_unix_ms: int
    accepted: CallAccepted
    progress: Progress
    entry: Entry
    handoff: Handoff
    needs_input: NeedsInput
    deliverable: Deliverable
    done: CallDone
    def __init__(self, call_id: _Optional[str] = ..., seq: _Optional[int] = ..., at_unix_ms: _Optional[int] = ..., accepted: _Optional[_Union[CallAccepted, _Mapping]] = ..., progress: _Optional[_Union[Progress, _Mapping]] = ..., entry: _Optional[_Union[Entry, _Mapping]] = ..., handoff: _Optional[_Union[Handoff, _Mapping]] = ..., needs_input: _Optional[_Union[NeedsInput, _Mapping]] = ..., deliverable: _Optional[_Union[Deliverable, _Mapping]] = ..., done: _Optional[_Union[CallDone, _Mapping]] = ...) -> None: ...

class CallAccepted(_message.Message):
    __slots__ = ("call_id", "platform_id", "product", "verb", "foreign_id", "activity_id", "billing")
    CALL_ID_FIELD_NUMBER: _ClassVar[int]
    PLATFORM_ID_FIELD_NUMBER: _ClassVar[int]
    PRODUCT_FIELD_NUMBER: _ClassVar[int]
    VERB_FIELD_NUMBER: _ClassVar[int]
    FOREIGN_ID_FIELD_NUMBER: _ClassVar[int]
    ACTIVITY_ID_FIELD_NUMBER: _ClassVar[int]
    BILLING_FIELD_NUMBER: _ClassVar[int]
    call_id: str
    platform_id: str
    product: str
    verb: str
    foreign_id: str
    activity_id: str
    billing: str
    def __init__(self, call_id: _Optional[str] = ..., platform_id: _Optional[str] = ..., product: _Optional[str] = ..., verb: _Optional[str] = ..., foreign_id: _Optional[str] = ..., activity_id: _Optional[str] = ..., billing: _Optional[str] = ...) -> None: ...

class Progress(_message.Message):
    __slots__ = ("detail",)
    DETAIL_FIELD_NUMBER: _ClassVar[int]
    detail: str
    def __init__(self, detail: _Optional[str] = ...) -> None: ...

class Entry(_message.Message):
    __slots__ = ("vendor", "foreign_id", "role", "name", "text", "agent_foreign_id", "fulfilled_by")
    VENDOR_FIELD_NUMBER: _ClassVar[int]
    FOREIGN_ID_FIELD_NUMBER: _ClassVar[int]
    ROLE_FIELD_NUMBER: _ClassVar[int]
    NAME_FIELD_NUMBER: _ClassVar[int]
    TEXT_FIELD_NUMBER: _ClassVar[int]
    AGENT_FOREIGN_ID_FIELD_NUMBER: _ClassVar[int]
    FULFILLED_BY_FIELD_NUMBER: _ClassVar[int]
    vendor: str
    foreign_id: str
    role: str
    name: str
    text: str
    agent_foreign_id: str
    fulfilled_by: str
    def __init__(self, vendor: _Optional[str] = ..., foreign_id: _Optional[str] = ..., role: _Optional[str] = ..., name: _Optional[str] = ..., text: _Optional[str] = ..., agent_foreign_id: _Optional[str] = ..., fulfilled_by: _Optional[str] = ...) -> None: ...

class Handoff(_message.Message):
    __slots__ = ("vendor", "foreign_id", "agent_foreign_id", "agent_name")
    VENDOR_FIELD_NUMBER: _ClassVar[int]
    FOREIGN_ID_FIELD_NUMBER: _ClassVar[int]
    AGENT_FOREIGN_ID_FIELD_NUMBER: _ClassVar[int]
    AGENT_NAME_FIELD_NUMBER: _ClassVar[int]
    vendor: str
    foreign_id: str
    agent_foreign_id: str
    agent_name: str
    def __init__(self, vendor: _Optional[str] = ..., foreign_id: _Optional[str] = ..., agent_foreign_id: _Optional[str] = ..., agent_name: _Optional[str] = ...) -> None: ...

class NeedsInput(_message.Message):
    __slots__ = ("foreign_id", "function_name", "arguments_json")
    FOREIGN_ID_FIELD_NUMBER: _ClassVar[int]
    FUNCTION_NAME_FIELD_NUMBER: _ClassVar[int]
    ARGUMENTS_JSON_FIELD_NUMBER: _ClassVar[int]
    foreign_id: str
    function_name: str
    arguments_json: str
    def __init__(self, foreign_id: _Optional[str] = ..., function_name: _Optional[str] = ..., arguments_json: _Optional[str] = ...) -> None: ...

class Deliverable(_message.Message):
    __slots__ = ("json", "trajectory_uri", "trajectory_format")
    JSON_FIELD_NUMBER: _ClassVar[int]
    TRAJECTORY_URI_FIELD_NUMBER: _ClassVar[int]
    TRAJECTORY_FORMAT_FIELD_NUMBER: _ClassVar[int]
    json: str
    trajectory_uri: str
    trajectory_format: str
    def __init__(self, json: _Optional[str] = ..., trajectory_uri: _Optional[str] = ..., trajectory_format: _Optional[str] = ...) -> None: ...

class CallDone(_message.Message):
    __slots__ = ("state", "stop_reason", "error", "foreign_id")
    STATE_FIELD_NUMBER: _ClassVar[int]
    STOP_REASON_FIELD_NUMBER: _ClassVar[int]
    ERROR_FIELD_NUMBER: _ClassVar[int]
    FOREIGN_ID_FIELD_NUMBER: _ClassVar[int]
    state: CallState
    stop_reason: str
    error: str
    foreign_id: str
    def __init__(self, state: _Optional[_Union[CallState, str]] = ..., stop_reason: _Optional[str] = ..., error: _Optional[str] = ..., foreign_id: _Optional[str] = ...) -> None: ...

class CancelRequest(_message.Message):
    __slots__ = ("call_id",)
    CALL_ID_FIELD_NUMBER: _ClassVar[int]
    call_id: str
    def __init__(self, call_id: _Optional[str] = ...) -> None: ...

class CancelResponse(_message.Message):
    __slots__ = ("accepted", "state", "error")
    ACCEPTED_FIELD_NUMBER: _ClassVar[int]
    STATE_FIELD_NUMBER: _ClassVar[int]
    ERROR_FIELD_NUMBER: _ClassVar[int]
    accepted: bool
    state: CallState
    error: str
    def __init__(self, accepted: _Optional[bool] = ..., state: _Optional[_Union[CallState, str]] = ..., error: _Optional[str] = ...) -> None: ...

class GetCallRequest(_message.Message):
    __slots__ = ("call_id",)
    CALL_ID_FIELD_NUMBER: _ClassVar[int]
    call_id: str
    def __init__(self, call_id: _Optional[str] = ...) -> None: ...

class CallRecord(_message.Message):
    __slots__ = ("call_id", "platform_id", "product", "verb", "state", "started_unix_ms", "ended_unix_ms", "foreign_id", "error", "trajectory_uri")
    CALL_ID_FIELD_NUMBER: _ClassVar[int]
    PLATFORM_ID_FIELD_NUMBER: _ClassVar[int]
    PRODUCT_FIELD_NUMBER: _ClassVar[int]
    VERB_FIELD_NUMBER: _ClassVar[int]
    STATE_FIELD_NUMBER: _ClassVar[int]
    STARTED_UNIX_MS_FIELD_NUMBER: _ClassVar[int]
    ENDED_UNIX_MS_FIELD_NUMBER: _ClassVar[int]
    FOREIGN_ID_FIELD_NUMBER: _ClassVar[int]
    ERROR_FIELD_NUMBER: _ClassVar[int]
    TRAJECTORY_URI_FIELD_NUMBER: _ClassVar[int]
    call_id: str
    platform_id: str
    product: str
    verb: str
    state: CallState
    started_unix_ms: int
    ended_unix_ms: int
    foreign_id: str
    error: str
    trajectory_uri: str
    def __init__(self, call_id: _Optional[str] = ..., platform_id: _Optional[str] = ..., product: _Optional[str] = ..., verb: _Optional[str] = ..., state: _Optional[_Union[CallState, str]] = ..., started_unix_ms: _Optional[int] = ..., ended_unix_ms: _Optional[int] = ..., foreign_id: _Optional[str] = ..., error: _Optional[str] = ..., trajectory_uri: _Optional[str] = ...) -> None: ...
