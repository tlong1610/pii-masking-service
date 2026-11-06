"""Đọc MongoDB cho luồng quét và xuất: lập profile toàn collection, đọc document theo lô."""

from collections.abc import Iterable, Iterator
from typing import Any

from pymongo import MongoClient

from piimask.profile import SAMPLE_SIZE, FieldProfiler
from piimask.schemas import DatabaseProfile, TableProfile


class MongoConnector:
    def __init__(self, connection_string: str, database_name: str, client: Any | None = None):
        self.connection_string = connection_string
        self.database_name = database_name
        # Client do bên gọi giữ (dùng chung hoặc mongomock); connector không đóng client này.
        self._client = client

    def _open_client(self) -> Any:
        if self._client is not None:
            return self._client
        client = MongoClient(self.connection_string, serverSelectionTimeoutMS=5000)
        client.admin.command("ping")
        return client

    def _release_client(self, client: Any) -> None:
        if client is not self._client:
            client.close()

    def collection_names(self) -> list[str]:
        client = self._open_client()
        try:
            names = client[self.database_name].list_collection_names()
            return sorted(name for name in names if not name.startswith("system."))
        finally:
            self._release_client(client)

    def extract_database_profile(
        self,
        sample_size: int = SAMPLE_SIZE,
        collections: Iterable[str] | None = None,
        batch_size: int = 1000,
    ) -> DatabaseProfile:
        """Đọc hết từng collection theo lô: đủ mọi trường, kể cả trường hiếm, trong mảng và lồng sâu."""
        names = self.collection_names() if collections is None else sorted(collections)
        tables = []
        for name in names:
            profiler = FieldProfiler(name, sample_size)
            for document in self.iter_documents(name, batch_size):
                profiler.add(document)
            tables.append(TableProfile(table_name=name, relations=[], columns=profiler.profiles()))
        return DatabaseProfile(database_name=self.database_name, tables=tables)

    def to_scanner_contract(
        self, sample_size: int = SAMPLE_SIZE, collections: Iterable[str] | None = None, batch_size: int = 1000
    ) -> list[dict[str, Any]]:
        """Một task cho mỗi trường. Bộ quét tách từ theo dấu gạch dưới nên column_name đổi dấu chấm thành gạch dưới,
        field_path giữ đường dẫn thật.
        """
        db_profile = self.extract_database_profile(sample_size, collections, batch_size)
        tasks: list[dict[str, Any]] = []
        for table in db_profile.tables:
            for col in table.columns:
                scanner_col = col.model_copy()
                scanner_col.column_name = col.column_name.replace("[].", "_").replace(".", "_")
                tasks.append(
                    {"collection_name": table.table_name, "field_path": col.column_name, "column_profile": scanner_col}
                )
        return tasks

    def iter_documents(self, collection_name: str, batch_size: int = 1000) -> Iterator[dict[str, Any]]:
        """Đọc từng document theo lô của server, không nạp cả collection vào bộ nhớ."""
        client = self._open_client()
        try:
            yield from client[self.database_name][collection_name].find({}).batch_size(batch_size)
        finally:
            self._release_client(client)
