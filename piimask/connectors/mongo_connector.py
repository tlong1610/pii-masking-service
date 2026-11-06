"""Đọc MongoDB cho luồng quét và xuất: làm phẳng trường lồng, lấy mẫu trong bộ nhớ, đọc document theo lô."""

from collections.abc import Iterator
from datetime import date, datetime
from typing import Any

from pymongo import MongoClient

from piimask.schemas import ColumnProfile, DatabaseProfile, TableProfile


def _infer_data_type(value: Any) -> str:
    """Tên kiểu rút gọn của một giá trị Python hoặc BSON."""
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, int):
        return "integer"
    if isinstance(value, float):
        return "float"
    if isinstance(value, datetime | date):
        return "date"
    if isinstance(value, list):
        return "array"
    if isinstance(value, dict):
        return "object"
    return "string"


def _flatten_document(
    doc: dict[str, Any],
    parent_key: str = "",
    sep: str = ".",
    current_depth: int = 0,
    max_depth: int = 2
) -> dict[str, Any]:
    """Làm phẳng document thành đường dẫn chấm tới max_depth; dict sâu hơn giữ nguyên làm một giá trị."""
    items: list[tuple[str, Any]] = []
    for k, v in doc.items():
        new_key = f"{parent_key}{sep}{k}" if parent_key else k
        if isinstance(v, dict) and v and current_depth < max_depth:
            items.extend(
                _flatten_document(
                    v,
                    new_key,
                    sep=sep,
                    current_depth=current_depth + 1,
                    max_depth=max_depth
                ).items()
            )
        else:
            items.append((new_key, v))
    return dict(items)



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

    def extract_database_profile(
        self,
        sample_size: int = 5,
        scan_limit: int = 100,
        max_depth: int = 2,
    ) -> DatabaseProfile:
        """Quét scan_limit document đầu của mỗi collection, làm phẳng tới max_depth, lấy mẫu giá trị khác null."""
        client = self._open_client()
        try:
            db = client[self.database_name]
            all_collections = [c for c in db.list_collection_names() if not c.startswith("system.")]

            tables_profile: list[TableProfile] = []

            for coll_name in sorted(all_collections):
                cursor = db[coll_name].find({}).limit(scan_limit)
                flattened_docs = [_flatten_document(doc, max_depth=max_depth) for doc in cursor]

                field_metadata: dict[str, dict[str, Any]] = {}
                for f_doc in flattened_docs:
                    for field_path, val in f_doc.items():
                        if field_path not in field_metadata:
                            field_metadata[field_path] = {
                                "type": _infer_data_type(val) if val is not None else "string",
                                "samples": set(),
                            }
                        if val is not None:
                            val_str = str(val).strip()
                            if len(field_metadata[field_path]["samples"]) < sample_size:
                                if val_str:
                                    field_metadata[field_path]["samples"].add(val_str)
                            if field_metadata[field_path]["type"] == "string":
                                field_metadata[field_path]["type"] = _infer_data_type(val)

                column_profiles: list[ColumnProfile] = []
                for field_path, meta in field_metadata.items():
                    is_pk = field_path == "_id"
                    column_profiles.append(
                        ColumnProfile(
                            table_name=coll_name,
                            column_name=field_path,
                            data_type=meta["type"],
                            is_primary_key=is_pk,
                            is_foreign_key=False,
                            samples=list(meta["samples"])[:sample_size],
                        )
                    )

                tables_profile.append(TableProfile(table_name=coll_name, relations=[], columns=column_profiles))

            return DatabaseProfile(database_name=self.database_name, tables=tables_profile)
        finally:
            self._release_client(client)

    def to_scanner_contract(self, sample_size: int = 5, max_depth: int = 2) -> list[dict[str, Any]]:
        """Một task cho mỗi trường. Bộ quét tách từ theo dấu gạch dưới nên column_name đổi dấu chấm thành gạch dưới,
        field_path giữ đường dẫn thật.
        """
        db_profile = self.extract_database_profile(sample_size=sample_size, max_depth=max_depth)
        tasks: list[dict[str, Any]] = []
        for table in db_profile.tables:
            for col in table.columns:
                scanner_col = col.model_copy()
                scanner_col.column_name = col.column_name.replace(".", "_")
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
