"""scenario-commerce-v11: values the organisers' ASR sample labels that the extractor used to omit.

Synthetic sentences; each case is a family (other numbers, other wordings), not one dataset sentence.
"""
import pytest

from ai_agent_service.components.intake import commerce as module


@pytest.mark.parametrize('text, area', [
    ('phòng hai mươi lăm mét', 25), ('phòng ngủ khoảng mười tám mét', 18), ('diện tích tầm ba mươi mét', 30),
    ('phòng chị rộng 40 m', 40), ('phòng khách 35 mét vuông', 35),
])
def test_room_area_without_vuong(text, area):
    assert module.commerce(text).get('room_area_m2') == area


@pytest.mark.parametrize('text', ['cái bàn dài hai mét', 'phòng cao ba mét', 'dây dài 5 mét'])
def test_lengths_are_not_room_areas(text):
    assert 'room_area_m2' not in module.commerce(text)


@pytest.mark.parametrize('text, days', [
    ('giao nội thành một đến hai ngày làm việc', 2), ('giao trong 2-3 ngày', 3), ('ship từ ba đến năm ngày', 5),
    ('nhận được hàng sau bốn ngày', 4),
])
def test_delivery_days_and_ranges(text, days):
    assert module.commerce(text).get('delivery_days') == days


@pytest.mark.parametrize('text, fee', [
    ('hàng cồng kềnh ngoài nội thành phụ thu ba mươi nghìn thôi ạ', 30000),
    ('hàng cồng kềnh tính thêm bốn mươi nghìn', 40000),
])
def test_bulky_surcharge(text, fee):
    assert module.commerce(text).get('bulky_fee_vnd') == fee


@pytest.mark.parametrize('text, old', [
    ('chị mới nhận giày mà size bốn mươi hơi chật', 40), ('size 42 bị rộng quá em ạ', 42), ('cỡ m không vừa', 'M'),
])
def test_a_size_that_does_not_fit_is_the_old_one(text, old):
    assert module.commerce(text).get('size_old') == old


def test_a_change_of_size_spans_clauses_and_turns():
    found = module.commerce('đôi size 40 màu đen, chị muốn đổi lên size 41')
    assert (found['size_old'], found['size_new']) == (40, 41)
    assert 'size_new' not in module.commerce('không đổi size 46 sang 47')
    turns = [('size bốn mươi hơi chật', None, 'C'), ('ừ đổi lên bốn mươi mốt nhé', None, 'C')]
    assert [o['asr_entities'].get('size_new') for o in module.observe_turns(turns)] == [None, 41]
    dialogue = module.observe_dialogue('size bốn mươi hơi chật.\nđôi size bốn mươi màu đen.\nừ đổi lên bốn mươi mốt nhé.')
    assert {k: dialogue['asr_entities'][k] for k in ('size_old', 'size_new')} == {'size_old': 40, 'size_new': 41}


def test_a_rise_that_is_not_a_size_change_is_not_a_size():
    assert 'size_new' not in module.commerce('giá lên 41 nghìn rồi')


def test_hesitation_after_a_price_comparison_is_the_comparison():
    turns = [('bên kia bán có năm triệu bảy thôi', None, 'C'), ('để anh cân nhắc thêm rồi báo lại', None, 'C')]
    assert module.observe_turns(turns)[1]['asr_entities']['blocker'] == 'so sanh gia'
    text = 'bên kia bán có năm triệu bảy thôi.\nđể anh cân nhắc thêm rồi báo lại.'
    assert module.observe_dialogue(text)['asr_entities']['blocker'] == 'so sanh gia'
    assert module.commerce('để anh cân nhắc thêm rồi báo lại')['blocker'] == 'can suy nghi them'
