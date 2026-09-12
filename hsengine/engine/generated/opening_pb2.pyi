from google.protobuf.internal import containers as _containers
from google.protobuf import descriptor as _descriptor
from google.protobuf import message as _message
from collections.abc import Iterable as _Iterable, Mapping as _Mapping
from typing import ClassVar as _ClassVar, Optional as _Optional, Union as _Union

DESCRIPTOR: _descriptor.FileDescriptor

class Gesture(_message.Message):
    __slots__ = ("id", "when", "weight", "instruction", "lane")
    ID_FIELD_NUMBER: _ClassVar[int]
    WHEN_FIELD_NUMBER: _ClassVar[int]
    WEIGHT_FIELD_NUMBER: _ClassVar[int]
    INSTRUCTION_FIELD_NUMBER: _ClassVar[int]
    LANE_FIELD_NUMBER: _ClassVar[int]
    id: str
    when: _containers.RepeatedScalarFieldContainer[str]
    weight: float
    instruction: str
    lane: _containers.RepeatedScalarFieldContainer[str]
    def __init__(self, id: _Optional[str] = ..., when: _Optional[_Iterable[str]] = ..., weight: _Optional[float] = ..., instruction: _Optional[str] = ..., lane: _Optional[_Iterable[str]] = ...) -> None: ...

class PauseAfter(_message.Message):
    __slots__ = ("after", "p")
    AFTER_FIELD_NUMBER: _ClassVar[int]
    P_FIELD_NUMBER: _ClassVar[int]
    after: int
    p: float
    def __init__(self, after: _Optional[int] = ..., p: _Optional[float] = ...) -> None: ...

class SequencePolicy(_message.Message):
    __slots__ = ("min_gestures", "max_gestures", "pause_after")
    MIN_GESTURES_FIELD_NUMBER: _ClassVar[int]
    MAX_GESTURES_FIELD_NUMBER: _ClassVar[int]
    PAUSE_AFTER_FIELD_NUMBER: _ClassVar[int]
    min_gestures: int
    max_gestures: int
    pause_after: _containers.RepeatedCompositeFieldContainer[PauseAfter]
    def __init__(self, min_gestures: _Optional[int] = ..., max_gestures: _Optional[int] = ..., pause_after: _Optional[_Iterable[_Union[PauseAfter, _Mapping]]] = ...) -> None: ...

class Catalog(_message.Message):
    __slots__ = ("gesture", "sequence")
    GESTURE_FIELD_NUMBER: _ClassVar[int]
    SEQUENCE_FIELD_NUMBER: _ClassVar[int]
    gesture: _containers.RepeatedCompositeFieldContainer[Gesture]
    sequence: SequencePolicy
    def __init__(self, gesture: _Optional[_Iterable[_Union[Gesture, _Mapping]]] = ..., sequence: _Optional[_Union[SequencePolicy, _Mapping]] = ...) -> None: ...
