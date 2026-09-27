def discounted_total(subtotal: float, percent: float) -> float:
    if subtotal < 0:
        raise ValueError("negative subtotal")
    if percent < 0 or percent > 100:
        raise ValueError("invalid discount")
    discount = subtotal * percent / 100
    return round(subtotal - discount, 2)
