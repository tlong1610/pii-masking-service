"""Sinh collection lớn để đo tốc độ: python -m mockup.load_perf

Chỉ dùng đo tốc độ và đọc theo lô, không tính vào độ chính xác: ghi vào database riêng, không có nhãn, eval.run
không đọc tới. Sinh thẳng theo lô vào MongoDB, không ghi file. Quy tắc URI giống mockup.load_mongo.
"""

import argparse
import os
import sys

from pymongo import MongoClient

from mockup.documents import make_bill, make_contract, make_customer
from mockup.generate import DEFAULT_SEED
from mockup.load_mongo import DEFAULT_DATABASE, DEFAULT_URI
from mockup.values import FakeValues

PERF_COLLECTION = "battery_bills"
DEFAULT_COUNT = 100_000
_CUSTOMERS = 2000


def perf_database(database: str = DEFAULT_DATABASE) -> str:
    return f"{database}_perf"


def load_perf(
    client, database: str, count: int = DEFAULT_COUNT, seed: int = DEFAULT_SEED, batch_size: int = 1000
) -> int:
    """Thay collection đo tốc độ bằng count bill, trả số document đã nạp."""
    unknown = sorted(set(client[database].list_collection_names()) - {PERF_COLLECTION})
    if unknown:
        raise ValueError(f"Database {database} có collection không thuộc mockup: {unknown}. Không nạp.")

    v = FakeValues(seed + 2)
    customers = [make_customer(v, index) for index in range(_CUSTOMERS)]
    contracts = [make_contract(v, customer) for customer in customers]

    collection = client[database][PERF_COLLECTION]
    collection.drop()
    for start in range(0, count, batch_size):
        batch = []
        for _ in range(min(batch_size, count - start)):
            index = v.rng.randrange(_CUSTOMERS)
            batch.append(make_bill(v, customers[index], contracts[index]))
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
