"""The ASR reference of a customer turn: the words the voice reads, and the entities they state.

The model writes each customer turn of a call the way a caller says it (BTC ``data/asr/ground_truth.json``:
numbers, money, codes and brand names as words). That string is sent to TTS, so it is both the audio
and the WER reference; ``entities`` are what BTC's ``entity_accuracy`` compares against.
"""
from typing import Any, Literal

from pydantic import Field

from .catalog import StrictModel

#: Why the customer does not buy yet, as BTC's ground truth labels it ("can hoi chong", "so sanh gia"), plus the
#: other reasons the scenarios use; a fixed list, so the entity can be matched exactly.
Blocker = Literal["can hoi chong", "can hoi vo", "can hoi gia dinh", "so sanh gia", "vuot ngan sach", "cho luong",
                  "can suy nghi them"]


class SpokenEntities(StrictModel):
    """Values the customer states in this turn, in BTC's ``asr/ground_truth.json`` keys; null when not said."""

    room_area_m2: int | None = Field(None, description="Diện tích phòng khách nói, m² (\"hai mươi lăm mét vuông\" → 25)")
    has_children: bool | None = Field(None, description="Khách nói nhà có (true) / không có (false) trẻ nhỏ")
    budget_vnd: int | None = Field(None, description="Ngân sách khách nói, đồng (\"năm triệu\" → 5000000)")
    competitor_price_vnd: int | None = Field(None, description="Giá chỗ khác khách đưa ra để so sánh, đồng")
    payment: Literal["COD", "bank"] | None = Field(None, description="Cách trả tiền khách chọn: COD (thu hộ) hoặc bank (chuyển khoản)")
    sku: str | None = Field(None, description="Mã sản phẩm khách nhắc tới, CHỈ lấy từ danh sách products được gửi")
    order_id: str | None = Field(None, description="Mã đơn khách đọc, viết hoa như OD312456")
    phone: str | None = Field(None, description="Số điện thoại khách đọc, 10 chữ số")
    size_old: int | str | None = Field(None, description="Size đang có khi khách muốn đổi")
    size_new: int | str | None = Field(None, description="Size khách muốn đổi sang")
    color: str | None = Field(None, description="Màu khách chọn, không dấu, chữ thường (\"den\")")
    blocker: Blocker | None = Field(None, description="Lý do chưa chốt mà câu nói rõ; null khi câu không nêu lý do")

    def stated(self) -> dict[str, Any]:
        return self.model_dump(exclude_none=True)


class SpokenTurn(StrictModel):
    """One customer turn as it is spoken."""

    idx: int = Field(ge=1, description="Số thứ tự của câu khách trong cuộc gọi, như trong input (1, 2, …)")
    spoken_text: str = Field(min_length=1, description="Câu khách đọc thành lời: chữ thường, không còn chữ số hay mã viết tắt, "
                                                       "giữ nguyên mọi từ khác và dấu câu")
    entities: SpokenEntities = Field(description="Giá trị khách nói trong câu này; để null những gì câu không nói")


class SpokenCall(StrictModel):
    """What the model returns: every customer turn of the call that was sent, in order."""

    turns: list[SpokenTurn] = Field(min_length=1, description="Đúng một phần tử cho MỖI câu khách được gửi, cùng idx")
