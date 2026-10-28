"""The ASR ground truth of a line: the words the voice reads, and the entities they state.

The model writes each line of a call (the customer's, or the shop agent's in a whole dialogue) the way it is said
aloud (BTC ``data/asr/ground_truth.json``: numbers, money, codes and brand names as words). That string is sent to
TTS, so it is both the audio and the WER reference; ``entities`` are what BTC's ``entity_accuracy`` compares against.

:class:`SpokenEntities` is the one entity vocabulary of both sides: ``ground_truth.json`` carries its JSON schema
(``entity_schema``), and ``evaluation/agent-evaluation`` extracts the entities of what a recogniser heard into the same
schema, so a correct transcript can score 100%.
"""
from typing import Any, Literal

from pydantic import Field

from .catalog import StrictModel

#: Why the customer does not buy yet, as BTC's ground truth labels it ("can hoi chong", "so sanh gia"): the agent's
#: own ``blocker`` phrases (``components/memory/ontology.py``) without diacritics, so what the agent understands from
#: the same words matches exactly.
Blocker = Literal["can hoi chong", "can hoi vo", "can hoi nguoi nha", "so sanh gia", "vuot ngan sach", "cho luong",
                  "can suy nghi them"]
DATE = r"^\d{4}-\d{2}-\d{2}$"


class SpokenEntities(StrictModel):
    """Values a line states, in BTC's ``asr/ground_truth.json`` keys (D01–D04); null when the line does not say it."""

    # what the customer tells
    room_area_m2: int | None = Field(None, description="Diện tích phòng, m² (\"hai mươi lăm mét vuông\" → 25)")
    has_children: bool | None = Field(None, description="Nhà có (true) / không có (false) trẻ nhỏ")
    budget_vnd: int | None = Field(None, description="Ngân sách khách nói, đồng (\"năm triệu\" → 5000000)")
    competitor_price_vnd: int | None = Field(None, description="Giá chỗ khác khách đưa ra để so sánh, đồng")
    payment: Literal["COD", "bank"] | None = Field(None, description="Cách trả tiền: COD (thu hộ) hoặc bank (chuyển khoản)")
    blocker: Blocker | None = Field(None, description="Lý do chưa chốt mà câu nói rõ; null khi câu không nêu lý do")
    size_old: int | str | None = Field(None, description="Size đang có khi khách muốn đổi")
    size_new: int | str | None = Field(None, description="Size khách muốn đổi sang")
    color: str | None = Field(None, description="Màu được chọn, không dấu, chữ thường (\"den\")")
    phone: str | None = Field(None, description="Số điện thoại được đọc, 10 chữ số")
    # what either side names
    sku: str | None = Field(None, description="Mã sản phẩm được nhắc tới, CHỈ lấy từ danh sách products được gửi")
    order_id: str | None = Field(None, description="Mã đơn được đọc, viết hoa như OD312456")
    # what the shop agent tells
    price_vnd: int | None = Field(None, description="Giá bán agent báo, đồng")
    promo_expiry: str | None = Field(None, pattern=DATE, description="Hạn khuyến mãi agent báo, YYYY-MM-DD")
    delivery_days: int | None = Field(None, description="Số ngày giao hàng agent báo")
    warranty_months: int | None = Field(None, description="Số tháng bảo hành agent báo")
    return_days: int | None = Field(None, description="Số ngày được đổi trả agent báo")
    min_free_ship_vnd: int | None = Field(None, description="Giá trị đơn tối thiểu để miễn phí giao, đồng")
    bulky_fee_vnd: int | None = Field(None, description="Phụ phí hàng cồng kềnh, đồng")
    exchange_fee_vnd: int | None = Field(None, description="Phí đổi hàng, đồng (0 khi miễn phí)")
    refund_vnd: int | None = Field(None, description="Số tiền hoàn lại, đồng")
    in_stock: bool | None = Field(None, description="Agent báo còn hàng (true) / hết hàng (false)")
    restock_date: str | None = Field(None, pattern=DATE, description="Ngày có hàng lại agent báo, YYYY-MM-DD")

    def stated(self) -> dict[str, Any]:
        return self.model_dump(exclude_none=True)


class SpokenTurn(StrictModel):
    """One line as it is spoken."""

    idx: int = Field(ge=1, description="Số thứ tự của câu, như trong input (1, 2, …)")
    spoken_text: str = Field(min_length=1, description="Câu đọc thành lời: chữ thường, không còn chữ số hay mã viết tắt, "
                                                       "giữ nguyên mọi từ khác và dấu câu")
    entities: SpokenEntities = Field(description="Giá trị câu này nói ra; để null những gì câu không nói")


class SpokenCall(StrictModel):
    """What the model returns: every line of the call that was sent, in order."""

    turns: list[SpokenTurn] = Field(min_length=1, description="Đúng một phần tử cho MỖI câu được gửi, cùng idx")


def entity_schema() -> dict[str, Any]:
    """The JSON schema of :class:`SpokenEntities`, written into every ``ground_truth.json`` this project makes."""
    return SpokenEntities.model_json_schema()
