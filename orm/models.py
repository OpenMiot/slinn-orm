from __future__ import annotations
from abc import ABC, abstractmethod
from typing import Literal, Optional
from datetime import timedelta, datetime
from typing import NamedTuple


class Model(ABC):
    @staticmethod
    @abstractmethod
    def __collection_name__() -> str: ...

    def _update_meta(self) -> None:
        if not hasattr(self, '_meta_primary_keys'):
            self._meta_primary_keys = ()

        for field_name in self.__dict__.keys():
            field = self.__dict__[field_name]
            if field_name.startswith('_') or not isinstance(field, Field):
                continue
            if hasattr(field, 'primary') and field.primary:
                if field_name not in self._meta_primary_keys:
                    self._meta_primary_keys = (*self._meta_primary_keys, field_name)


class Field(ABC):
    class FieldReference(NamedTuple):
        collection_name: str
        field_name: str

    def make_identity(self) -> Field:
        self.identity = True
        return self

    def make_primary(self) -> Field:
        self.primary = True
        return self
    
    def make_unique(self) -> Field:
        self.unique = True
        return self
    
    def make_not_null(self) -> Field:
        self.not_null = True
        return self
    
    def set_reference(self, collection_name: str, field_name: str) -> Field:
        self.reference = self.FieldReference(collection_name, field_name)
        return self


class BoolField(Field): ...


class IntegerField(Field):
    def __init__(self, *, size: Literal[2, 4, 8] = 4):
        self.size = size


class DecimalField(Field): ...


class FloatField(Field):
    def __init__(self, *, double: bool = False):
        self.double = double


class TextField(Field): ...


class TimeField(Field):
    def __init__(
        self,
        *,
        zone: bool = True,
        date: bool = True,
        time: bool = True,
        default: Optional[timedelta | datetime]
    ):
        self.zone = zone
        self.date = date
        self.time = time
        self.default = default


class TimeDeltaField(Field): ...


class BinaryField(Field): ...


class UIDField(Field):
    def __init__(self):
        self.make_identity()


class UUIDField(Field): ...
