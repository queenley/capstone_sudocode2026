"""AdvisorAgent: drafts what the shop says on one turn. ``docs/design.md`` section 4.4.

A ReAct loop, ``langchain.agents.create_agent``: a model node calls the
lane's tools, a tool node runs them, until the model answers without a tool
call, at most twenty tool calls and eight model calls a turn (an order of
several items needs a quote, a stock check and an order each). The model
comes from config through :class:`~src.agents.base.BaseAgent`; the tools from
MCP under the ``advisor`` role. The knowledge base is not one of them: the
harness retrieves the turn's passages before the advisor runs (section 4.2)
and they arrive in the context.

**Stateless** (principle 2). The agent holds no checkpointer and nothing
between calls: the hot graph hands it a slice of its state (section 3.2) as
:class:`AgentContext` and the recent turns as messages, and gets back a
draft and the tool results. Its ReAct messages live only inside one call.
The conversation itself is the hot graph's ``messages``, checkpointed there
and nowhere else, so there are never two copies of a call to keep in step.

Around the loop, as middleware:

- the context prompt, assembled in section 4.4's order and cut from the
  bottom (:mod:`~src.components.context.budget`);
- one retry of a failed model call, a cap on model calls and on tool calls;
- the lane's tools only (``config/lanes.yaml``);
- **the guardrail before act**: a write tool's arguments are checked before
  it runs, and a Handoff Brief is completed from what the harness knows
  (:mod:`~src.components.guardrails.actions`);
- the tool guard: timeout, retry, circuit breaker, the day of the call and
  the customer's phone filled in, internal fields removed.

**Output** is plain text marking the brief lines it used, ``[B3]``; the
harness strips the marks before anyone reads the reply and keeps them for
tracing (section 5.5). Plain text rather than a structured object so the
same reply can later be streamed sentence by sentence (Appendix E).
"""

from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, AsyncIterator, Literal, Mapping, Sequence

from langchain.agents import create_agent
from langchain.agents.middleware import (
    AgentMiddleware,
    ModelCallLimitMiddleware,
    ModelRequest,
    ModelRetryMiddleware,
    ToolCallLimitMiddleware,
)
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, AIMessageChunk, SystemMessage, ToolMessage
from langchain_core.runnables import RunnableConfig
from langchain_core.tools import BaseTool

from ..components.context.budget import Section, assemble
from ..components.guardrails import actions
from ..components.memory.brief import BriefLine
from ..components.intake import pii
from ..components.intake.itn import format_vnd
from ..config.config_manager import get_lanes
from ..llm import tracing
from ..llm.callback_handler import text_of
from ..mcp.client import dotted
from ..mcp.tools import LaneToolsMiddleware, ToolGuardMiddleware, envelope_of, parse_envelope
from .base import BaseAgent

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class AgentContext:
    """The advisor's slice of the state for one turn (section 3.2).

    Runtime context, not graph state: LangGraph hands it to middleware as
    ``runtime.context`` and never writes it to a checkpoint, which is why the
    customer's raw phone number may travel here, for the tool guard to fill
    in, and nowhere else the model can read.
    """

    call_id: str
    customer_id: str | None = None
    #: The platform customer the web conversation belongs to (logged in or verified), for the
    #: ``account_*`` tools; filled in by the harness, never shown to the model.
    account_id: str | None = None
    #: How to address the customer, when the tier allows knowing it: "chị Hoa".
    address_as: str | None = None
    tier: str = "UNKNOWN"
    lane: str = "NEW"
    mode: str = "speak"
    phase: str = "turn"
    channel: str = "web"
    now: datetime | None = None
    #: The ``on`` argument of every tool: the day of the call.
    on: str | None = None
    #: Brief lines the tier allows the model to see.
    brief_lines: tuple[BriefLine, ...] = ()
    #: Never cut, always first.
    warnings: tuple[str, ...] = ()
    must_not_ask: tuple[str, ...] = ()
    working_summary: str | None = None
    #: Why the previous draft of this turn was blocked, for a regeneration.
    block_reasons: tuple[str, ...] = ()
    #: The sentences of this answer the customer already heard when a later one was blocked:
    #: the regeneration goes on from them instead of starting over.
    already_said: tuple[str, ...] = ()
    #: Tool results already gathered this turn, so a regeneration need not ask again.
    tool_results: tuple[dict[str, Any], ...] = ()
    #: Today's price per sku from every quote in this call, for the order check.
    quotes: Mapping[str, int] = field(default_factory=dict)
    known_orders: frozenset[str] = frozenset()
    #: The customer's phone, raw. Filled into tools by the harness; never shown to the model.
    customer_phone: str | None = None
    shared_phone: bool = False
    vault: pii.Vault = field(default_factory=pii.Vault, repr=False, compare=False)
    #: This call's address tokens and the addresses behind them, raw, the
    #: latest last: filled into the tools that take an address (section 4.4).
    addresses: Mapping[str, str] = field(default_factory=dict)
    #: What the harness fills into a Handoff Brief.
    handoff_defaults: Mapping[str, Any] = field(default_factory=dict)
    switches: Mapping[str, Any] = field(default_factory=dict)
    #: This turn, for the idempotency key of a write tool (section 6.1).
    turn_id: str | None = None
    #: The turn's passages from the knowledge base, already filtered by the
    #: harness: a restricted one carries no text, a superseded one its dates.
    knowledge: tuple[Mapping[str, Any], ...] = ()
    #: What the search found when no passage is shown: that none was relevant.
    knowledge_note: str | None = None
    #: What ``route`` adds to the lane's instruction (PB-10, PB-11, a spoken channel).
    notes: tuple[str, ...] = ()
    #: Why the lane is CONFIRM_IDENTITY: "probable" (a shared number's question is the harness's own).
    confirm_reason: str | None = None
    #: Product codes this call may order, from the brief; codes in this
    #: turn's tool results are added by the before-write check itself.
    trusted_skus: frozenset[str] = frozenset()
    #: The turn's flags from intake (a request for a person, a complaint, ...).
    flags: Mapping[str, Any] = field(default_factory=dict)
    #: The products tools showed earlier in this call: ``{sku, name, price_vnd}``.
    seen_products: tuple[Mapping[str, Any], ...] = ()
    #: The orders earlier turns of this call created: ``{order_id, sku}``.
    created_orders: tuple[Mapping[str, Any], ...] = ()
    #: How an unknown customer calls themselves, and whether the agent asked.
    self_called: str | None = None
    honorific_asked: bool = False
    #: The customer's words this turn and the agent's last reply, tokenised:
    #: what the before-write checks read (a deletion needs both).
    customer_said: str | None = None
    last_agent_said: str | None = None


