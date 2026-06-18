class CheckoutService:
    def calculate_total(self, cart):
        subtotal = sum(item["price"] * item.get("quantity", 1) for item in cart["items"])
        return subtotal + cart.get("shipping_fee", 0)

    def authorize_payment(self, payment_method, amount):
        if amount <= 0:
            raise ValueError("amount must be positive")
        return {"status": "authorized", "method": payment_method}
