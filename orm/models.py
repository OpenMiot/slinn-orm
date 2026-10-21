from abc import ABC, abstractmethod
from typing import Literal, Optional
from datetime import timedelta, datetime
from typing import NamedTuple, Any
from ipaddress import IPv4Address, IPv6Address, ip_address


class Model(ABC):
    @staticmethod
    @abstractmethod
    def __collection_name__() -> str: ...
    
    @property
    def __fields__(self) -> dict[str, Field]:
        return {
            field_name: field for field_name, field in self.__dict__.items()
            if not field_name.startswith('_') and isinstance(field, Field)
        }

    def _update_meta(self) -> None:
        if not hasattr(self, '_meta_primary_keys'):
            self._meta_primary_keys = ()

        for field_name, field in type(self).__dict__.items():
            self.__dict__[field_name] = field
            if field_name.startswith('_') or not isinstance(field, Field):
                continue
            if hasattr(field, 'primary') and field.primary and field_name not in self._meta_primary_keys:
                self._meta_primary_keys = (*self._meta_primary_keys, field_name)
    
    def __serialize_object__(self, obj: dict[str, Any]) -> dict[str, Any]:
        result = obj.copy()
        for field_name in result:
            field = self.__fields__.get(field_name)
            if not field:
                continue
            result[field_name] = field.__serialize__(result[field_name])
        return result
    
    def __deserialize_object__(self, obj: Any) -> dict[str, Any]:
        result = {}
        for field_name in dict(obj):
            field = self.__fields__.get(field_name)
            if not field:
                continue
            result[field_name] = field.__deserialize__(obj[field_name])
        return result
        
    def __new__(cls, **kwargs):
        if kwargs:
            return cls().__serialize_object__(kwargs)
        return object.__new__(cls)


class Field(ABC):
    class FieldReference(NamedTuple):
        collection_name: str
        field_name: str
    
    def __serialize__(self, value: Any) -> Any:
        return value
    
    def __deserialize__(self, value: Any) -> Any:
        return value

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
    
    def set_default_expr(self, default_expr: str) -> Field:
        self.default_expr = default_expr
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
        default: timedelta | datetime | None
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


class UUIDField(Field):
    def __init__(self):
        self.set_default_expr("""
            (
                unhex(
                    hex(
                        unhex(
                            substr(
                                hex(zeroblob(8) || printf('%016X', CAST(unixepoch('subsecond') * 1000 AS INTEGER))), -12
                            )
                        )
                    )
                    ||
                    '7' || substr(hex(randomblob(2)), 2, 3)
                    ||
                    substr('89AB', 1 + (abs(random()) % 4), 1) || substr(hex(randomblob(8)), 2)
                )
            )
        """)

class InetField(Field):
    def __serialize__(self, ip: IPv4Address | IPv6Address | str | int) -> bytes:
        if isinstance(ip, str):
            ip = ip_address(ip)
        return ip.packed
    
    def __deserialize__(self, ip: IPv4Address | IPv6Address | str | int | bytes) -> IPv4Address | IPv6Address:
        if isinstance(ip, (IPv4Address, IPv6Address)):
            return ip
        if isinstance(ip, (str, int, bytes)):
            return ip_address(ip)
    