@dataclass
class Draft:
    """One run's result: the text, what the tools said, and what it cost."""

    text: str
    tool_results: list[dict[str, Any]]
    model: str | None
    model_calls: int
    seconds: float


class AdvisorFailure(RuntimeError):
    """A failed model must not erase tools that already executed."""

    def __init__(self, error: Exception, partial: Draft) -> None:
        super().__init__(type(error).__name__)
        self.error = error
        self.partial = partial


@dataclass(frozen=True)
class AdvisorEvent:
    """One thing a streamed run produced: a chunk of the answer, a tool round starting, its results, or the end."""

    kind: Literal["text", "tool_started", "tools", "done"]
    text: str = ""
    draft: Draft | None = None
    #: For ``tools``: every tool call of the run so far, as :attr:`Draft.tool_results` lists them.
    results: tuple[dict[str, Any], ...] = ()


#: Section 4.4, "Luật làm đúng từ đầu": every rule the organisers' documents
#: and grader make knowable is in the first release (principle 8), each
#: also enforced in code where code can (the guard, the before-write check).
#: The codes in brackets are the policy sections the rule comes from.
HARD_RULES = """\
Bạn là trợ lý ảo bán hàng của một cửa hàng Việt Nam, trả lời khách qua điện thoại hoặc tin nhắn. Xưng "em", gọi khách theo danh xưng của khách.

Nguồn sự thật:
1. Giá, khuyến mãi, tồn kho, thời gian giao, trạng thái đơn: chỉ nói con số có trong kết quả tool của lượt này (pricing_get_quote, inventory_check, delivery_estimate, order_status, order_create, order_update, account_cart, account_orders). Không nhớ, không suy, không làm tròn, không tự cộng tổng. Giá trong Call Brief là lịch sử, chỉ nói kiểu "hôm trước bên em báo"; giá hôm nay phải gọi pricing_get_quote.
2. Mã sản phẩm (sku, variant_sku) chỉ dùng mã có nguyên văn trong kết quả tool của cuộc gọi này hoặc trong Call Brief; muốn đúng size, màu thì lấy variant_sku từ catalog_search. Không tự ghép mã từ tên.
3. Chính sách đổi trả, vận chuyển, bảo hành, thanh toán, giờ làm việc: chỉ dựa vào mục "Tài liệu liên quan". Đoạn hết hiệu lực chỉ áp cho đơn tạo trước ngày chính sách đổi. Đoạn nội bộ thì từ chối, không nói gì về giá nhập, nhà cung cấp, giá sàn, biên lợi nhuận (KM-06).
4. Điều không có trong tài liệu hay kết quả tool: nói ngay "Dạ hiện em chưa có thông tin về …", không đoán, ghi nhận và hẹn phản hồi (PB-05). Không chuyển máy chỉ vì thiếu thông tin. Tool báo lỗi hoặc hết giờ (TIMEOUT): gọi lại tool đó một lần trong lượt; vẫn lỗi thì nói thật là em chưa tra được ngay lúc này và mời khách nhắn lại sau ít phút. Không trả lời kiểu "em kiểm tra rồi báo lại, anh/chị chờ chút": em chỉ trả lời khi khách nhắn, không tự nhắn lại sau được.

Cách xử lý:
5. Không bao giờ nhận là người. Khách hỏi người hay máy thì nói thật em là trợ lý ảo của shop và đề nghị chuyển nhân viên nếu khách muốn (PB-07).
6. Chỉ gọi handoff_transfer khi: câu hỏi về sức khỏe, y tế, thuốc, thai sản, an toàn của trẻ (nói "chưa có thông tin" trước rồi mới chuyển, PB-06); khách đòi gặp người; khiếu nại nghiêm trọng. Đã nói "chưa có thông tin" về câu hỏi sức khỏe hay an toàn của trẻ, hoặc khách hỏi có chuyển máy cho người khác được không: gọi handoff_transfer ngay trong lượt đó, không hỏi lại "anh có muốn chuyển không".
7. Không hỏi lại điều Call Brief đã có. Cần kiểm lại thì hỏi dạng xác nhận ("vẫn … đúng không ạ?"), mỗi thông tin xác nhận tối đa một lần trong cuộc (PB-01).
8. Khách chê đắt hoặc so giá: không bình luận, không xác nhận hay phủ nhận giá bên khác, không tự giảm giá; nêu quyền lợi có trong tool hoặc tài liệu như bảo hành, quà tặng, đổi trả (PB-02, PB-04).
9. Khách cần hỏi người nhà: không ép, đề nghị hẹn giờ gọi lại; chỉ nhắc khuyến mãi còn hiệu lực; không tạo khan hiếm giả (PB-03).
10. Khuyến mãi đã hết hạn thì nói thẳng là đã hết và báo giá hiện tại, không giữ giá cũ (KM-01). Không nhắc khuyến mãi chưa bắt đầu (KM-02).
11. Chưa gọi inventory_check thì không hứa còn hàng. Hết hàng thì không tạo đơn: nói ngày dự kiến có lại nếu tool có, gợi ý sản phẩm khác hoặc hẹn báo lại (FAQ-10, FAQ-17).
12. Khách đồng ý mua: ngay trong lượt đó gọi pricing_get_quote (đúng biến thể, số lượng, địa chỉ nếu có), delivery_estimate, rồi order_create với đúng giá cuối; câu trả lời đọc lại đơn một lần: sản phẩm, biến thể, số lượng, giá cuối, thanh toán, thời gian giao (PB-09). Thiếu địa chỉ vẫn tạo đơn được. COD quá 10.000.000đ thì đề nghị chuyển khoản hoặc tách đơn (VC-03). Khách đã nói rõ muốn đặt, chốt hoặc lên đơn (kể cả "làm ơn lên đơn", "chốt đơn cho anh", "xác nhận mua") và đã có sản phẩm cùng hình thức thanh toán: gọi order_create ngay trong lượt, không hỏi lại "muốn em đặt luôn không". Chưa có variant_sku thì tự lấy từ catalog_search, không xin khách mã. order_create trả needs_confirmation_call: true (đơn COD trên 2.000.000đ) thì nói thêm một câu: nhân viên sẽ gọi điện xác nhận đơn trước khi giao.
13. Hẹn gọi lại: callback_at theo ISO có +07:00, trong giờ làm việc, thứ Hai đến thứ Bảy 08:00–21:00, Chủ nhật 09:00–18:00 (LN-01); tool trả moved_from thì báo khách giờ mới.
14. Khách muốn xóa dữ liệu: hỏi xác nhận một câu; khách đồng ý thì gọi memory_request_deletion và nói hệ thống sẽ xóa trong 72 giờ (QT-06).
15. Danh tính chưa xác minh: không đọc giá đã báo, địa chỉ, mã đơn, không nói về lần tư vấn trước.
16. Không đọc lại đầy đủ số điện thoại, địa chỉ, CCCD, số tài khoản. Chuỗi dạng <PHONE_1>, <ADDR_1> có trong lời khách là thông tin đã che: giữ nguyên nếu cần nhắc lại, không tự tạo chuỗi như vậy. CCCD, số tài khoản không nhận qua hội thoại (PB-08, QT-04).
17. Xưng hô theo cách khách tự xưng trong cuộc; danh xưng và tên trong hồ sơ chỉ dùng khi khách chưa tự xưng. Hồ sơ và Call Brief là của người đứng tên số điện thoại hay tài khoản này: nếu lời khách cho thấy người đang nói có thể là người khác (tự xưng hoặc nói tên khác hồ sơ, nói mình là người nhà), chưa nhắc thông tin riêng trong brief cho tới khi khách xác nhận qua một câu hỏi (PB-01).
18. Khách nói đã từng mua hay được tư vấn mà em chưa có Call Brief: xin số điện thoại khách đã dùng lần trước để tra lại.
19. Gợi ý sản phẩm: đối chiếu từng nhu cầu khách đã nêu với thuộc tính (attributes) của sản phẩm trong kết quả catalog_search, như diện tích phòng (room_area_m2), nhà có trẻ nhỏ (child_safe_lock), rồi mới gợi ý. Ngân sách khách nói "tầm", "khoảng" là ước chừng: khi tìm thì nới chừng 10% thay vì đặt làm mức trần, và nói rõ phần chênh nếu mẫu hợp nhu cầu nhỉnh hơn.
20. Khách muốn đổi địa chỉ, đổi hoặc hủy "đơn đang xử lý" mà chưa nêu mã đơn: lấy từ order_status hoặc crm_get_customer; chỉ có một đơn chưa giao thì dùng luôn đơn đó, có nhiều đơn thì đọc danh sách cho khách chọn; không xin khách đọc mã đơn.
21. Khách nhắc một thông tin cũ hoặc sai (chính sách cũ, giá cũ): chỉ nói thông tin đang đúng, kèm ngày cập nhật nếu tài liệu có, không nhắc lại con số sai.
22. Khách đăng nhập tài khoản website thì có các tool account_*: hỏi giỏ hàng thì gọi account_cart, tổng tiền giỏ đọc đúng total_vnd; hỏi đơn đã đặt trên website thì gọi account_orders (mã đơn dạng #ABCD1234), đơn qua hotline/Zalo vẫn tra bằng order_status. Không có tool account_* là khách chưa đăng nhập: giỏ hàng chỉ biết qua dòng "(Giỏ hàng trên website …)" dưới lời khách nếu có; không có thì mời khách đăng nhập hoặc cho biết sản phẩm đang quan tâm.

Mỗi lượt tối đa một câu hỏi, và chỉ hỏi khi cần thông tin để làm bước kế tiếp; không kết lượt bằng câu "em có thể hỗ trợ gì thêm không ạ?" hay "anh/chị cần gì nữa không ạ?". Chưa gọi order_create thì không nói đơn đã được tạo.

Cách trả lời: tiếng Việt tự nhiên của nhân viên bán hàng, có dạ, vâng, ạ; tối đa 3 câu, trừ khi đọc lại đơn; văn xuôi, không markdown, không gạch đầu dòng. Mọi số tiền, số ngày, số tháng viết bằng chữ số: 5.200.000đ, 7 ngày, 24 tháng. Khi dùng một dòng Call Brief, đánh dấu mã dòng ngay sau ý đó, ví dụ [B2] hoặc [B2][B5]; không ghi mã tài liệu như [DT-03] vào câu trả lời."""

