from __future__ import annotations
from .. import CollectionProtocol, ConnectionProtocol, PoolProtocol
from ..attributed_dict import AttributedDict
from ..typemap import typemap as tm
from ..order import OrderType
from ..models import (
    Model, Field, BoolField, IntegerField, DecimalField, FloatField, TextField, TimeField, TimeDeltaField, 
    BinaryField, UIDField, UUIDField, InetField
)
from typing import Coroutine, Optional, Final
from functools import partial
from datetime import datetime, timedelta
import asyncpg


class PostgresCollection(CollectionProtocol):
    def __init__(self, connection: PostgresConnection, name: str, model: Model | None = None):
        self.connection = connection
        self.name = name
        self.model = model

    async def find(
        self,
        _filter: dict,
        *,
        fields: tuple[str] = ('*',),
        order: tuple[tuple[OrderType, str]] = ()) -> list[dict]:
        return [self.model.__deserialize_object__(record) for record in await self.connection._fetch(
            f'SELECT {', '.join(fields)} '
            f'FROM {self.name} '
            f'{'WHERE ' if _filter else ''}{' AND '.join([f'{list(_filter.keys())[i]}=${i+1}' for i in range(0, len(_filter))])} '
            f'{'ORDER BY ' if order else ''}{', '.join([(f'{o[1]} {'ASC' if o[0] is OrderType.ASC else 'DESC'}') for o in order])};',
            *_filter.values())]

    async def find_one(
            self,
            _filter: dict,
            *,
            fields: tuple[str] = ('*',)) -> dict:
        result = await self.find(
            _filter,
            fields=fields
        )
        return result[0] if result else None

    async def insert(
        self,
        _object: dict,
        *,
        returning: tuple[str] = (),
        typemap: dict | None = None) -> None: 
        if not _object:
            return []
        if self.model:
            _object = self.model.__serialize_object__(_object)
        records = await self.connection._fetch(
            f'INSERT INTO {self.name}({', '.join(_object.keys())}) '
            f'VALUES({', '.join([f'${i+1}' for i in range(len(_object))])}) '
            f'{'RETURNING' if returning else ''} {', '.join(returning)}',
            *tm(_object, typemap).values())
        return records[0] if records else None

    async def update(
        self,
        _filter: dict,
        _object: dict,
        *,
        returning: tuple[str] = (),
        typemap: dict | None = None) -> None:
        if not _object:
            return []
        if self.model:
            _object = self.model.__serialize_object__(_object)
        return await self.connection._fetch(
            f'UPDATE {self.name} '
            f'SET {', '.join([f'{key}=${i+1}' for i, key in enumerate(_object)])} '
            f'{'WHERE ' if _filter else ''}{' AND '.join([f'{list(_filter.keys())[i]}=${i+len(_object)+1}' for i in range(0, len(_filter))])} '
            f'{'RETURNING' if returning else ''} {', '.join(returning)};',
            *tm(_object, typemap).values(), *_filter.values())

    async def delete(self, _filter: dict) -> None: 
        await self.connection._fetch(f'''
            DELETE FROM {self.name}
            {'WHERE ' if _filter else ''}{' AND '.join([f'{list(_filter.keys())[i]}=${i+1}' for i in range(0, len(_filter))])};''',
            *_filter.values())

    async def pop(
        self,
        _filter: dict,
        *,
        returning: tuple[str] = ('*', )) -> dict: 
        return await self.connection._fetch(
            f'DELETE FROM {self.name} '
            f'{'WHERE ' if _filter else ''}{' AND '.join([f'{list(_filter.keys())[i]}=${i+1}' for i in range(0, len(_filter))])} '
            f'{'RETURNING' if returning else ''} {', '.join(returning)};',
            *_filter.values())

    async def count(self, _filter: dict) -> int: 
        return (await self.connection._fetch(f'''
            SELECT COUNT(*)
            FROM {self.name}
            {'WHERE ' if _filter else ''}{' AND '.join([f'{list(_filter.keys())[i]}=${i+1}' for i in range(0, len(_filter))])};''',
            *_filter.values()))[0]['count']
    
    async def get_size(self) -> int: ...
    
    async def drop(self, *, not_exists_ok: bool = False) -> None: 
        await self.connection._fetch(f'DROP TABLE {'IF EXISTS ' if not_exists_ok else ''}{self.name};')


