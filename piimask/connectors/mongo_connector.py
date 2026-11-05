"""
MongoDB Connector for PII Detection Pipeline.
Extracts schema metadata, flattens nested document fields, extracts safe samples,
and constructs DatabaseProfile for AI scanning and verification.
"""

import logging
import os
from collections.abc import Iterator
from datetime import date, datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

try:
    from pymongo import MongoClient
    from pymongo.errors import PyMongoError
except ImportError:
    MongoClient = None
    PyMongoError = Exception

from piimask.detection.column_stats import ratios_from_counts
from piimask.schemas import ColumnProfile, DatabaseProfile, TableProfile, TableRelation

logger = logging.getLogger(__name__)


def _infer_data_type(value: Any) -> str:
    """Infers simplified data type name from a Python/BSON value."""
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
    """
    Recursively flattens a nested MongoDB document into dot-notation paths up to max_depth.

    Level breakdown:
    - Root / scalar (cấp 0): e.g., '_id', 'customer_id'
    - 1-level nesting (cấp 1): e.g., 'identity.cccd', 'contact.email'
    - 2-level nesting (cấp 2): e.g., 'identity.kyc.doc_number'

    If current_depth reaches max_depth, nested dicts are kept as objects and not expanded further.
    """
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
    """
    Connector to inspect MongoDB schemas, collections, nested fields,
    and extract non-null sample values for the PII detection pipeline.
    """

    def __init__(
        self,
        connection_string: str | None = None,
        database_name: str | None = None,
        client: Any | None = None,
    ):
        self.connection_string = connection_string or os.getenv(
            "MONGO_URI", "mongodb://admin:admin@localhost:27017/?authSource=admin"
        )
        self.database_name = database_name or self._extract_database_name()
        # Caller-owned client (shared or mongomock); never closed by the connector.
        self._client = client

    def _open_client(self) -> Any:
        if self._client is not None:
            return self._client
        if MongoClient is None:
            raise RuntimeError("Thư viện pymongo chưa được cài đặt. Không thể kết nối MongoDB.")
        client = MongoClient(self.connection_string, serverSelectionTimeoutMS=5000)
        client.admin.command("ping")
        return client

    def _release_client(self, client: Any) -> None:
        if client is not self._client:
            client.close()

    def _extract_database_name(self) -> str:
        """Extracts database name from connection string path or fallback to env/default."""
        env_db = os.getenv("MONGO_DB")
        if env_db:
            return env_db
        try:
            parsed = urlparse(self.connection_string)
            path = parsed.path.strip("/")
            if path:
                return path.split("?")[0]
        except Exception:
            pass
        return "mydatabase"

    def _infer_collection_relations(self, collection_name: str, available_collections: list[str]) -> list[TableRelation]:
        """
        Infers foreign key relationships across collections based on schema conventions:
        - In 'orders': 'customer_id' -> 'customers._id'
        - In 'orders': 'pii_ext.customer_cccd' -> 'customers.identity.cccd'
        """
        relations: list[TableRelation] = []

        if collection_name == "orders":
            if "customers" in available_collections:
                relations.append(
                    TableRelation(
                        from_column="customer_id",
                        to_table="customers",
                        to_column="_id",
                    )
                )
                relations.append(
                    TableRelation(
                        from_column="pii_ext.customer_cccd",
                        to_table="customers",
                        to_column="identity.cccd",
                    )
                )

        return relations

    def list_relations(self) -> list[tuple[str, str, str, str]]:
        """(from_collection, from_field, to_collection, to_field) for every inferred join."""
        client = self._open_client()
        try:
            db = client[self.database_name]
            names = [c for c in db.list_collection_names() if not c.startswith("system.")]
            return [
                (coll, rel.from_column, rel.to_table, rel.to_column)
                for coll in sorted(names)
                for rel in self._infer_collection_relations(coll, names)
            ]
        finally:
            self._release_client(client)

    def extract_database_profile(
        self,
        sample_size: int = 5,
        scan_limit: int = 100,
        max_depth: int = 2,
    ) -> DatabaseProfile:
        """
        Scans all MongoDB collections in the target database, flattens nested fields,
        samples distinct non-null values, and returns a unified DatabaseProfile.

        Args:
            sample_size: Number of sample values to collect per field
            scan_limit: Number of documents to sample when discovering collection schema
            max_depth: Maximum nesting level to flatten (defaults to 2 as per PRD)

        Returns:
            DatabaseProfile: Standardized database schema representation for AI scanning.
        """
        client = self._open_client()
        try:
            db = client[self.database_name]
            all_collections = [c for c in db.list_collection_names() if not c.startswith("system.")]

            tables_profile: list[TableProfile] = []

            for coll_name in sorted(all_collections):
                coll = db[coll_name]
                relations = self._infer_collection_relations(coll_name, all_collections)
                fk_columns = {r.from_column for r in relations}

                # Sample documents to discover all flattened fields
                cursor = coll.find({}).limit(scan_limit)
                flattened_docs = [_flatten_document(doc, max_depth=max_depth) for doc in cursor]

                # Map field_name -> {type, set of sample values}
                field_metadata: dict[str, dict[str, Any]] = {}
                for f_doc in flattened_docs:
                    for field_path, val in f_doc.items():
                        if field_path not in field_metadata:
                            field_metadata[field_path] = {
                                "type": _infer_data_type(val) if val is not None else "string",
                                "samples": set(),
                                "lengths": [],
                                # hash() of each value only: enough to count distinct values, keeps no value
                                "value_hashes": set(),
                            }
                        if val is not None:
                            val_str = str(val).strip()
                            field_metadata[field_path]["lengths"].append(len(val_str))
                            field_metadata[field_path]["value_hashes"].add(hash(val_str))
                            if len(field_metadata[field_path]["samples"]) < sample_size:
                                if val_str:
                                    field_metadata[field_path]["samples"].add(val_str)
                            if field_metadata[field_path]["type"] == "string":
                                field_metadata[field_path]["type"] = _infer_data_type(val)

                # Build ColumnProfiles
                column_profiles: list[ColumnProfile] = []
                for field_path, meta in field_metadata.items():
                    is_pk = (field_path == "_id")
                    is_fk = (field_path in fk_columns)
                    system_rec = "HASHING" if (is_pk or is_fk) else None

                    lengths = meta.get("lengths", [])
                    length_mean = None
                    length_variance = None
                    if lengths:
                        n = len(lengths)
                        length_mean = sum(lengths) / n
                        if n > 1:
                            length_variance = sum((x - length_mean) ** 2 for x in lengths) / (n - 1)
                        else:
                            length_variance = 0.0

                    # Missing fields count as empty: every scanned document either has a value or not.
                    profiled_values, distinct_ratio, null_ratio = ratios_from_counts(
                        len(flattened_docs), len(lengths), len(meta["value_hashes"])
                    )

                    col_prof = ColumnProfile(
                        table_name=coll_name,
                        column_name=field_path,
                        data_type=meta["type"],
                        is_primary_key=is_pk,
                        is_foreign_key=is_fk,
                        samples=list(meta["samples"])[:sample_size],
                        system_recommendation=system_rec,
                        length_mean=length_mean,
                        length_variance=length_variance,
                        profiled_values=profiled_values,
                        distinct_ratio=distinct_ratio,
                        null_ratio=null_ratio,
                    )
                    column_profiles.append(col_prof)

                table_profile = TableProfile(
                    table_name=coll_name,
                    relations=relations,
                    columns=column_profiles,
                )
                tables_profile.append(table_profile)

            return DatabaseProfile(
                database_name=self.database_name,
                tables=tables_profile,
            )
        finally:
            self._release_client(client)

    def inspect_scope(self) -> list[dict[str, Any]]:
        """
        Inspects available collections, document counts, and field scope.
        Conforms to PRD connector contract (inspect_scope).
        """
        client = self._open_client()
        try:
            db = client[self.database_name]
            all_collections = [c for c in db.list_collection_names() if not c.startswith("system.")]
            scopes = []
            for coll_name in sorted(all_collections):
                doc_count = db[coll_name].count_documents({})
                # Quick sample to count distinct fields
                sample_docs = list(db[coll_name].find({}).limit(50))
                fields_set = set()
                for d in sample_docs:
                    fields_set.update(_flatten_document(d).keys())
                scopes.append({
                    "source_type": "mongo",
                    "database": self.database_name,
                    "collection_name": coll_name,
                    "document_count": doc_count,
                    "field_count": len(fields_set),
                    "fields": sorted(fields_set)
                })
            return scopes
        finally:
            self._release_client(client)

    def profile_fields(
        self,
        collection_name: str | None = None,
        sample_size: int = 5,
        max_depth: int = 2
    ) -> list[ColumnProfile]:
        """
        Directly returns flat list of ColumnProfiles for scanner consumption.
        Conforms to PRD connector contract (profile_fields).
        """
        db_profile = self.extract_database_profile(sample_size=sample_size, max_depth=max_depth)
        columns: list[ColumnProfile] = []
        for table in db_profile.tables:
            if collection_name is None or table.table_name == collection_name:
                columns.extend(table.columns)
        return columns

    def to_scanner_contract(
        self,
        sample_size: int = 5,
        max_depth: int = 2
    ) -> list[dict[str, Any]]:
        """
        Converts the MongoDB profile into standardized scanner tasks / contract.
        Each task matches the exact format expected by the 3-tier cascade funnel
        and LangGraph AgentState.

        To ensure 100% compatibility with standard AI tokenizers (which split on '_'),
        the ColumnProfile passed to the scanner formats nested dot paths as snake_case,
        while preserving the true MongoDB dot-notation path in 'field_path'.
        """
        db_profile = self.extract_database_profile(sample_size=sample_size, max_depth=max_depth)
        tasks: list[dict[str, Any]] = []
        for table in db_profile.tables:
            for col in table.columns:
                # Provide a scanner-friendly ColumnProfile copy where dot is replaced by underscore
                # so that standard snake_case tokenizers (col.column_name.replace("_", " "))
                # can naturally split nested fields without modifying AI detection code!
                scanner_col = col.model_copy()
                scanner_col.column_name = col.column_name.replace(".", "_")
                tasks.append({
                    "source_engine": "mongo",
                    "database_name": db_profile.database_name,
                    "collection_name": table.table_name,
                    "field_path": col.column_name,
                    "column_profile": scanner_col,
                    "data_type": col.data_type,
                    "samples": col.samples,
                    "is_primary_key": col.is_primary_key,
                    "is_foreign_key": col.is_foreign_key,
                    "system_recommendation": col.system_recommendation
                })
        return tasks

    def iter_documents(self, collection_name: str, batch_size: int = 1000) -> Iterator[dict[str, Any]]:
        """Đọc từng document theo lô của server, không nạp cả collection vào bộ nhớ."""
        client = self._open_client()
        try:
            yield from client[self.database_name][collection_name].find({}).batch_size(batch_size)
        finally:
            self._release_client(client)

    def export_profile_to_json(self, output_path: str, sample_size: int = 5):
        """
        Exports extracted profile to JSON file for offline inspection and debugging.
        """
        profile = self.extract_database_profile(sample_size=sample_size)
        json_data = profile.model_dump_json(indent=4)
        out_file = Path(output_path)
        out_file.parent.mkdir(parents=True, exist_ok=True)
        out_file.write_text(json_data, encoding="utf-8")
        logger.info(f"Đã lưu cấu trúc MongoDB Profile ra file: {output_path}")