LANE_NOTES = {
    "CONTINUITY": (
        "Khách quen, có Call Brief. Câu đầu tiên của cuộc: chào bằng tên và danh xưng, một câu xác nhận tiếp nối "
        "nhắc tối đa ba thông tin theo thứ tự ưu tiên (đơn đã đặt kèm mã đơn, việc còn dở như cần bàn với gia đình, sản phẩm đã tư vấn) có đánh dấu [Bn], rồi hỏi khách muốn tiếp tục thế nào; "
        "không đọc vẹt cả hồ sơ. Sau đó dùng thông tin trong brief đúng lúc cần và đánh dấu [Bn]. "
        "Không hỏi mở lại: {must_not_ask}."
    ),
    "NEW": "Khách mới hoặc chưa có gì để tiếp nối. Hỏi nhu cầu còn thiếu, mỗi lượt một câu hỏi, rồi tư vấn từ catalog_search.",
    "ORDER_SERVICE": (
        "Khách hỏi về đơn đã đặt. Tra order_status; đổi size, đổi sản phẩm, trả hàng, đổi địa chỉ bằng order_update; "
        "báo đúng phí, chênh lệch, số tiền và thời gian hoàn tiền mà tool trả về. "
        "Chưa có mã đơn thì tra crm_get_customer bằng hồ sơ đã xác minh; nếu vẫn không thấy đơn, xin mã đơn, "
        "không tạo đơn mới và không đoán mã hoặc trạng thái."
    ),
    "OUT_OF_SCOPE": (
        "Câu hỏi ngoài tài liệu hoặc phải chuyển người. Câu đầu tiên là \"Dạ hiện em chưa có thông tin về …\". "
        "Câu hỏi về sức khỏe, y tế, thuốc, thai sản, an toàn của trẻ, hoặc khách muốn gặp người: gọi handoff_transfer "
        "với escalation_reason đúng. Còn lại: ghi nhận câu hỏi, hẹn phản hồi, không gọi tool."
    ),
    "CLARIFY": "Em nghe chưa rõ. Hỏi lại đúng một câu ngắn, không đoán nội dung, không gọi tool.",
    "HANDOFF": (
        "Hệ thống đang trục trặc hoặc đã phải dùng câu an toàn nhiều lần. Xin lỗi ngắn gọn rồi gọi "
        "handoff_transfer với escalation_reason loi_he_thong."
    ),
}

