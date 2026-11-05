"""API che PII: uvicorn api.main:app. Hợp đồng ở docs/api/, tài liệu tự sinh ở /docs và /openapi.json.

Fail closed: mọi lỗi trả status khác OK, không có maskedText, và không chứa nội dung yêu cầu. Bên gọi phải chặn lưu
và gửi khi status khác OK.
"""

import logging
from typing import Literal

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from piimask import __version__
from piimask.detection.ner_orchestrator import get_ner_pipeline
from piimask.transform.text_masker import mask_text

CONTRACT_VERSION = "1.0.0"
SCHEMA_VERSION = 1

logger = logging.getLogger(__name__)

app = FastAPI(title="PII Masking API", version=CONTRACT_VERSION)


class MaskTextRequest(BaseModel):
    schemaVersion: Literal[1]  # noqa: N815
    requestId: str = Field(min_length=1, max_length=128)  # noqa: N815
    context: Literal["faq", "ocr", "ticket", "log"]
    locale: str
    text: str
    keep: list[str] = Field(default_factory=list, description="Các loại không che, ví dụ METER_ID")


class EntityOut(BaseModel):
    type: str
    start: int = Field(description="Vị trí trên văn bản gốc")
    end: int


class MaskTextResponse(BaseModel):
    schemaVersion: Literal[1]  # noqa: N815
    requestId: str  # noqa: N815
    maskerVersion: str  # noqa: N815
    status: Literal["OK"]
    maskedText: str  # noqa: N815
    entities: list[EntityOut]


class FieldError(BaseModel):
    field: str
    type: str


class MaskTextError(BaseModel):
    """Không có maskedText, requestId rỗng nếu yêu cầu không đọc được."""

    schemaVersion: Literal[1]  # noqa: N815
    requestId: str | None  # noqa: N815
    maskerVersion: str  # noqa: N815
    status: Literal["ERROR", "INVALID_REQUEST"]
    errors: list[FieldError] = Field(default_factory=list)


class HealthResponse(BaseModel):
    status: Literal["OK", "ERROR"]
    maskerVersion: str  # noqa: N815
    nerEnabled: bool = Field(description="false nghĩa là chỉ có regex và từ điển, chưa che được họ tên và địa chỉ")  # noqa: N815


def _error(http_status: int, status: str, request_id: str | None, errors: list[FieldError] | None = None):
    body = MaskTextError(
        schemaVersion=SCHEMA_VERSION,
        requestId=request_id,
        maskerVersion=__version__,
        status=status,
        errors=errors or [],
    )
    return JSONResponse(status_code=http_status, content=body.model_dump())


@app.exception_handler(RequestValidationError)
async def invalid_request(_: Request, exc: RequestValidationError) -> JSONResponse:
    # Phản hồi mặc định của FastAPI lặp lại phần thân yêu cầu trong trường input, tức là lặp lại văn bản gốc.
    errors = [
        FieldError(field=".".join(str(part) for part in error["loc"]), type=error["type"]) for error in exc.errors()
    ]
    return _error(422, "INVALID_REQUEST", None, errors)


@app.get("/health", response_model=HealthResponse, responses={503: {"model": HealthResponse}})
def health():
    try:
        pipeline = get_ner_pipeline()
        mask_text("0900000000", pipeline=pipeline)
    except Exception as exc:
        logger.error("Kiểm tra sức khỏe thất bại: %s", type(exc).__name__)
        body = HealthResponse(status="ERROR", maskerVersion=__version__, nerEnabled=False)
        return JSONResponse(status_code=503, content=body.model_dump())
    return HealthResponse(status="OK", maskerVersion=__version__, nerEnabled=pipeline.ml_scanner is not None)


@app.post(
    "/v1/mask/text",
    response_model=MaskTextResponse,
    responses={422: {"model": MaskTextError}, 500: {"model": MaskTextError}},
)
def mask(request: MaskTextRequest):
    try:
        result = mask_text(request.text, request.keep)
    except Exception as exc:
        # Chỉ ghi loại lỗi: thông điệp của exception có thể chứa văn bản đang che.
        logger.error("Che văn bản thất bại: %s", type(exc).__name__)
        return _error(500, "ERROR", request.requestId)
    return MaskTextResponse(
        schemaVersion=SCHEMA_VERSION,
        requestId=request.requestId,
        maskerVersion=__version__,
        status="OK",
        maskedText=result.text,
        entities=[EntityOut(type=entity.type, start=entity.start, end=entity.end) for entity in result.entities],
    )
