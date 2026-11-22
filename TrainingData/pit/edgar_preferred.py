"""Interpret accession-specific evidence about preferred stock."""


def preferred_evidence(facts, accession, period):
    """Return a supported adjustment and evidence type, including a verified zero."""
    def values(tag):
        return {
            fact["val"] for fact in facts.get(tag, [])
            if fact["accn"] == accession and fact["end"] == period and "start" not in fact
        }

    carrying = values("PreferredStockCarryingValue")
    if len(carrying) == 1 and next(iter(carrying)) >= 0:
        return next(iter(carrying)), "reported_carrying_value"
    if carrying:
        return None, "conflicting_carrying_value"
    outstanding = values("PreferredStockSharesOutstanding")
    issued = values("PreferredStockSharesIssued")
    other_claims = values("PreferredStockValue") | values("PreferredStockRedemptionValue")
    if outstanding == {0} and issued <= {0} and other_claims <= {0}:
        return 0, "reported_zero_preferred_shares"
    return None, "unverified_preferred_stock"