#: CONFIRM_IDENTITY by its reason (section 4.2): one question, nothing private before it is answered.
#: A shared number has no note: its question is the harness's fixed line, and no model is called.
CONFIRM_NOTES = {
    "probable": (
        "Khách vừa đọc một số điện thoại có trong hồ sơ nhưng chưa xác nhận. Hỏi đúng MỘT câu xác nhận về sản phẩm "
        "đã tư vấn lần trước; không nêu giá, địa chỉ, mã đơn."
    ),
}

OPENING = {
    True: (
        "Khách vừa bắt máy và chưa nói gì. Hãy mở lời trước: chào, nói rõ em là trợ lý tự động của shop, "
        "rồi xác nhận tiếp nối dựa đúng vào Call Brief (tối đa hai thông tin) và hỏi khách muốn tiếp tục "
        "thế nào. Không gọi tool ở lượt này."
    ),
    False: (
        "Khách vừa bắt máy và chưa nói gì. Hãy mở lời trước, ngắn gọn: chào, nói rõ em là trợ lý tự động "
        "của shop, hỏi khách cần hỗ trợ gì. Không gọi tool ở lượt này."
    ),
}

COPILOT_NOTE = (
    "Chế độ copilot: tư vấn viên đã nhận cuộc và sẽ gửi câu trả lời; em chỉ soạn gợi ý cho họ. Câu \"em kết "
    "nối anh/chị với đồng nghiệp\" đã nói rồi, không nói lại, không chào lại, đi thẳng vào điều khách vừa nói. "
    "Không tự gọi tool ghi (tạo đơn, hẹn gọi lại, chuyển máy): tư vấn viên làm việc đó."
)


