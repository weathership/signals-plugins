from google.protobuf.internal import containers as _containers
from google.protobuf import descriptor as _descriptor
from google.protobuf import message as _message
from collections.abc import Iterable as _Iterable
from typing import ClassVar as _ClassVar, Optional as _Optional

DESCRIPTOR: _descriptor.FileDescriptor

class EngineStatusRequest(_message.Message):
    __slots__ = ()
    def __init__(self) -> None: ...

class EngineStatusReply(_message.Message):
    __slots__ = ("project", "version", "capabilities")
    PROJECT_FIELD_NUMBER: _ClassVar[int]
    VERSION_FIELD_NUMBER: _ClassVar[int]
    CAPABILITIES_FIELD_NUMBER: _ClassVar[int]
    project: str
    version: str
    capabilities: _containers.RepeatedScalarFieldContainer[str]
    def __init__(self, project: _Optional[str] = ..., version: _Optional[str] = ..., capabilities: _Optional[_Iterable[str]] = ...) -> None: ...

class GetAgentInstanceRequest(_message.Message):
    __slots__ = ()
    def __init__(self) -> None: ...

class GetAgentInstanceReply(_message.Message):
    __slots__ = ("healthy", "dashboard_url", "gateway_url", "detail")
    HEALTHY_FIELD_NUMBER: _ClassVar[int]
    DASHBOARD_URL_FIELD_NUMBER: _ClassVar[int]
    GATEWAY_URL_FIELD_NUMBER: _ClassVar[int]
    DETAIL_FIELD_NUMBER: _ClassVar[int]
    healthy: bool
    dashboard_url: str
    gateway_url: str
    detail: str
    def __init__(self, healthy: _Optional[bool] = ..., dashboard_url: _Optional[str] = ..., gateway_url: _Optional[str] = ..., detail: _Optional[str] = ...) -> None: ...

class WebRtcOfferRequest(_message.Message):
    __slots__ = ("sdp", "type", "agenda_id", "timezone")
    SDP_FIELD_NUMBER: _ClassVar[int]
    TYPE_FIELD_NUMBER: _ClassVar[int]
    AGENDA_ID_FIELD_NUMBER: _ClassVar[int]
    TIMEZONE_FIELD_NUMBER: _ClassVar[int]
    sdp: str
    type: str
    agenda_id: str
    timezone: str
    def __init__(self, sdp: _Optional[str] = ..., type: _Optional[str] = ..., agenda_id: _Optional[str] = ..., timezone: _Optional[str] = ...) -> None: ...

class WebRtcOfferReply(_message.Message):
    __slots__ = ("sdp", "type", "session_id", "source")
    SDP_FIELD_NUMBER: _ClassVar[int]
    TYPE_FIELD_NUMBER: _ClassVar[int]
    SESSION_ID_FIELD_NUMBER: _ClassVar[int]
    SOURCE_FIELD_NUMBER: _ClassVar[int]
    sdp: str
    type: str
    session_id: str
    source: str
    def __init__(self, sdp: _Optional[str] = ..., type: _Optional[str] = ..., session_id: _Optional[str] = ..., source: _Optional[str] = ...) -> None: ...

class WebRtcHangupRequest(_message.Message):
    __slots__ = ("session_id",)
    SESSION_ID_FIELD_NUMBER: _ClassVar[int]
    session_id: str
    def __init__(self, session_id: _Optional[str] = ...) -> None: ...

class WebRtcHangupReply(_message.Message):
    __slots__ = ("dropped",)
    DROPPED_FIELD_NUMBER: _ClassVar[int]
    dropped: bool
    def __init__(self, dropped: _Optional[bool] = ...) -> None: ...
