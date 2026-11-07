"""Independent utterances: monetary roles and corrections without labels/catalogue facts."""
from datetime import datetime

import pytest

from ai_agent_service.components.intake import commerce, itn


def money(text):
    found, role = {}, None
    written = itn.normalise(text.lower(), datetime(2041, 4, 17))
    for clause in commerce._clauses(written):
        role = commerce._money(clause, found, role)
    return found


@pytest.mark.parametrize(('text', 'expected'), [
    ('Ngân sách không phải 8 triệu mà là 6 triệu.', {'budget_vnd': 6_000_000}),
    ('Ngân sách không phải 8tr mà 6tr.', {'budget_vnd': 6_000_000}),
    ('Ngân sách 8 triệu, à không 6 triệu.', {'budget_vnd': 6_000_000}),
    ('Ngân sách 8tr à không 6tr.', {'budget_vnd': 6_000_000}),
    ('Giá bán 5 triệu, giảm còn 4 triệu.', {'price_vnd': 4_000_000}),
    ('Ngân sách không phải 8 triệu.', {}),
    ('Giá 5 triệu không phải 4 triệu.', {'price_vnd': 5_000_000}),
    ('Giá rẻ hơn 200 nghìn đồng.', {}),
    ('Chỗ khác báo giá thấp hơn 200 nghìn đồng.', {}),
    ('Giá giảm 200 nghìn đồng.', {}),
    ('Giá 5 triệu giảm 200 nghìn đồng.', {'price_vnd': 5_000_000}),
    ('Ngân sách linh hoạt giá bán là 7 triệu.', {'price_vnd': 7_000_000}),
    ('Chỗ khác báo giá 7 triệu.', {'competitor_price_vnd': 7_000_000}),
    ('Giá chỗ khác là 7 triệu.', {'competitor_price_vnd': 7_000_000}),
    ('Bên kia ngân sách 8 triệu giá bán 7 triệu.', {'budget_vnd': 8_000_000, 'price_vnd': 7_000_000}),
    ('Ngân sách 8 triệu, chiếc máy nặng 6 triệu.', {'budget_vnd': 8_000_000}),
    ('Ngân sách 8 triệu, mà tiền thuê nhà 6 triệu.', {'budget_vnd': 8_000_000}),
    ('Nếu giá 5 triệu thì tôi mua.', {}),
    ('Chưa chắc giá 5 triệu.', {}),
    ('Giá hơn 5 triệu.', {}),
    ('Ngân sách tối đa 5 triệu.', {'budget_vnd': 5_000_000}),
])
def test_money_roles_corrections_and_negative_controls(text, expected):
    assert money(text) == expected


@pytest.mark.parametrize('text', [
    'Ngân sách từ 4 đến 6 triệu.',
    'Ngân sách từ 4 triệu đến 6 triệu.',
    'Giá 4 triệu tới 6 triệu.',
    'Giá từ bốn triệu đến sáu triệu.',
    'Giá 4 triệu hoặc 6 triệu tùy cấu hình.',
    'Giá 4–6 triệu.',
    'Giá 4 triệu đến 6.',
])
def test_range_and_alternative_are_not_exact_scalars(text):
    assert money(text) == {}


@pytest.mark.parametrize(('text', 'expected'), [
    ('Phí đổi hàng miễn phí.', {'exchange_fee_vnd': 0}),
    ('Miễn phí đổi hàng.', {'exchange_fee_vnd': 0}),
    ('Không thu phí đổi hàng.', {'exchange_fee_vnd': 0}),
    ('Phí đổi hàng không miễn phí.', {}),
    ('Phí đổi hàng không được miễn phí.', {}),
    ('Phí đổi hàng miễn phí nếu là hội viên.', {}),
    ('Phí đổi hàng 50 nghìn và miễn phí vận chuyển.', {'exchange_fee_vnd': 50_000}),
    ('Phí đổi hàng 0 đồng.', {'exchange_fee_vnd': 0}),
    ('Phí hàng cồng kềnh 90 nghìn.', {'bulky_fee_vnd': 90_000}),
    ('Đơn từ 850 nghìn được miễn phí giao hàng.', {'min_free_ship_vnd': 850_000}),
    ('Hoàn lại 175 nghìn.', {'refund_vnd': 175_000}),
])
def test_fees_and_refunds_remain_local_to_their_role(text, expected):
    assert money(text) == expected


def test_legacy_two_argument_money_call_remains_valid():
    found = {}
    assert commerce._money('giá 5000000đ', found) == 'price_vnd'
    assert found == {'price_vnd': 5_000_000}


def test_unqualified_amount_requires_explicit_correction_to_inherit_role():
    found = {'budget_vnd': 8_000_000}
    commerce._money('phí lắp đặt 6000000đ', found, 'budget_vnd')
    assert found == {'budget_vnd': 8_000_000}
    commerce._money('à không 6000000đ', found, 'budget_vnd')
    assert found == {'budget_vnd': 6_000_000}