# A message is read: an amount the customer may compare or copy is written in figures.
CHAT_NOTE = (
    "Đây là tin nhắn chat, khách đọc chứ không nghe: viết số tiền bằng chữ số có dấu chấm và đ "
    "(3.290.000đ), không viết số bằng chữ."
)

# A phone call is listened to, not read: a long answer is one the caller talks
# over, and on a laptop's speakers the echo canceller then swallows them.
SPOKEN_NOTE = (
    "Đây là cuộc gọi thoại: câu trả lời được đọc thành tiếng. Trả lời tối đa hai câu ngắn, mỗi lần một ý, "
    "không liệt kê nhiều sản phẩm một lúc, rồi dừng để khách nói. Đọc số tiền và số điện thoại tự nhiên."
)


#: Passages shown to the model per turn (section 4.2: five retrieved, three allowed in).
KNOWLEDGE_SHOWN = 3


def lane_instruction(context: AgentContext) -> str:
    """The lane's instruction with the notes ``route`` and the channel add."""
    if context.lane == "CONFIRM_IDENTITY":
        text = CONFIRM_NOTES.get(context.confirm_reason or "probable", CONFIRM_NOTES["probable"])
    else:
        text = LANE_NOTES.get(context.lane, "").format(must_not_ask=", ".join(context.must_not_ask) or "không có")
    extra = list(context.notes)
    if context.mode == "copilot":
        extra.append(COPILOT_NOTE)
    if context.channel == "hotline":
        extra.append(SPOKEN_NOTE)
    else:
        extra.append(CHAT_NOTE)
    return "\n".join([text, *extra]).strip()


def system_prompt(context: AgentContext, *, max_tokens: int = 3000) -> tuple[str, tuple[str, ...]]:
    """The system message in section 4.4's order, and the sections that were cut.

    1 rules, 2 warnings (both never cut), 3 the lane, 4 the brief lines the
    tier allows, 5 the summary of older turns (the last four travel as
    messages), 6 the turn's knowledge passages, 7 the playbook entries of the
    situation, 8 tool results already gathered (a regeneration), 9 why the
    previous draft was blocked. Required evidence survives the soft budget;
    optional sections are admitted in priority order.
    """
    brief = "\n".join(f"{line.id}. {line.text}" for line in context.brief_lines)
    policy, playbook = shown_passages(context.knowledge)
    sections = [
        Section("rules", HARD_RULES),
        Section("warnings", "\n".join(f"CẢNH BÁO: {w}" for w in context.warnings)),
        Section("lane", (
            f"Lane: {context.lane}. Mức xác minh danh tính: {context.tier}. Kênh: {context.channel}."
            + (f" Hồ sơ đứng tên: {context.address_as}." if context.address_as else _address_note(context))
            + f"\n{lane_instruction(context)}"
        ).strip()),
        Section("products", _products_block(context.seen_products)),
        Section("orders", _orders_block(context.created_orders)),
        Section("brief", f"Call Brief:\n{brief}" if brief else ""),
        Section("summary", f"Tóm tắt các lượt trước:\n{context.working_summary}" if context.working_summary else ""),
        Section("knowledge", _knowledge_block("Tài liệu liên quan", policy) or context.knowledge_note or ""),
        Section("playbook", _knowledge_block("Kinh nghiệm xử lý đã được duyệt", playbook)),
        Section("tool_results", _tool_block(context.tool_results)),
        Section("opening", OPENING[bool(context.brief_lines)] if context.phase == "opening" else ""),
        Section("blocked", _blocked_block(context)),
    ]
    pack = assemble(sections, max_tokens=max_tokens)
    return pack.text, pack.cut


def shown_passages(knowledge: Sequence[Mapping[str, Any]]) -> tuple[list[Mapping[str, Any]], list[Mapping[str, Any]]]:
    """What the model reads of a turn's passages: the first three from the documents, and the playbook entries.

    The guard checks a reply against these and no others: a number from a
    passage the model never saw cannot be a number it read (section 4.5).
    """
    policy = [p for p in knowledge if p.get("source") != "playbook"][:KNOWLEDGE_SHOWN]
    playbook = [p for p in knowledge if p.get("source") == "playbook"]
    return policy, playbook


def _knowledge_block(heading: str, passages: Sequence[Mapping[str, Any]]) -> str:
    """Passages as the model reads them: a restricted one as a refusal, a superseded one with its dates."""
    if not passages:
        return ""
    lines = []
    for passage in passages:
        code = passage.get("chunk_id") or "?"
        title = passage.get("title") or ""
        if passage.get("restricted"):
            lines.append(passage.get("instruction") or f"Đoạn [{code}] là thông tin nội bộ: không đọc, không trích.")
            continue
        validity = f" (đoạn này {passage['validity']})" if passage.get("superseded") and passage.get("validity") else ""
        lines.append(f"[{code}] {title}{validity}: {str(passage.get('text') or '').strip()}")
    return f"{heading}:\n" + "\n".join(lines)


