from __future__ import annotations

def build_nanpin_plan(
    total_budget_yen: float,
    averaging_down_count: int,
    current_price: float,
    period_low: float,
    max_gap_percent: int = 10,
) -> dict[str, list[float] | float | int]:
    """Build a plan as close as possible to the selected gap without exceeding it."""
    budget = float(total_budget_yen)
    count = int(averaging_down_count)
    current = float(current_price)
    low = min(float(period_low), current)
    gap_percent = int(max_gap_percent)
    if budget <= 0:
        raise ValueError("投資資金は0円より大きくしてください。")
    if count < 1:
        raise ValueError("ナンピン回数は1回以上にしてください。")
    if current <= 0 or low <= 0:
        raise ValueError("株価は0円より大きい値が必要です。")
    if gap_percent not in (5, 10, 20, 30):
        raise ValueError("底値からの許容差は5％・10％・20％・30％から選んでください。")

    target_step = count
    investment_prices = [
        current + (low - current) * step / target_step
        for step in range(count + 1)
    ]
    # Keep a small margin inside the selected limit. The screen rounds the gap
    # to a whole percentage, so this also prevents an exact boundary from being
    # displayed one percentage point beyond the user's selection.
    safe_gap_fraction = max(0.0, gap_percent - 0.25) / 100.0
    stage_weights = [1.0]
    cumulative_weight = 1.0
    cumulative_shares = 1.0 / current

    for price in investment_prices[1:]:
        stage_target_average = price / (1.0 - safe_gap_fraction)
        denominator = stage_target_average / price - 1.0
        required_weight = max(
            0.0,
            (cumulative_weight - stage_target_average * cumulative_shares)
            / denominator,
        )
        # When the limit is loose, keep later purchases small so the final
        # average stays as close as possible to the selected upper limit.
        # A tiny positive weight keeps every requested nanpin stage present.
        next_weight = max(0.001, required_weight * (1.0 + 1e-9))
        stage_weights.append(next_weight)
        cumulative_weight += next_weight
        cumulative_shares += next_weight / price

    target_average = investment_prices[-1] / (1.0 - safe_gap_fraction)

    weight_sum = sum(stage_weights)
    investment_amounts = [budget * weight / weight_sum for weight in stage_weights]

    running_average_prices: list[float] = []
    cumulative_amount = 0.0
    cumulative_shares = 0.0
    for amount, price in zip(investment_amounts, investment_prices):
        cumulative_amount += amount
        cumulative_shares += amount / price
        running_average_prices.append(cumulative_amount / cumulative_shares)

    return {
        "investment_amounts": investment_amounts,
        "investment_prices": investment_prices,
        "average_prices": running_average_prices,
        "period_low": low,
        "target_average": target_average,
        "target_step": target_step,
        "max_gap_percent": gap_percent,
    }
