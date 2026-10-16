"""Transparent sell-now versus store grain decision calculations.

The engine deliberately accepts user-supplied bids and explicit assumptions.  It
does not retrieve a live bid or describe the result as a marketing recommendation.
"""

from dataclasses import dataclass
from decimal import Decimal


ZERO = Decimal(0)
ONE_HUNDRED = Decimal(100)
TWELVE = Decimal(12)


@dataclass(frozen=True)
class StorageDecisionInputs:
    """Inputs for one grain inventory and one proposed storage period."""

    quantity_bushels: Decimal
    current_bid_per_bushel: Decimal
    storage_months: Decimal
    annual_financing_rate_pct: Decimal
    storage_cost_per_bushel_month: Decimal
    handling_cost_per_bushel: Decimal
    shrink_pct: Decimal
    incremental_insurance_per_bushel_month: Decimal = ZERO
    future_transport_difference_per_bushel: Decimal = ZERO


@dataclass(frozen=True)
class StorageDecisionResult:
    """Calculated economics expressed at the end of the storage period."""

    sell_now_value: Decimal
    retained_bushels: Decimal
    financing_cost: Decimal
    storage_cost: Decimal
    handling_cost: Decimal
    insurance_cost: Decimal
    transport_difference: Decimal
    total_carrying_cost: Decimal
    break_even_future_bid: Decimal
    required_bid_increase: Decimal
    required_bid_increase_pct: Decimal

    def advantage_at(self, future_bid_per_bushel: Decimal) -> Decimal:
        """Return stored-sale value less the future value of selling now."""

        stored_net = self.retained_bushels * future_bid_per_bushel
        non_financing_costs = self.total_carrying_cost - self.financing_cost
        return stored_net - non_financing_costs - (
            self.sell_now_value + self.financing_cost
        )


def calculate_storage_decision(
    inputs: StorageDecisionInputs,
) -> StorageDecisionResult:
    """Calculate the cash bid required for storage to equal a sale today.

    Financing is simple interest on the current gross sale value.  Shrink is
    applied once to saleable bushels at the end of the selected period.  All
    other costs are incremental costs caused by delaying the sale.
    """

    _validate(inputs)
    sell_now_value = inputs.quantity_bushels * inputs.current_bid_per_bushel
    financing_cost = (
        sell_now_value
        * inputs.annual_financing_rate_pct
        / ONE_HUNDRED
        * inputs.storage_months
        / TWELVE
    )
    storage_cost = (
        inputs.quantity_bushels
        * inputs.storage_cost_per_bushel_month
        * inputs.storage_months
    )
    handling_cost = inputs.quantity_bushels * inputs.handling_cost_per_bushel
    insurance_cost = (
        inputs.quantity_bushels
        * inputs.incremental_insurance_per_bushel_month
        * inputs.storage_months
    )
    transport_difference = (
        inputs.quantity_bushels * inputs.future_transport_difference_per_bushel
    )
    retained_bushels = inputs.quantity_bushels * (
        Decimal(1) - inputs.shrink_pct / ONE_HUNDRED
    )
    total_carrying_cost = (
        financing_cost
        + storage_cost
        + handling_cost
        + insurance_cost
        + transport_difference
    )
    break_even_future_bid = (
        sell_now_value + total_carrying_cost
    ) / retained_bushels
    required_bid_increase = break_even_future_bid - inputs.current_bid_per_bushel
    required_bid_increase_pct = (
        required_bid_increase / inputs.current_bid_per_bushel * ONE_HUNDRED
    )
    return StorageDecisionResult(
        sell_now_value=sell_now_value,
        retained_bushels=retained_bushels,
        financing_cost=financing_cost,
        storage_cost=storage_cost,
        handling_cost=handling_cost,
        insurance_cost=insurance_cost,
        transport_difference=transport_difference,
        total_carrying_cost=total_carrying_cost,
        break_even_future_bid=break_even_future_bid,
        required_bid_increase=required_bid_increase,
        required_bid_increase_pct=required_bid_increase_pct,
    )


def _validate(inputs: StorageDecisionInputs) -> None:
    positive = {
        "quantity_bushels": inputs.quantity_bushels,
        "current_bid_per_bushel": inputs.current_bid_per_bushel,
        "storage_months": inputs.storage_months,
    }
    for name, value in positive.items():
        if value <= ZERO:
            raise ValueError(f"{name} must be greater than zero")
    non_negative = {
        "annual_financing_rate_pct": inputs.annual_financing_rate_pct,
        "storage_cost_per_bushel_month": inputs.storage_cost_per_bushel_month,
        "handling_cost_per_bushel": inputs.handling_cost_per_bushel,
        "shrink_pct": inputs.shrink_pct,
        "incremental_insurance_per_bushel_month": (
            inputs.incremental_insurance_per_bushel_month
        ),
    }
    for name, value in non_negative.items():
        if value < ZERO:
            raise ValueError(f"{name} cannot be negative")
    if inputs.shrink_pct >= ONE_HUNDRED:
        raise ValueError("shrink_pct must be less than 100")
