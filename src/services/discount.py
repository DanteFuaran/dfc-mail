"""Расчет скидок"""


def calculate_discount(quantity: int) -> float:
    """Расчет скидки в зависимости от количества."""
    discount_rules = {500: 5, 1000: 10, 2000: 15, 5000: 20}
    max_discount = 0
    for threshold, discount in sorted(discount_rules.items(), reverse=True):
        if quantity >= threshold:
            max_discount = discount
            break
    return max_discount


def calculate_total_price(price_per_unit: float, quantity: int) -> tuple[float, float]:
    """Расчет итоговой цены с учетом скидки. Возвращает (скидка %, итого)."""
    discount_percent = calculate_discount(quantity)
    total = price_per_unit * quantity
    discount_amount = total * (discount_percent / 100)
    return discount_percent, total - discount_amount
