"""Enable one existing Translogic Customer as a Calculator Customer."""

from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction

from .models import Client, Customer


class CalculatorCustomerConflict(ValidationError):
    """A Customer cannot be enabled without changing an existing relationship."""


def enable_calculator_customer(customer_id: int, *, active: bool = True) -> tuple[Client, bool]:
    """Return (Client, created). All callers use the same atomic operation."""
    try:
        return _enable_calculator_customer(customer_id, active=active)
    except IntegrityError as exc:
        raise CalculatorCustomerConflict(
            'Calculator Customer creation conflicted with another request. Reload and try again.'
        ) from exc


@transaction.atomic
def _enable_calculator_customer(customer_id: int, *, active: bool) -> tuple[Client, bool]:
    customer = Customer.objects.select_for_update().get(pk=customer_id)
    if customer.is_special or customer.code == '*':
        raise CalculatorCustomerConflict('The special Customer cannot become a Calculator Customer.')

    if customer.linked_client_id:
        return Client.objects.get(pk=customer.linked_client_id), False

    existing = Client.objects.select_for_update().filter(code=customer.code).first()
    if existing is not None:
        owner = Customer.objects.filter(linked_client=existing).exclude(pk=customer.pk).first()
        if owner is not None:
            raise CalculatorCustomerConflict(
                f'Calculator Customer {existing.code} is already linked to Customer {owner.code}.'
            )
        # An existing Client keeps its Name. Active follows the explicit choice.
        if existing.active != active:
            existing.active = active
            existing.save(update_fields=['active', 'updated_at'])
        client, created = existing, False
    else:
        client = Client(code=customer.code, name=customer.name, active=active)
        client.full_clean()
        client.save()
        created = True

    customer.linked_client = client
    # Historical imported rows may contain an empty raw_data payload. Validate
    # the relationship without revalidating unrelated import provenance.
    customer.full_clean(exclude=['raw_data'])
    customer.save(update_fields=['linked_client', 'updated_at'])
    return client, created
