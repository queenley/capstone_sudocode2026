"""Entities read from recognised text."""
from src.asr.entities import extract


def test_numbers_said_as_words_become_entities():
    assert extract("chị nhớ là phòng mình khoảng hai mươi lăm mét vuông không có trẻ nhỏ đâu") == {
        "room_area_m2": 25, "has_children": False}
    assert extract("ngân sách chị chỉ có năm triệu thôi") == {"budget_vnd": 5_000_000}


def test_payment_and_price():
    assert extract("chị muốn thanh toán cod và giao hàng ở cầu giấy")["payment"] == "COD"
    assert extract("giá bốn triệu tám trăm chín mươi nghìn đồng")["price_vnd"] == 4_890_000


def test_a_sentence_without_entities_gives_none():
    assert extract("alo chị oanh đây em ơi") == {}