def _address_note(context: AgentContext) -> str:
    """How to address a customer the shop does not know yet."""
    if context.self_called:
        return f" Khách tự xưng là {context.self_called}: gọi khách là {context.self_called}, xưng em, dùng nhất quán."
    if context.honorific_asked:
        return " Chưa biết danh xưng và em đã hỏi rồi: gọi anh/chị, không hỏi lại."
    return (" Chưa biết danh xưng: tạm gọi anh/chị. Ở lượt thứ hai, hoặc khi xin thông tin đặt hàng, hỏi đúng một lần, "
            "gộp vào câu hỏi đang cần hỏi: \"Dạ cho em hỏi mình xưng hô là anh hay chị ạ?\"")


def _blocked_block(context: AgentContext) -> str:
    """Why the last draft was blocked, and when part of the answer was already said, what to go on from."""
    if not context.block_reasons:
        return ""
    reasons = "; ".join(context.block_reasons)
    if context.already_said:
        return (f"Khách đã nghe em nói: «{' '.join(context.already_said)}». Câu tiếp theo của em bị chặn vì: {reasons} "
                "Nói tiếp phần còn lại của câu trả lời, không lặp lại phần khách đã nghe; cần tool thì gọi trước khi nói.")
    return f"Câu trả lời trước của em đã bị chặn vì: {reasons} Hãy soạn lại, tránh đúng những điểm đó."


def _orders_block(orders: Sequence[Mapping[str, Any]]) -> str:
    """The orders this call created: a later address or payment corrects them, it is not a new order."""
    if not orders:
        return ""
    lines = [f"- {o['order_id']}" + (f": {o['sku']}" if o.get("sku") else "") for o in orders]
    return ("Đơn đã tạo trong cuộc này (khách bổ sung địa chỉ, đổi thanh toán thì gọi order_update trên đơn đó, "
            "không tạo đơn mới):\n" + "\n".join(lines))


def _products_block(products: Sequence[Mapping[str, Any]]) -> str:
    """The products tools showed earlier in this call, with their codes: what a later turn quotes and orders."""
    if not products:
        return ""
    lines = [f"- {p['sku']}: {p.get('name') or '?'}" + (f", {format_vnd(int(p['price_vnd']))}" if p.get("price_vnd") else "")
             for p in products]
    return ("Sản phẩm đã tra trong cuộc này (mã chính xác: báo giá, kiểm kho, đặt đơn dùng đúng mã này; "
            "giá ở đây có thể đã cũ, đặt đơn vẫn gọi pricing_get_quote):\n" + "\n".join(lines))


def _tool_block(results: Sequence[Mapping[str, Any]]) -> str:
    if not results:
        return ""
    lines = [f"- {r['name']}({json.dumps(r.get('args') or {}, ensure_ascii=False)}) -> "
             f"{json.dumps(r.get('result'), ensure_ascii=False)}" for r in results]
    return "Kết quả tool đã có trong lượt này (dùng lại, không cần gọi lại):\n" + "\n".join(lines)


class ContextPromptMiddleware(AgentMiddleware):
    """The system message for each model call, built from the run's context.

    Both hooks are implemented on purpose: the framework does not derive one
    from the other, and the service is async.
    """

    def __init__(self, model_limit: int = 8) -> None:
        super().__init__()
        self.model_limit = model_limit

    def _with_prompt(self, request: ModelRequest) -> ModelRequest:
        context = getattr(getattr(request, "runtime", None), "context", None)
        if not isinstance(context, AgentContext):
            return request
        prompt, _ = system_prompt(context)
        prompt = pii.tokenise(prompt, context.vault)
        if request.state.get("run_model_call_count", 0) >= self.model_limit - 1:
            prompt += ("\nĐây là lượt model cuối: không gọi thêm tool. Trả lời ngắn từ kết quả đã có; "
                       "thiếu dữ liệu thì nói chưa kiểm tra được và xin đúng thông tin còn thiếu. "
                       "Không khẳng định thao tác thành công nếu chưa có kết quả tool thành công.")
            return request.override(system_message=SystemMessage(content=prompt), tools=[])
        return request.override(system_message=SystemMessage(content=prompt))

    def wrap_model_call(self, request: ModelRequest, handler: Any) -> Any:
        return handler(self._with_prompt(request))

    async def awrap_model_call(self, request: ModelRequest, handler: Any) -> Any:
        return await handler(self._with_prompt(request))


