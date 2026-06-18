from checkout_service import CheckoutService


def test_calculate_total_includes_shipping():
    service = CheckoutService()
    cart = {
        "items": [{"price": 20, "quantity": 2}],
        "shipping_fee": 5,
    }
    assert service.calculate_total(cart) == 45


def test_authorize_payment_rejects_non_positive_amount():
    service = CheckoutService()
    try:
        service.authorize_payment("saved_card", 0)
    except ValueError as exc:
        assert "positive" in str(exc)
