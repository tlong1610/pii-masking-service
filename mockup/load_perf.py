"""Sinh collection lớn để đo tốc độ: python -m mockup.load_perf

Chỉ dùng đo tốc độ và đọc theo lô, không tính vào độ chính xác: ghi vào database riêng, không có nhãn, eval.run
không đọc tới. Sinh thẳng theo lô vào MongoDB, không ghi file. Quy tắc URI giống mockup.load_mongo.

Có gài các trường PII hiếm để kiểm tra cách lấy mẫu của bộ quét, xem RARE_FIELDS. Giá trị gài sinh từ bộ sinh riêng
nên tính lại được ở eval.perf và không làm đổi các document còn lại.
"""

import argparse
import os
import sys
from collections.abc import Callable
from dataclasses import dataclass

from pymongo import MongoClient

from mockup.documents import make_bill, make_contract, make_customer
from mockup.generate import DEFAULT_SEED
from mockup.load_mongo import DEFAULT_DATABASE, DEFAULT_URI
from mockup.values import FakeValues

PERF_COLLECTION = "battery_bills"
DEFAULT_COUNT = 100_000
_CUSTOMERS = 2000


@dataclass(frozen=True)
class RareField:
    """Trường được gài vào document start, start + every, ... Đường dẫn viết như nhãn chuẩn."""

    path: str
    pii_type: str
    case: str
    start: int
    every: int
    value: Callable[[FakeValues], str]
    template: str = "{value}"


RARE_FIELDS = [
    RareField("SpouseIdNumber", "CCCD", "chỉ có sau document 50.000", 60_000, 500, lambda v: v.cccd()),
    RareField("EmergencyContact.Phone", "PHONE", "lồng, chỉ có sau document 50.000", 75_000, 1000, lambda v: v.phone()),
    RareField(
        "Profile.Kyc.Guardian.Email",
        "EMAIL",
        "lồng sâu hơn phạm vi quét, chỉ có sau document 50.000",
        90_000,
        250,
        lambda v: v.email("Khach Hiem"),
    ),
    RareField(
        "RelatedContacts[].Phone", "PHONE", "trong mảng, chỉ có sau document 50.000", 52_000, 500, lambda v: v.phone()
    ),
    RareField(
        "ExtraNote",
        "PHONE",
        "văn bản tự do, chỉ có sau document 50.000",
        55_000,
        1000,
        lambda v: v.phone(),
        "Khách đổi số liên hệ sang {value}",
    ),
    RareField(
        "ReferrerEmail",
        "EMAIL",
        "khoảng 0,1% document, có 1 document trong 100 đầu",
        37,
        997,
        lambda v: v.email("Khach Hiem"),
    ),
    RareField(
        "x9", "CCCD", "tên mơ hồ, khoảng 0,1% document, có 1 document trong 100 đầu", 41, 1009, lambda v: v.cccd()
    ),
    RareField(
        "PaidAt.StoreName",
        "PHONE",
        "nhập nhầm vào trường đã kết luận không phải PII, chỉ có sau document 50.000",
        65_000,
        1000,
        lambda v: v.phone(),
    ),
]


def rare_values(rare_fields: list[RareField], count: int, seed: int = DEFAULT_SEED) -> dict[str, dict[int, str]]:
    """Đường dẫn -> {vị trí document -> giá trị PII đã gài}. Chỉ dùng trong bộ nhớ."""
    planted = {}
    for offset, field in enumerate(rare_fields):
        v = FakeValues(seed + 3 + offset)
        planted[field.path] = {index: field.value(v) for index in range(field.start, count, field.every)}
    return planted


def _plant(document: dict, path: str, value: str) -> None:
    """Ghi giá trị vào đường dẫn, tạo dict hoặc mảng một phần tử nếu chưa có."""
    *parents, leaf = path.split(".")
    target = document
    for name in parents:
        if name.endswith("[]"):
            target[name[:-2]] = [{}]
            target = target[name[:-2]][0]
        else:
            target = target.setdefault(name, {})
    target[leaf] = value


def perf_database(database: str = DEFAULT_DATABASE) -> str:
    return f"{database}_perf"


def load_perf(
    client,
    database: str,
    count: int = DEFAULT_COUNT,
    seed: int = DEFAULT_SEED,
    batch_size: int = 1000,
    rare_fields: list[RareField] | None = None,
) -> int:
    """Thay collection đo tốc độ bằng count bill, trả số document đã nạp."""
    unknown = sorted(set(client[database].list_collection_names()) - {PERF_COLLECTION})
    if unknown:
        raise ValueError(f"Database {database} có collection không thuộc mockup: {unknown}. Không nạp.")

    v = FakeValues(seed + 2)
    customers = [make_customer(v, index) for index in range(_CUSTOMERS)]
    contracts = [make_contract(v, customer) for customer in customers]

    rare_fields = RARE_FIELDS if rare_fields is None else rare_fields
    planted = rare_values(rare_fields, count, seed)
    by_document: dict[int, list[tuple[RareField, str]]] = {}
    for field in rare_fields:
        for position, value in planted[field.path].items():
            by_document.setdefault(position, []).append((field, value))

    collection = client[database][PERF_COLLECTION]
    collection.drop()
    for start in range(0, count, batch_size):
        batch = []
        for position in range(start, min(start + batch_size, count)):
            index = v.rng.randrange(_CUSTOMERS)
            bill = make_bill(v, customers[index], contracts[index])
            for field, value in by_document.get(position, []):
                _plant(bill, field.path, field.template.format(value=value))
            batch.append(bill)
        collection.insert_many(batch)
    return collection.count_documents({})


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--uri", default=os.getenv("MOCKUP_MONGO_URI", DEFAULT_URI))
    parser.add_argument("--database", default=perf_database(os.getenv("MOCKUP_MONGO_DB", DEFAULT_DATABASE)))
    parser.add_argument("--count", type=int, default=DEFAULT_COUNT)
    args = parser.parse_args()

    client = MongoClient(args.uri, serverSelectionTimeoutMS=5000)
    try:
        print(f"{PERF_COLLECTION}: {load_perf(client, args.database, args.count)}")
    except ValueError as exc:
        sys.exit(str(exc))
    finally:
        client.close()


if __name__ == "__main__":
    main()
