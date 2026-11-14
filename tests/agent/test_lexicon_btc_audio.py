"""Lexicon corrections heard on the organisers' D01 and D04 audio: "ngân sách" written "nâng sát", "còn hàng" written
"còn hàn".

Synthetic sentences, not the organisers' sentences; the misheard spellings are the recogniser's own.
"""
import pytest

from ai_agent_service.components.intake import commerce as module
from ai_agent_service.components.intake.lexicon import correct


def test_a_budget_the_recogniser_wrote_nang_sat():
    text = correct('nhà anh có bé ba tuổi nâng sát tầm bốn triệu thôi em')
    assert 'ngân sách tầm bốn triệu' in text
    assert module.commerce(text).get('budget_vnd') == 4000000


def test_in_stock_the_recogniser_wrote_con_han():
    text = correct('dạ size bốn mươi hai màu trắng còn hàn ạ')
    assert text.endswith('còn hàng ạ')
    assert module.commerce(text).get('in_stock') is True


@pytest.mark.parametrize('heard, field, value', [
    ('chị hỏi máy lọc không khí mẫu ep x', 'sku', 'SKU-AP-X'),
    ('chị hỏi máy lọc không khí mẫu EPIX', 'sku', 'SKU-AP-X'),
    ('em gợi ý mẫu aipai có khóa trẻ em', 'sku', 'SKU-AP-Y'),
    ('em gợi ý mẫu EPIE có khóa trẻ em', 'sku', 'SKU-AP-Y'),
    ('máy lọc không khí epi pro giá bao nhiêu', 'sku', 'SKU-AP-PRO'),
    ('anh hỏi máy lọc nước carophy chín lõi', 'sku', 'SKU-WF-RO9'),
    ('anh hỏi máy lọc nước carofy chín lõi', 'sku', 'SKU-WF-RO9'),
    ('chị đổi giày trung lai hai pro size bốn mốt', 'sku', 'SKU-SN-RUN2'),
    ('chị đổi giày rung lai hai pro size bốn mốt', 'sku', 'SKU-SN-RUN2'),
    ('giao về nhà thanh toán ko d nhé', 'payment', 'COD'),
    ('giao về nhà thanh toán KOD nhé', 'payment', 'COD'),
    ('giao về nhà thanh toán kê ô đê nhé', 'payment', 'COD'),
])
def test_names_the_organisers_read_as_vietnamese_spells_them(heard, field, value):
    # "e pia y", "ka rô phi", "cê ô đê", "run lai" as the recognisers wrote them on the organisers' audio.
    assert module.commerce(correct(heard)).get(field) == value


def test_a_name_without_its_model_letter_gives_the_brand_only():
    assert correct('tư vấn chị mẫu aipr cho phòng ngủ') == 'tư vấn chị mẫu AirPure cho phòng ngủ'


def test_words_already_right_are_left_alone():
    for text in ['ngân sách tầm năm triệu', 'dạ còn hàng ạ', 'chị nâng sáu cái thùng', 'còn hàng hàn quốc không em',
                 'trung tâm bảo hành', 'con lai', 'ko được đâu em', 'em kiểm tra cho chị']:
        assert correct(text) == text
