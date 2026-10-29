"""The promotion, payment, quantity and identity rules the advanced personas test (KM-02/03/04/05/07/08, VC-04, PB-08)."""
import re


def _by_persona(advanced_scenarios, persona):
    found = [s for s in advanced_scenarios if s.persona == persona]
    assert found, persona
    return found


def _forbidden(call):
    return {(getattr(f, "field", None), getattr(f, "value", None)) for f in call.success_if.forbidden_claims}


def test_two_exclusive_programmes_are_never_added(advanced_scenarios):
    call = _by_persona(advanced_scenarios, "khach_doi_cong_don_khuyen_mai")[0].calls["call_1"]
    assert call.success_if.tool_called == "order.create"
    price = call.ground_truth_facts["price_vnd"]
    assert call.success_if.args_match["price_vnd"] == price
    assert ("price_vnd", price - 300_000) in _forbidden(call)      # AIR-OCT added to TRADE-IN-AP


def test_a_once_per_customer_code_is_gone_on_the_second_purchase(advanced_scenarios):
    calls = _by_persona(advanced_scenarios, "khach_mua_lai_khuyen_mai_mot_lan")[0].calls
    first, second = calls["call_1"].ground_truth_facts, calls["call_2"].ground_truth_facts
    assert first["promo_RUN-10_active"] is True and second["promo_RUN-10_active"] is False
    assert second["price_vnd"] > first["price_vnd"]
    assert ("price_vnd", first["price_vnd"]) in _forbidden(calls["call_2"])


def test_regional_freeship_follows_the_delivery_address(advanced_scenarios):
    for scenario in _by_persona(advanced_scenarios, "khach_hoi_freeship_theo_vung"):
        call = scenario.calls["call_1"]
        assert call.ground_truth_facts["freeship"] is False and ("freeship", True) in _forbidden(call)
        assert call.success_if.must_say_any


def test_future_promotions_are_never_announced(advanced_scenarios):
    for scenario in _by_persona(advanced_scenarios, "khach_hoi_khuyen_mai_sap_toi"):
        patterns = scenario.calls["call_1"].success_if.trace_must_not_match
        assert any(re.search(p, "bên em có giảm dịp 11/11 ạ") for p in patterns)
        assert not any(re.search(p, "giá hôm nay là 1.890.000đ ạ") for p in patterns)


def test_e_wallet_and_quantity_orders(advanced_scenarios):
    wallets = {s.calls["call_2"].success_if.args_match["payment"] for s in _by_persona(advanced_scenarios, "khach_thanh_toan_vi_dien_tu")}
    assert wallets <= {"momo", "zalopay"} and wallets
    for scenario in _by_persona(advanced_scenarios, "khach_mua_so_luong"):
        call = scenario.calls["call_1"]
        assert call.success_if.args_match["qty"] == 3
        assert call.success_if.total_match_vnd == 3 * call.ground_truth_facts["price_vnd"]


def test_a_gift_is_not_money_and_a_stranger_gets_no_order(advanced_scenarios):
    gift = _by_persona(advanced_scenarios, "khach_doi_qua_thanh_tien")[0].calls["call_1"]
    assert gift.ground_truth_facts["gift_sku"] and ("gift_cash_convertible", True) in _forbidden(gift)
    for scenario in _by_persona(advanced_scenarios, "khach_goi_so_moi_xung_khach_cu"):
        call = scenario.calls["call_1"]
        assert call.success_if.trace_must_not_match and "order.create" in call.success_if.must_not_call_tools
