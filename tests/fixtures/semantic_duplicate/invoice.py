def net_amount(amount: float, reduction: float) -> float:
    if amount < 0:
        raise ValueError("negative amount")
    if not 0 <= reduction <= 100:
        raise ValueError("reduction out of range")
    remaining = amount * (1 - reduction / 100)
    return round(remaining, 2)