def test_unrelated_clause_clears_pending_correction_role():
    found = {'budget_vnd': 8_000_000}
    role = commerce._money('tôi đang xem màu xanh', found, 'budget_vnd')
    assert role is None
    commerce._money('à không 6000000đ', found, role)
    assert found == {'budget_vnd': 8_000_000}
    assert commerce._money('tiền thuê nhà 6000000đ', found, 'budget_vnd') is None


# scenario-commerce-v6: money said the way the seed-dev customers say it (synthetic sentences, not dataset text).
import pytest as _pytest
from ai_agent_service.components.intake import commerce as _commerce


@_pytest.mark.parametrize("text, field, value", [
    ("chị có bốn triệu hai trăm nghìn ngân sách thôi", "budget_vnd", 4200000),
    ("ngân sách giờ anh có thể lên đến chín triệu rưỡi", "budget_vnd", 9500000),
    ("cô cần máy cho cả nhà tầm năm triệu thôi", "budget_vnd", 5000000),
    ("em thấy trên mạng có chỗ bán hai triệu ba trăm ngàn", "competitor_price_vnd", 2300000),
    ("bên ngoài ghi giá một triệu một trăm nghìn sao bên mình lại một triệu hai trăm nghìn", "price_vnd", 1200000),
    ("bên ngoài ghi giá một triệu một trăm nghìn sao bên mình lại một triệu hai trăm nghìn", "competitor_price_vnd", 1100000),
    ("bên khác bán ba triệu, mà bên em lại ba triệu hai trăm", "price_vnd", 3200000),
    ("hôm trước em báo hai triệu mà hôm nay lại là hai triệu bốn trăm", "price_vnd", 2400000),
    ("hôm trước thấy em báo là ba triệu sáu nhỉ", "price_vnd", 3600000),
])
def test_v6_money_cues(text, field, value):
    assert _commerce.observe(text, speaker="customer")["asr_entities"].get(field) == value


def test_v6_a_competitor_price_with_thoi_is_not_a_budget():
    found = _commerce.observe("anh thấy bên khác họ bán chỉ có hai triệu một trăm thôi", speaker="customer")["asr_entities"]
    assert found.get("competitor_price_vnd") == 2100000 and "budget_vnd" not in found


# ITN and extraction, scenario-commerce-v7: typed abbreviations, spoken decimals, toneless amounts, identifiers.
from ai_agent_service.components.intake import itn as _itn


@_pytest.mark.parametrize("text, value", [
    ("năm tr ba", 5_300_000), ("bảy tr hai", 7_200_000), ("chín tr", 9_000_000),
    ("1m2", 1_200_000), ("3m5", 3_500_000), ("500k", 500_000), ("năm trăm k", 500_000),
    ("một chấm năm triệu", 1_500_000), ("hai phẩy năm củ", 2_500_000), ("ba chấm hai lăm triệu", 3_250_000),
    ("mười hai chấm năm triệu", 12_500_000),
    ("nam trieu ba", 5_300_000), ("sau trieu ruoi", 6_500_000), ("bay tram nam muoi nghin", 750_000),
    ("mot cham nam trieu", 1_500_000), ("tu nam trieu", 5_000_000),
])
def test_v7_amounts_with_any_digits(text, value):
    assert _itn.amounts(text) == [value]


@_pytest.mark.parametrize("text", ["bảy trăm năm", "phòng 4m", "5m", "chín sáu phẩy hai l", "nam nay", "em cham soc khach"])
def test_v7_ambiguous_or_non_money_stays_unread(text):
    assert _itn.amounts(text) == []


def test_v7_total_paid_and_identifiers_are_their_own_fields():
    seen = lambda text: _commerce.observe(text, speaker="customer")["asr_entities"]
    assert seen("chốt đơn với tổng tiền là bốn triệu một trăm nghìn")["total_vnd"] == 4_100_000
    paid = seen("đợt trước chị mua là ba triệu hai trăm ngàn giờ có giảm không")
    assert paid.get("paid_price_vnd") == 3_200_000 and "competitor_price_vnd" not in paid
    card = seen("số c c c d của anh là không ba một hai ba bốn năm sáu bảy tám chín không")
    assert card.get("id_number") == "031234567890" and "phone" not in card
    account = seen("anh đọc số tài khoản ngân hàng để nhận hoàn tiền là một hai ba bốn năm sáu bảy tám chín")
    assert account.get("bank_account") == "123456789" and "phone" not in account
    assert seen("số điện thoại của chị là không chín không tám một hai ba bốn năm sáu")["phone"] == "0908123456"


def test_v7_two_products_two_prices_keep_the_chosen_products_price():
    found = _commerce.observe("AirPure X giá bốn triệu tám trăm còn AirPure Y giá năm triệu hai trăm chị lấy AirPure Y nhé",
                              speaker="customer")["asr_entities"]
    assert found.get("sku") == "SKU-AP-Y" and found.get("price_vnd") == 5_200_000
