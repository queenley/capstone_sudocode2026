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
