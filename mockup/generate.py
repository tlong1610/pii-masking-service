"""Sinh mockup MongoDB, nhãn chuẩn và danh mục chuẩn: python -m mockup.generate"""

import argparse
import json
from pathlib import Path

from bson import json_util

from mockup.documents import make_bill, make_contract, make_customer, make_device, make_ticket
from mockup.labels import catalog, field_labels
from mockup.values import FakeValues

DEFAULT_SEED = 20261105
DEFAULT_SIZES = {"customers": 500, "battery_bills": 1000, "tickets": 450, "devices": 300}

_MOCKUP_DIR = Path(__file__).parent


def build_collections(seed: int = DEFAULT_SEED, sizes: dict | None = None) -> tuple[dict[str, list], list[dict]]:
    """Trả các collection và nhãn vị trí thực thể trong văn bản tự do. Mỗi khách có đúng một hợp đồng."""
    sizes = {**DEFAULT_SIZES, **(sizes or {})}
    v = FakeValues(seed)

    customers = [make_customer(v, index) for index in range(sizes["customers"])]
    contracts = [make_contract(v, customer) for customer in customers]

    bills = []
    for _ in range(sizes["battery_bills"]):
        index = v.rng.randrange(len(customers))
        bills.append(make_bill(v, customers[index], contracts[index]))

    tickets, text_spans = [], []
    for index in range(sizes["tickets"]):
        ticket, spans = make_ticket(v, v.rng.choice(customers), index)
        tickets.append(ticket)
        text_spans.append({"collection": "tickets", "id": ticket["TicketNo"], "path": "Note", "labels": spans})

    devices = [make_device(v, index) for index in range(sizes["devices"])]
    collections = {
        "customers": customers,
        "battery_contracts": contracts,
        "battery_bills": bills,
        "tickets": tickets,
        "devices": devices,
    }
    return collections, text_spans


def _write_jsonl(path: Path, lines: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(f"{line}\n" for line in lines), encoding="utf-8")


def write_mockup(data_dir: Path, labels_dir: Path, seed: int = DEFAULT_SEED, sizes: dict | None = None) -> None:
    """Dữ liệu ghi vào data_dir (không commit); nhãn và danh mục không chứa giá trị, ghi vào labels_dir."""
    collections, text_spans = build_collections(seed, sizes)

    all_labels = []
    for name, docs in collections.items():
        _write_jsonl(
            data_dir / "mongo" / f"{name}.jsonl",
            [json_util.dumps(doc, json_options=json_util.RELAXED_JSON_OPTIONS, ensure_ascii=False) for doc in docs],
        )
        labels = field_labels(name, docs)
        all_labels.extend(labels)
        catalog_path = labels_dir / "catalog" / f"{name}.json"
        catalog_path.parent.mkdir(parents=True, exist_ok=True)
        catalog_path.write_text(
            json.dumps(catalog(name, labels), ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )

    _write_jsonl(labels_dir / "fields.jsonl", [json.dumps(item, ensure_ascii=False) for item in all_labels])
    _write_jsonl(labels_dir / "text_spans.jsonl", [json.dumps(item, ensure_ascii=False) for item in text_spans])


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seed", type=int, default=DEFAULT_SEED)
    parser.add_argument("--data-dir", type=Path, default=Path("data/mockup"))
    parser.add_argument("--labels-dir", type=Path, default=_MOCKUP_DIR / "labels")
    args = parser.parse_args()
    write_mockup(args.data_dir, args.labels_dir, args.seed)


if __name__ == "__main__":
    main()
