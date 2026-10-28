"""Spoken numbers to written (components/intake/itn.py), as a recogniser hands them over: no punctuation."""
from datetime import datetime

import pytest

from ai_agent_service.components.intake import itn

NOW = datetime(2026, 1, 1)


@pytest.mark.parametrize("said, written", [
    ("bốn triệu tám", "4.800.000đ"),
    ("hai trăm bốn chín k", "249.000đ"),
    ("một củ hai", "1.200.000đ"),
    ("hai triệu rưỡi", "2.500.000đ"),
    ("năm triệu hai trăm nghìn", "5.200.000đ"),
    ("hai triệu không trăm năm mươi nghìn", "2.050.000đ"),
])
def test_money(said, written):
    assert itn.normalise(said, NOW) == written


@pytest.mark.parametrize("said, written", [
    ("số không chín tám bốn một hai ba bốn năm sáu", "số 0984123456"),
    ("số của anh là không chín một bảy hai hai ba bốn năm sáu", "số của anh là 0917223456"),
    ("hai không hai sáu", "2026"),
    ("mã ô đê ba trăm mười hai nghìn bốn trăm năm mươi sáu", "mã OD312456"),
])
def test_digit_strings_and_order_codes(said, written):
    assert itn.normalise(said, NOW) == written


@pytest.mark.parametrize("said, written", [
    # Found by the ASR evaluation (the ASR evaluation, asr-team-v2): "không" after a number was read as a zero.
    ("chỗ khác là bốn triệu tám không biết có giảm được không", "chỗ khác là 4.800.000đ không biết có giảm được không"),
    ("giá năm triệu hai không em", "giá 5.200.000đ không em"),
    ("còn năm triệu không", "còn 5.000.000đ không"),
    ("hai triệu rưỡi không chị", "2.500.000đ không chị"),
    ("còn tám không em", "còn 8 không em"),
    # "mốt" only counts ("bốn mốt" is 41): never a digit of a phone number.
    ("size bốn mốt không em", "size 41 không em"),
    # Before the number, as before.
    ("không năm triệu đâu", "không 5.000.000đ đâu"),
    # With punctuation the run already ended at the comma.
    ("bốn triệu tám, không biết", "4.800.000đ, không biết"),
])
def test_khong_around_a_number_asks_or_negates(said, written):
    assert itn.normalise(said, NOW) == written


def test_amounts_reads_spoken_and_written_money():
    assert itn.amounts("giá năm triệu hai không em, bên kia 4.890.000đ") == [5_200_000, 4_890_000]
