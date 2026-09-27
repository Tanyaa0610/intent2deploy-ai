from src.payments.provider_client import PaymentProviderClient
from src.payments.service import PaymentService


def test_charge_order_succeeds() -> None:
    service = PaymentService(PaymentProviderClient())
    charge = service.charge_order(order_id=1, amount=42.0)
    assert charge.amount == 42.0
    assert charge.provider_charge_id


def test_charges_for_order_returns_only_matching_order() -> None:
    service = PaymentService(PaymentProviderClient())
    service.charge_order(order_id=1, amount=10.0)
    service.charge_order(order_id=2, amount=20.0)
    assert len(service.charges_for_order(1)) == 1


# NOTE: There is intentionally no regression test here for a retried charge
# after a provider timeout — that gap is what the "fix duplicate orders on
# payment-provider timeout" benchmark task (task_011) is expected to close
# by adding idempotency-key support and a test proving a retry does not
# create a second provider charge.