class ActionGuardMiddleware(AgentMiddleware):
    """The guardrail before act (section 4.4): a write tool runs only if its arguments pass."""

    async def awrap_tool_call(self, request: Any, handler: Any) -> Any:
        call = request.tool_call
        name = call["name"]
        if name not in actions.WRITE_TOOLS | actions.SKU_READ_TOOLS | actions.CUSTOMER_READ_TOOLS:
            return await handler(request)
        context = getattr(getattr(request, "runtime", None), "context", None)
        if not isinstance(context, AgentContext):
            return ToolMessage(content=json.dumps({"ok": False, "error": {"code": "PRECONDITION",
                "retryable": False, "message": "Missing trusted runtime context."}}),
                tool_call_id=call["id"], name=name, additional_kwargs={"blocked_by": "guardrail"})
        args = dict(call.get("args") or {})
        if name == "handoff_transfer":
            args["brief"] = actions.fill_handoff(args.get("brief") or {}, context.handoff_defaults)
        state = getattr(request, "state", None) or {}
        quotes = {**context.quotes, **_quotes_in(state)}
        codes, orders = _seen_in(state, context.tool_results)
        verdict = actions.check(
            name, args, tier=context.tier, mode=context.mode, has_phone=bool(context.customer_phone),
            quotes=quotes, orders=context.known_orders | orders, trusted=context.trusted_skus | codes | set(quotes),
            lane=context.lane, flags=context.flags, now=context.now,
            last_agent_said=context.last_agent_said, customer_said=context.customer_said,
            shared_phone=context.shared_phone, created=(*context.created_orders, *_created_in(state)),
        )
        if not verdict.passed:
            envelope = {"ok": False, "error": {"code": "PRECONDITION", "retryable": False, "message": " ".join(verdict.reasons)}}
            return ToolMessage(
                content=json.dumps(envelope, ensure_ascii=False), tool_call_id=call["id"], name=name,
                additional_kwargs={"args": args, "blocked_by": "guardrail"},
            )
        return await handler(request.override(tool_call={**call, "args": args}))


def _seen_in(state: Mapping[str, Any], earlier: Sequence[Mapping[str, Any]]) -> tuple[frozenset[str], frozenset[str]]:
    """Product codes and order ids the tools showed in this run and earlier in this turn: what may be acted on."""
    envelopes = [envelope_of(m) for m in state.get("messages") or [] if isinstance(m, ToolMessage)]
    envelopes += [r.get("result") for r in earlier]
    codes: set[str] = set()
    orders: set[str] = set()

    def walk(value: Any) -> None:
        if isinstance(value, dict):
            for key in ("sku", "variant_sku", "successor_sku", "new_variant_sku"):
                if isinstance(value.get(key), str):
                    codes.add(value[key])
            if isinstance(value.get("order_id"), str):
                orders.add(value["order_id"])
            for item in value.values():
                walk(item)
        elif isinstance(value, list):
            for item in value:
                walk(item)

    for envelope in envelopes:
        if isinstance(envelope, dict) and envelope.get("ok"):
            walk(envelope.get("data"))
    return frozenset(codes), frozenset(orders)


def _created_in(state: Mapping[str, Any]) -> list[dict[str, Any]]:
    """The orders ``order_create`` made earlier in this run, ``{order_id, sku}``, the sku from the call's arguments."""
    asked = {call["id"]: call.get("args") or {} for m in state.get("messages") or [] if isinstance(m, AIMessage)
             for call in m.tool_calls if call.get("name") == "order_create"}
    created = []
    for message in state.get("messages") or []:
        if isinstance(message, ToolMessage) and message.name == "order_create":
            envelope = envelope_of(message)
            data = envelope.get("data") if isinstance(envelope, dict) and envelope.get("ok") else None
            if isinstance(data, dict) and data.get("order_id"):
                created.append({"order_id": data["order_id"], "sku": asked.get(message.tool_call_id, {}).get("sku")})
    return created


def _quotes_in(state: Mapping[str, Any]) -> dict[str, int]:
    """Today's price per sku from the pricing results already in this run."""
    quotes: dict[str, int] = {}
    for message in state.get("messages") or []:
        if isinstance(message, ToolMessage) and message.name == "pricing_get_quote":
            envelope = envelope_of(message) or {}
            data = envelope.get("data") or {}
            if envelope.get("ok") and data.get("sku") and data.get("final_price_vnd") is not None:
                quotes[data["sku"]] = int(data["final_price_vnd"])
    return quotes


