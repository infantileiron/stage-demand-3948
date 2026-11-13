"""Integer guide allocation across venues that share one daily headcount pool.

Objective: minimise the largest uncovered audience count (people), i.e. the
venue that would be left most short of guides. Once that worst shortfall is
fixed, leftover capacity goes to the earlier venue in canonical order, which is
what "同分优先场馆名靠前者" means.
"""
from src.constants.enums import VENUE_ORDER

MIN_PER_VENUE = 2


def _tenths(value): return int(round(float(value) * 10))


def _minimum(upper_units, carry, ceilings, threshold, capacity):
    """Fewest guides per venue that leave at most ``threshold`` people uncovered.

    Returns None when the roster cannot reach that threshold inside the daily
    capacity or inside a venue's own suggestion.
    """
    allocation = []
    for upper, people, ceiling in zip(upper_units, carry, ceilings):
        if upper <= threshold:
            needed = MIN_PER_VENUE
        else:
            needed = max(MIN_PER_VENUE, -(-(upper - threshold) // (10 * people)))
        if needed > ceiling:
            return None
        allocation.append(needed)
    return allocation if sum(allocation) <= capacity else None


def venue_sort_key(venue):
    """Earlier canonical venue first; unknown names fall back to name order."""
    if venue in VENUE_ORDER:
        return (0, VENUE_ORDER.index(venue), venue)
    return (1, 0, venue)


def allocate(uppers, people_per_usher, suggestions, capacity):
    """Allocate whole guides for one day.

    ``uppers`` are the forecast interval upper bounds (people), ``suggestions``
    the single-venue guide counts already produced by the forecast
    (``max(2, ceil(upper / people_per_usher))``). The result never exceeds the
    daily capacity nor any venue's own suggestion and keeps at least two guides
    per venue. Raises ValueError when the capacity cannot hold the floor.
    """
    venues = len(uppers)
    if venues == 0:
        raise ValueError("至少需要一个场馆")
    if len(people_per_usher) != venues or len(suggestions) != venues:
        raise ValueError("场馆、承载数与建议必须一一对应")
    capacity = int(capacity)
    if capacity < MIN_PER_VENUE * venues:
        raise ValueError(f"每日人力容量{capacity}人不足以满足每厅保底{MIN_PER_VENUE}人（至少需{MIN_PER_VENUE * venues}人）")
    upper_units = [_tenths(value) for value in uppers]
    carry = [int(people) for people in people_per_usher]
    ceilings = [int(value) for value in suggestions]
    if any(people <= 0 for people in carry):
        raise ValueError("每名引导员承载人数必须为正整数")
    if any(ceiling < MIN_PER_VENUE for ceiling in ceilings):
        raise ValueError("单厅原建议不足每厅保底两人，无法合并")

    # The optimum is always one of the reachable uncovered values; searching
    # that finite ladder keeps the result exact instead of greedy-approximate.
    thresholds = {0}
    for upper, people, ceiling in zip(upper_units, carry, ceilings):
        for count in range(MIN_PER_VENUE, ceiling + 1):
            thresholds.add(max(0, upper - 10 * people * count))
    ladder = sorted(thresholds)

    low, high = 0, len(ladder) - 1
    best = None
    while low <= high:
        middle = (low + high) // 2
        needed = _minimum(upper_units, carry, ceilings, ladder[middle], capacity)
        if needed is None:
            low = middle + 1
        else:
            best = (ladder[middle], needed)
            high = middle - 1
    if best is None:  # defensive; the floor check above already guarantees this
        raise ValueError("每日人力容量不足，无法生成合并编排")

    _, allocation = best
    # Same objective already reached: spend the remainder on earlier venues.
    spare = capacity - sum(allocation)
    for index in range(venues):
        extra = min(spare, ceilings[index] - allocation[index])
        allocation[index] += extra
        spare -= extra
    return allocation


def uncovered(upper, people_per_usher, guides):
    """People left without a guide, never negative."""
    return round(max(0.0, float(upper) - int(people_per_usher) * int(guides)), 1)
