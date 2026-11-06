import logging

import psycopg
from psycopg import sql
from psycopg.rows import dict_row

from piimask.schemas import ColumnProfile, DatabaseProfile, TableProfile, TableRelation

logger = logging.getLogger(__name__)


class PostgresConnector:
    """Đọc schema và dữ liệu mẫu từ PostgreSQL. Mẫu chỉ giữ trong bộ nhớ."""

    def __init__(self, connection_string: str):
        self.connection_string = connection_string

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
            DatabaseProfile: Cấu trúc DB để bộ quét phân loại
        """
        tables_profile: list[TableProfile] = []
        # Lấy tên database từ chuỗi kết nối (ví dụ: postgresql://user:pass@host:5432/dbname)
        db_name = self.connection_string.split("/")[-1].split("?")[0]

        with psycopg.connect(self.connection_string, row_factory=dict_row) as conn:
            with conn.cursor() as cur:
                # 1. Quét danh sách các bảng (Tables)
                cur.execute(
                    "SELECT table_name FROM information_schema.tables WHERE table_schema = %s AND table_type = 'BASE TABLE'",
                    (schema_name,),
                )
                tables = [row["table_name"] for row in cur.fetchall()]
                if table_names:
                    allowed = set(table_names)
                    tables = [t for t in tables if t in allowed]

                # 2. Quét toàn bộ Primary Keys (Khóa chính)
                cur.execute(
                    """
                    SELECT c.table_name, c.column_name
                    FROM information_schema.columns c
                    JOIN information_schema.key_column_usage kcu
                        ON c.table_name = kcu.table_name AND c.column_name = kcu.column_name
                    JOIN information_schema.table_constraints tc
                        ON kcu.constraint_name = tc.constraint_name AND tc.constraint_type = 'PRIMARY KEY'
                    WHERE c.table_schema = %s
                """,
                    (schema_name,),
                )
                pks = cur.fetchall()
                pk_set = {(row["table_name"], row["column_name"]) for row in pks}

                # 3. Quét toàn bộ Foreign Keys (Khóa ngoại) và xây dựng đồ thị quan hệ
                cur.execute(
                    """
                    SELECT
                        tc.table_name AS source_table, kcu.column_name AS source_column,
                        ccu.table_name AS target_table, ccu.column_name AS target_column
                    FROM information_schema.table_constraints AS tc
                    JOIN information_schema.key_column_usage AS kcu ON tc.constraint_name = kcu.constraint_name
                    JOIN information_schema.constraint_column_usage AS ccu ON ccu.constraint_name = tc.constraint_name
                    WHERE tc.constraint_schema = %s AND tc.constraint_type = 'FOREIGN KEY'
                """,
                    (schema_name,),
                )
                fks = cur.fetchall()

                # Gom nhóm FK theo từng bảng nguồn
                fk_map = {}
                for fk in fks:
                    src_table = fk["source_table"]
                    if src_table not in fk_map:
                        fk_map[src_table] = []
                    fk_map[src_table].append(
                        {
                            "from_column": fk["source_column"],
                            "to_table": fk["target_table"],
                            "to_column": fk["target_column"],
                        }
                    )

                # 4. Duyệt qua từng bảng để lấy danh sách cột và Samples
                for table in tables:
                    # Thông tin quan hệ của bảng này
                    relations_data = fk_map.get(table, [])
                    relations = [TableRelation(**r) for r in relations_data]
                    fk_columns = {r["from_column"] for r in relations_data}

                    # Quét danh sách cột của bảng
                    cur.execute(
                        """
                        SELECT column_name, data_type
                        FROM information_schema.columns
                        WHERE table_schema = %s AND table_name = %s
                    """,
                        (schema_name, table),
                    )
                    columns_info = cur.fetchall()

                    column_profiles = []
                    for col_info in columns_info:
                        col_name = col_info["column_name"]
                        data_type = col_info["data_type"]

                        is_pk = (table, col_name) in pk_set
                        is_fk = col_name in fk_columns

                        if sample_size > 0:
                            # Lấy mẫu (Sample data) khác NULL
                            query = sql.SQL("SELECT DISTINCT {} FROM {} WHERE {} IS NOT NULL LIMIT {}").format(
                                sql.Identifier(col_name),
                                sql.Identifier(table),
                                sql.Identifier(col_name),
                                sql.Literal(sample_size),
                            )

                            try:
                                cur.execute(query)
                                samples_raw = cur.fetchall()
                                samples = [str(r[col_name]) for r in samples_raw if r[col_name] is not None]
                            except Exception as e:
                                # Thông báo lỗi của driver có thể chứa giá trị nên chỉ ghi loại lỗi.
                                logger.error("Lỗi khi lấy mẫu bảng %s cột %s: %s", table, col_name, type(e).__name__)
                                samples = []
                        else:
                            samples = []

                        col_prof = ColumnProfile(
                            table_name=table,
                            column_name=col_name,
                            data_type=data_type,
                            is_primary_key=is_pk,
                            is_foreign_key=is_fk,
                            samples=samples,
                        )
                        column_profiles.append(col_prof)

                    # Gom lại thành Profile của bảng
                    table_profile = TableProfile(table_name=table, relations=relations, columns=column_profiles)
                    tables_profile.append(table_profile)

        # 5. Trả về Profile toàn cục của cả Database
        return DatabaseProfile(database_name=db_name, tables=tables_profile)