class PostgresConnection(ConnectionProtocol):
    FIELDS_MAP: Final[dict] = {
        BoolField: lambda field: 'BOOLEAN',
        IntegerField: lambda field: {
            2: 'SMALLINT',
            4: 'INTEGER',
            8: 'BIGINT'
        }[field.size],
        DecimalField: lambda field: 'DECIMAL',
        FloatField: lambda field: 'DOUBLE PRECISION' if field.double else 'REAL',
        TextField: lambda field: 'TEXT',
        TimeField: lambda field: {
            (False, False, True): 'TIME',
            (False, True, False): 'DATE',
            (False, True, True): 'TIMESTAMP',
            (True, False, True): 'TIMETZ',
            (True, True, False): 'DATE',
            (True, True, True): 'TIMESTAMPTZ'
        }[field.zone, field.date, field.time] + (
            '' if field.default is None else (' DEFAULT ' + {
                datetime: lambda dt: f'to_timestamp({dt.timestamp()})',
                timedelta: lambda td: f'NOW() + INTERVAL \'{td.total_seconds()} seconds\''
            }[type(field.default)](field.default))
        ),
        TimeDeltaField: lambda field: 'INTERVAL',
        BinaryField: lambda field: 'BYTEA',
        UIDField: lambda field: 'BIGINT',
        UUIDField: lambda field: 'UUID',
        InetField: lambda field: 'INET'
    }

    def __init__(self, pool, connection, transaction, autocommit: bool = True):
        self._pool = pool
        self._connection = connection
        self._transaction = transaction
        self._autocommit = autocommit
        self._models = set()
        self.collection = self.__getattr__
    
    def __getattr__(self, key) -> CollectionProtocol:
        return PostgresCollection(
            self, key, model = next(iter(model for model in self._models if model.__collection_name__() == key))
        )
    
    async def rollback(self) -> None:
        await self._transaction.rollback()
    
    async def commit(self) -> None:
        await self._transaction.commit()
    
    async def collections(self) -> list:
        return [collection[0] for collection in await self._fetch('''
            SELECT table_name
            FROM information_schema.tables
            WHERE table_schema NOT IN ('pg_catalog', 'information_schema') AND table_type = 'BASE TABLE'
            ORDER BY table_name;''')]

    async def create(self, model: Model, *, exists_ok=False) -> None:
        model._update_meta()
        fields = []
        for field_name in model.__dict__:
            field = getattr(model, field_name)
            if field_name.startswith('_') or not isinstance(field, Field):
                continue
            fields.append(
                f'''
                    {field_name} {self.FIELDS_MAP[type(field)](field)}
                    {'UNIQUE' if hasattr(field, 'unique') and field.unique else ''}
                    {'NOT NULL' if hasattr(field, 'not_null') and field.not_null else ''}
                    {'GENERATED ALWAYS AS IDENTITY' if hasattr(field, 'identity') and field.identity else ''}
                    {f'REFERENCES {field.reference.collection_name}({field.reference.field_name})' 
                    if hasattr(field, 'reference') and field.reference else ''}
                    {f'DEFAULT {field.default_expr}' if hasattr(field, 'default_expr') else ''}
                '''.strip()
            )
        await self._fetch(f'''
            CREATE TABLE {'IF NOT EXISTS ' if exists_ok else ''}{model.__collection_name__()}(
                {','.join(fields)},
                {f'PRIMARY KEY ({','.join(model._meta_primary_keys)})' if model._meta_primary_keys else ''}
            );
        '''.strip())
        self._models.add(model)
    
    async def create_index(
        self,
        index_name: str,
        collection_name: str,
        fields: tuple[str],
        *,
        exists_ok: bool=False,
        unique: bool=False
    ) -> None:
        await self._fetch(f'''
            CREATE {'UNIQUE ' if unique else ''}INDEX {'IF NOT EXISTS ' if exists_ok else ''}{index_name} ON {collection_name}({','.join(fields)});
        ''')
    
    async def __aenter__(self):
        await self._transaction.start()
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:
        try:
            if not exc_type and self._autocommit:
                await self.commit()
            else:
                await self.rollback()
        finally:
            await self._pool.release(self)
    
    async def _fetch(self, query, *args, timeout: float | None = None, record_class=None) -> list:
        query = ' '.join([line.strip() for line in query.split('\n')]).strip()
        return await self._connection.fetch(
            query,
            *args,
            timeout=timeout,
            record_class=record_class
        )

class PostgresPool(PoolProtocol):
    def __init__(self, pool_factory, autocommit=True):
        self._pool_factory = pool_factory
        self._autocommit = autocommit
        self._pool = None
        self._tasks = []    
    
    async def acquire(self) -> PostgresConnection:
        if not self._pool:
            self._pool = await self._pool_factory()
        connection = await self._pool.acquire()
        transaction = connection.transaction()
        pg_conn = PostgresConnection(self, connection, transaction)
        tasks, self._tasks = self._tasks, []
        for task in tasks:
            await task(pg_conn)
        return pg_conn
    
    async def release(self, connection: PostgresConnection):
        await self._pool.release(connection._connection)
        del connection
    
    def on_acquire(self, coroutine: Coroutine[ConnectionProtocol]) -> None:
        self._tasks.append(coroutine)
    
    async def close(self):
        self._pool.close()


def Postgres(
        dsn: Optional[str] = None,
        *,
        host: Optional[str] = None,
        port: Optional[int] = None,
        user: Optional[str] = None,
        password: Optional[str] = None,
        database: Optional[str] = None,
        server_settings: Optional[dict] = None,
        autocommit: bool = True) -> PostgresPool:
    return PostgresPool(
        partial(
            asyncpg.create_pool,
            dsn,
            server_settings=server_settings
        ) if dsn else partial(
            asyncpg.create_pool,
            host=host,
            port=port,
            user=user,
            password=password,
            database=database,
            server_settings=server_settings
        ),
        autocommit=autocommit
    )
