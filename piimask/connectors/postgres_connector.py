import logging

try:
    import psycopg
    from psycopg.rows import dict_row
except ImportError:
    logging.warning("psycopg is not installed. Please install it using `pip install psycopg`.")
    psycopg = None

from piimask.schemas import ColumnProfile, DatabaseProfile, TableProfile, TableRelation

logger = logging.getLogger(__name__)


class PostgresConnector:
    """
    Connector để đọc dữ liệu mẫu và lấy thông tin schema từ PostgreSQL.
    Dành cho luồng PII Detection.
    """

    def __init__(self, connection_string: str):
        self.connection_string = connection_string

    @staticmethod
    def _distribution_stats(conn, cur, table: str, col_name: str) -> tuple[int | None, float | None, float | None]:
        """Counts over the first STATS_ROW_LIMIT rows, computed in Postgres; only the three numbers come back.

        Runs in a savepoint so a failure (odd type, permissions) skips the stats without aborting the scan.
        """
        from psycopg import sql

        from piimask.detection.column_stats import STATS_ROW_LIMIT, ratios_from_counts

        query = sql.SQL(
            "SELECT COUNT(*) AS n_rows, COUNT(c) AS n_non_null, COUNT(DISTINCT c::TEXT) AS n_distinct "
            "FROM (SELECT {} AS c FROM {} LIMIT {}) AS s"
        ).format(sql.Identifier(col_name), sql.Identifier(table), sql.Literal(STATS_ROW_LIMIT))
        try:
            with conn.transaction():
                cur.execute(query)
                row = cur.fetchone()
        except Exception as exc:
            logger.warning("Distribution stats skipped for %s.%s: %s", table, col_name, type(exc).__name__)
            return None, None, None
        if not row:
            return None, None, None
        return ratios_from_counts(int(row["n_rows"]), int(row["n_non_null"]), int(row["n_distinct"]))

    def extract_database_profile(
        self,
        schema_name: str = "public",
        sample_size: int = 5,
        table_names: tuple[str, ...] | list[str] | set[str] | None = None,
    ) -> DatabaseProfile:
        """
        Trích xuất toàn bộ cấu trúc CSDL bao gồm quan hệ và dữ liệu mẫu.

        Args:
            schema_name: Tên schema cần quét (thường là 'public' trong Postgres)
            sample_size: Số lượng giá trị mẫu cần trích xuất mỗi cột (nếu <= 0 sẽ chỉ quét schema siêu nhanh)
            table_names: Danh sách bảng cụ thể cần lấy (nếu None sẽ lấy tất cả)

        Returns:
            DatabaseProfile: Object chứa cấu trúc DB chuẩn bị cho AI Agent
        """
        if psycopg is None:
            raise RuntimeError("Thư viện psycopg chưa được cài đặt. Không thể kết nối Database.")

        tables_profile: list[TableProfile] = []
        # Lấy tên database từ chuỗi kết nối (ví dụ: postgresql://user:pass@host:5432/dbname)
        db_name = self.connection_string.split("/")[-1].split("?")[0]

        with psycopg.connect(self.connection_string, row_factory=dict_row) as conn:
            with conn.cursor() as cur:
                # 1. Quét danh sách các bảng (Tables)
                cur.execute(
                    "SELECT table_name FROM information_schema.tables WHERE table_schema = %s AND table_type = 'BASE TABLE'",
                    (schema_name,)
                )
                tables = [row["table_name"] for row in cur.fetchall()]
                if table_names:
                    allowed = set(table_names)
                    tables = [t for t in tables if t in allowed]

                # 2. Quét toàn bộ Primary Keys (Khóa chính)
                cur.execute("""
                    SELECT c.table_name, c.column_name
                    FROM information_schema.columns c
                    JOIN information_schema.key_column_usage kcu
                        ON c.table_name = kcu.table_name AND c.column_name = kcu.column_name
                    JOIN information_schema.table_constraints tc
                        ON kcu.constraint_name = tc.constraint_name AND tc.constraint_type = 'PRIMARY KEY'
                    WHERE c.table_schema = %s
                """, (schema_name,))
                pks = cur.fetchall()
                pk_set = {(row["table_name"], row["column_name"]) for row in pks}

                # 3. Quét toàn bộ Foreign Keys (Khóa ngoại) và xây dựng đồ thị quan hệ
                cur.execute("""
                    SELECT
                        tc.table_name AS source_table, kcu.column_name AS source_column,
                        ccu.table_name AS target_table, ccu.column_name AS target_column
                    FROM information_schema.table_constraints AS tc
                    JOIN information_schema.key_column_usage AS kcu ON tc.constraint_name = kcu.constraint_name
                    JOIN information_schema.constraint_column_usage AS ccu ON ccu.constraint_name = tc.constraint_name
                    WHERE tc.constraint_schema = %s AND tc.constraint_type = 'FOREIGN KEY'
                """, (schema_name,))
                fks = cur.fetchall()

                # Gom nhóm FK theo từng bảng nguồn
                fk_map = {}
                for fk in fks:
                    src_table = fk["source_table"]
                    if src_table not in fk_map:
                        fk_map[src_table] = []
                    fk_map[src_table].append({
                        "from_column": fk["source_column"],
                        "to_table": fk["target_table"],
                        "to_column": fk["target_column"]
                    })

                # 4. Duyệt qua từng bảng để lấy danh sách cột và Samples
                for table in tables:
                    # Thông tin quan hệ của bảng này
                    relations_data = fk_map.get(table, [])
                    relations = [
                        TableRelation(**r) for r in relations_data
                    ]
                    fk_columns = {r["from_column"] for r in relations_data}

                    # Quét danh sách cột của bảng
                    cur.execute("""
                        SELECT column_name, data_type
                        FROM information_schema.columns
                        WHERE table_schema = %s AND table_name = %s
                    """, (schema_name, table))
                    columns_info = cur.fetchall()

                    column_profiles = []
                    for col_info in columns_info:
                        col_name = col_info["column_name"]
                        data_type = col_info["data_type"]

                        is_pk = (table, col_name) in pk_set
                        is_fk = col_name in fk_columns

                        # Hard-code recommend: Các trường khóa bắt buộc dùng HASHING
                        system_rec = "HASHING" if is_pk or is_fk else None

                        if sample_size > 0:
                            # Lấy mẫu (Sample data) khác NULL
                            from psycopg import sql
                            query = sql.SQL("SELECT DISTINCT {} FROM {} WHERE {} IS NOT NULL LIMIT {}").format(
                                sql.Identifier(col_name),
                                sql.Identifier(table),
                                sql.Identifier(col_name),
                                sql.Literal(sample_size)
                            )

                            try:
                                cur.execute(query)
                                samples_raw = cur.fetchall()
                                samples = [str(r[col_name]) for r in samples_raw if r[col_name] is not None]
                            except Exception as e:
                                logger.error(f"Lỗi khi trích xuất mẫu bảng {table} cột {col_name}: {e}")
                                samples = []

                            # Tính mean và variance của độ dài dữ liệu
                            stats_query = sql.SQL("SELECT AVG(LENGTH({}::TEXT)) as mean_len, COALESCE(VARIANCE(LENGTH({}::TEXT)), 0) as var_len FROM {} WHERE {} IS NOT NULL").format(
                                sql.Identifier(col_name),
                                sql.Identifier(col_name),
                                sql.Identifier(table),
                                sql.Identifier(col_name)
                            )

                            length_mean = None
                            length_variance = None
                            try:
                                cur.execute(stats_query)
                                stats_raw = cur.fetchone()
                                if stats_raw:
                                    length_mean = float(stats_raw["mean_len"]) if stats_raw["mean_len"] is not None else None
                                    length_variance = float(stats_raw["var_len"]) if stats_raw["var_len"] is not None else None
                            except Exception as e:
                                logger.error(f"Lỗi khi tính toán thống kê độ dài bảng {table} cột {col_name}: {e}")

                            profiled_values, distinct_ratio, null_ratio = self._distribution_stats(
                                conn, cur, table, col_name
                            )
                        else:
                            samples = []
                            length_mean = None
                            length_variance = None
                            profiled_values, distinct_ratio, null_ratio = None, None, None

                        col_prof = ColumnProfile(
                            table_name=table,
                            column_name=col_name,
                            data_type=data_type,
                            is_primary_key=is_pk,
                            is_foreign_key=is_fk,
                            samples=samples,
                            system_recommendation=system_rec,
                            length_mean=length_mean,
                            length_variance=length_variance,
                            profiled_values=profiled_values,
                            distinct_ratio=distinct_ratio,
                            null_ratio=null_ratio,
                        )
                        column_profiles.append(col_prof)

                    # Gom lại thành Profile của bảng
                    table_profile = TableProfile(
                        table_name=table,
                        relations=relations,
                        columns=column_profiles
                    )
                    tables_profile.append(table_profile)

        # 5. Trả về Profile toàn cục của cả Database
        return DatabaseProfile(
            database_name=db_name,
            tables=tables_profile
        )

    def extract_schema_overview(self, schema_name: str = "public") -> DatabaseProfile:
        """Tables, columns, primary and foreign keys of one schema in three catalog queries.

        For the DPO scope picker: no samples, and the number of round trips does not grow with
        the number of tables (the per-table loop of ``extract_database_profile`` is slow on remote
        hosts such as Supabase poolers).
        """
        if psycopg is None:
            raise RuntimeError("Thư viện psycopg chưa được cài đặt. Không thể kết nối Database.")
        db_name = self.connection_string.split("/")[-1].split("?")[0]
        with psycopg.connect(self.connection_string, row_factory=dict_row, connect_timeout=10) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT c.table_name, c.column_name, c.data_type
                    FROM information_schema.columns c
                    JOIN information_schema.tables t
                      ON t.table_schema = c.table_schema AND t.table_name = c.table_name
                    WHERE c.table_schema = %s AND t.table_type = 'BASE TABLE'
                    ORDER BY c.table_name, c.ordinal_position
                    """,
                    (schema_name,),
                )
                columns = cur.fetchall()
                cur.execute(
                    """
                    SELECT cls.relname AS table_name, att.attname AS column_name
                    FROM pg_index idx
                    JOIN pg_class cls ON cls.oid = idx.indrelid
                    JOIN pg_namespace ns ON ns.oid = cls.relnamespace
                    JOIN pg_attribute att ON att.attrelid = cls.oid AND att.attnum = ANY(idx.indkey)
                    WHERE idx.indisprimary AND ns.nspname = %s
                    """,
                    (schema_name,),
                )
                pk_set = {(r["table_name"], r["column_name"]) for r in cur.fetchall()}
                cur.execute(
                    """
                    SELECT src.relname AS source_table, src_att.attname AS source_column,
                           dst.relname AS target_table, dst_att.attname AS target_column
                    FROM pg_constraint con
                    JOIN pg_class src ON src.oid = con.conrelid
                    JOIN pg_namespace ns ON ns.oid = src.relnamespace
                    JOIN pg_class dst ON dst.oid = con.confrelid
                    JOIN LATERAL unnest(con.conkey, con.confkey) AS k(src_num, dst_num) ON true
                    JOIN pg_attribute src_att ON src_att.attrelid = src.oid AND src_att.attnum = k.src_num
                    JOIN pg_attribute dst_att ON dst_att.attrelid = dst.oid AND dst_att.attnum = k.dst_num
                    WHERE con.contype = 'f' AND ns.nspname = %s
                    """,
                    (schema_name,),
                )
                fks = cur.fetchall()

        fk_map: dict[str, list[dict]] = {}
        for fk in fks:
            fk_map.setdefault(fk["source_table"], []).append(
                {"from_column": fk["source_column"], "to_table": fk["target_table"], "to_column": fk["target_column"]}
            )
        by_table: dict[str, list[ColumnProfile]] = {}
        for col in columns:
            table, name = col["table_name"], col["column_name"]
            is_pk = (table, name) in pk_set
            is_fk = any(r["from_column"] == name for r in fk_map.get(table, []))
            by_table.setdefault(table, []).append(
                ColumnProfile(
                    table_name=table,
                    column_name=name,
                    data_type=col["data_type"],
                    is_primary_key=is_pk,
                    is_foreign_key=is_fk,
                    samples=[],
                    system_recommendation="HASHING" if is_pk or is_fk else None,
                )
            )
        return DatabaseProfile(
            database_name=db_name,
            tables=[
                TableProfile(
                    table_name=table,
                    relations=[TableRelation(**r) for r in fk_map.get(table, [])],
                    columns=cols,
                )
                for table, cols in by_table.items()
            ],
        )

    def export_profile_to_json(self, output_path: str, schema_name: str = "public", sample_size: int = 5):
        """
        Tiện ích: Trích xuất và lưu toàn bộ cấu trúc DB ra file JSON vật lý.
        Dành cho mục đích debug hoặc chia sẻ data contract giữa Backend và AI Engineer.

        Args:
            output_path: Đường dẫn file JSON cần lưu (VD: 'data/fixtures/db_profile.json')
            schema_name: Tên schema cần quét
            sample_size: Số lượng mẫu dữ liệu
        """
        # 1. Trích xuất
        profile = self.extract_database_profile(schema_name, sample_size)

        # 2. Convert sang JSON string
        json_data = profile.model_dump_json(indent=4)

        # 3. Lưu ra file
        from pathlib import Path
        Path(output_path).write_text(json_data, encoding="utf-8")
        logger.info(f"Đã lưu cấu trúc DB ra file: {output_path}")

    def list_relations(self, schema_name: str = "public") -> list[tuple[str, str, str, str]]:
        """List foreign key relations as (source_table, source_column, target_table, target_column)."""
        if psycopg is None:
            raise RuntimeError("Thư viện psycopg chưa được cài đặt. Không thể kết nối Database.")
        with psycopg.connect(self.connection_string, row_factory=dict_row) as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    SELECT
                        tc.table_name AS source_table,
                        kcu.column_name AS source_column,
                        ccu.table_name AS target_table,
                        ccu.column_name AS target_column
                    FROM information_schema.table_constraints AS tc
                    JOIN information_schema.key_column_usage AS kcu
                      ON tc.constraint_name = kcu.constraint_name
                      AND tc.table_schema = kcu.table_schema
                    JOIN information_schema.constraint_column_usage AS ccu
                      ON ccu.constraint_name = tc.constraint_name
                      AND ccu.table_schema = tc.table_schema
                    WHERE tc.constraint_type = 'FOREIGN KEY'
                      AND tc.table_schema = %s
                """, (schema_name,))
                rows = cur.fetchall()
                return [
                    (r["source_table"], r["source_column"], r["target_table"], r["target_column"])
                    for r in rows
                ]

