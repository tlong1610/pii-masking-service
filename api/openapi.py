"""Ghi hợp đồng OpenAPI vào repo: python -m api.openapi"""

import json
from pathlib import Path

from api.main import app

CONTRACT_PATH = Path(__file__).resolve().parent.parent / "docs/api/openapi-v1.json"


def render() -> str:
    return json.dumps(app.openapi(), ensure_ascii=False, indent=2) + "\n"


if __name__ == "__main__":
    CONTRACT_PATH.parent.mkdir(parents=True, exist_ok=True)
    CONTRACT_PATH.write_text(render(), encoding="utf-8")