class AdvisorAgent(BaseAgent):
    """Drafts the reply for one turn, from the slice of state it is given."""

    #: Four items need catalogue, quote, stock and order each, plus delivery.
    TOOL_CALLS_PER_RUN = 20
    MODEL_CALLS_PER_RUN = 8

    def __init__(
        self,
        *,
        provider: str | None = None,
        model: str | None = None,
        tools: Sequence[BaseTool] | None = None,
        generation: Mapping[str, Any] | None = None,
        retries: int = 1,
        llm: BaseChatModel | None = None,
    ) -> None:
        """``retries`` is the one retry of a failed model call and of a
        retryable tool failure (sections 4.9 and 6.1). An evaluation harness
        that must see every attempt sets it to 0. ``llm`` replaces the model
        from config, for offline tests."""
        super().__init__("advisor", provider=provider, model=model, generation=generation, llm=llm)
        self._tools = list(tools or ())
        names = [tool.name for tool in self._tools]
        retry = [ModelRetryMiddleware(max_retries=retries, initial_delay=1.0, on_failure="error")] if retries else []
        self._graph = create_agent(
            model=self.llm,
            tools=self._tools,
            middleware=[
                ContextPromptMiddleware(self.MODEL_CALLS_PER_RUN),
                *retry,
                ModelCallLimitMiddleware(run_limit=self.MODEL_CALLS_PER_RUN, exit_behavior="error"),
                ToolCallLimitMiddleware(run_limit=self.TOOL_CALLS_PER_RUN, exit_behavior="continue"),
                LaneToolsMiddleware(get_lanes(), names),
                ActionGuardMiddleware(),
                ToolGuardMiddleware(names, retries=retries),
            ],
            context_schema=AgentContext,
            name=self.name,
        )
        logger.info("Agent '%s' ready on %s | tools: %s", self.name, self.model_name, names or "none")

    @property
    def tool_names(self) -> list[str]:
        return [tool.name for tool in self._tools]

    def run_config(self, context: AgentContext, *, user_id: str | None = None) -> RunnableConfig:
        """Per-run config: trace callback and metadata. No thread: nothing persists here."""
        config: RunnableConfig = {"run_name": self.name}
        config["metadata"] = tracing.trace_metadata(
            session_id=context.customer_id or context.call_id,
            user_id=user_id,
            tags=[self.name, context.lane, context.mode],
            agent=self.name,
            call_id=context.call_id,
            tier=context.tier,
            lane=context.lane,
            mode=context.mode,
            switches=dict(context.switches),
        )
        if (handler := tracing.handler()) is not None:
            config["callbacks"] = [handler]
        return config

    async def draft(self, messages: list[Any], context: AgentContext, *, user_id: str | None = None) -> Draft:
        """Run the loop once over *messages* and return the draft."""
        async for event in self.stream(messages, context, user_id=user_id):
            if event.kind == "done":
                return event.draft
        raise RuntimeError("Advisor stream ended without a draft")

    async def stream(
        self, messages: list[Any], context: AgentContext, *, user_id: str | None = None
    ) -> AsyncIterator[AdvisorEvent]:
        """Run the loop once over *messages*, yielding the answer as it is written.

        Text arrives in chunks from the model node; a model call that turns
        out to call tools says so with ``tool_started``, once per call, and
        ``tools`` follows when they have answered, with every result so far,
        so a sentence can be checked against them before the run ends. The
        last event is ``done`` with the whole :class:`Draft`, as :meth:`draft`
        would return it. Closing the iterator early stops the run: that is how
        the harness abandons a draft whose sentence the guard blocked
        (section 4.8).
        """
        started = time.perf_counter()
        produced: list[Any] = []
        announced: set[str] = set()
        try:
            async for mode, chunk in self._graph.astream(
                {"messages": messages}, config=self.run_config(context, user_id=user_id), context=context,
                stream_mode=["messages", "updates"],
            ):
                if mode == "updates":
                    fresh = [m for update in chunk.values() if isinstance(update, dict) for m in update.get("messages") or []]
                    produced.extend(fresh)
                    if any(isinstance(m, ToolMessage) for m in fresh):
                        yield AdvisorEvent("tools", results=tuple(tool_results_of(produced)))
                    continue
                message, meta = chunk
                # A model that streams sends chunks; one that does not sends its
                # whole message once, which is a chunk's parent class.
                if meta.get("langgraph_node") != "model" or not isinstance(message, AIMessage):
                    continue
                calls = message.tool_call_chunks if isinstance(message, AIMessageChunk) else message.tool_calls
                if calls:
                    if message.id not in announced:
                        announced.add(message.id or "")
                        yield AdvisorEvent("tool_started")
                    continue
                text = text_of(message, strip=False)
                if text:
                    yield AdvisorEvent("text", text=text)
        except Exception as error:
            raise AdvisorFailure(error, self._draft_of(produced, started)) from error
        yield AdvisorEvent("done", draft=self._draft_of(produced, started))

    def _draft_of(self, produced: Sequence[Any], started: float) -> Draft:
        return Draft(
            text=_final_text(produced),
            tool_results=tool_results_of(produced),
            model=self.model_name,
            model_calls=sum(1 for m in produced if isinstance(m, AIMessage)),
            seconds=time.perf_counter() - started,
        )


def _final_text(produced: Sequence[Any]) -> str:
    for message in reversed(produced):
        if isinstance(message, AIMessage) and not message.tool_calls:
            return text_of(message).strip()
    return ""


def tool_results_of(produced: Sequence[Any]) -> list[dict[str, Any]]:
    """Every tool call of the run: organisers' name, the arguments it ran with, the envelope."""
    answers = {m.tool_call_id: m for m in produced if isinstance(m, ToolMessage)}
    results = []
    for message in produced:
        if not isinstance(message, AIMessage):
            continue
        for call in message.tool_calls:
            answer = answers.get(call["id"])
            envelope = parse_envelope(answer.content) if answer is not None else None
            blocked_by = answer.additional_kwargs.get("blocked_by") if answer is not None else None
            if answer is None:
                envelope = {"ok": False, "error": {"code": "TOOL_RESULT_MISSING", "retryable": False,
                                                   "message": "No result received; execution outcome is unknown."}}
                blocked_by = "missing_result"
            if (answer is not None and answer.status == "error" and isinstance(answer.content, str)
                    and answer.content.startswith("Tool call limit exceeded.")):
                envelope = {"ok": False, "error": {"code": "TOOL_CALL_LIMIT", "retryable": False,
                                                   "message": answer.content}}
                blocked_by = "framework"
            results.append({
                "name": dotted(call["name"]),
                "args": (answer.additional_kwargs.get("args") if answer is not None else None) or call["args"],
                "result": envelope,
                "blocked_by": blocked_by,
            })
    return results
