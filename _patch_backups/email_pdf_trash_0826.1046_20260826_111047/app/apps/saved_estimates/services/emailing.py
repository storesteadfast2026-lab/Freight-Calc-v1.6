from dataclasses import dataclass

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.core.mail import EmailMultiAlternatives
from django.core.validators import validate_email
from django.template.loader import render_to_string

from apps.authentication_gateway.models import CalculatorUserProfile
from apps.authentication_gateway.services import get_calculator_profile


MAX_ESTIMATES_PER_EMAIL = 20


class EstimateEmailError(ValueError):
    """A safe, user-facing validation error for estimate email delivery."""


@dataclass(frozen=True)
class RecipientOption:
    email: str
    label: str


def estimate_email_is_configured() -> bool:
    """Return whether the SMTP settings required for delivery are available."""
    return bool(
        getattr(settings, 'ESTIMATE_EMAIL_ENABLED', False)
        and settings.EMAIL_HOST
        and settings.EMAIL_PORT
        and settings.EMAIL_HOST_USER
        and settings.EMAIL_HOST_PASSWORD
        and settings.DEFAULT_FROM_EMAIL
    )


def is_customer_user(user) -> bool:
    if user.is_superuser:
        return False
    return (
        get_calculator_profile(user).role
        == CalculatorUserProfile.Role.CUSTOMER_USER
    )


def recipient_options_for_client(user, client):
    """Return registered recipients the requesting user may email."""
    if is_customer_user(user):
        if user.email and _valid_email(user.email):
            return [RecipientOption(user.email, user.email)]
        return []

    User = get_user_model()
    recipients = (
        User.objects.filter(
            is_active=True,
            calculator_profile__calculator_access=True,
            calculator_profile__role=CalculatorUserProfile.Role.CUSTOMER_USER,
            calculator_profile__client=client,
        )
        .exclude(email='')
        .order_by('email', 'pk')
    )
    options = []
    seen = set()
    for recipient in recipients:
        email = recipient.email.strip()
        key = email.casefold()
        if key in seen or not _valid_email(email):
            continue
        name = recipient.get_full_name().strip()
        label = f'{name} — {email}' if name else email
        options.append(RecipientOption(email=email, label=label))
        seen.add(key)
    return options


def resolve_recipient(user, client, requested_email=''):
    """Resolve a recipient without allowing arbitrary-address email sending."""
    options = recipient_options_for_client(user, client)
    if not options:
        raise EstimateEmailError(
            'No active customer account with a valid registered email is available.'
        )

    if is_customer_user(user):
        return options[0].email

    requested = (requested_email or '').strip().casefold()
    if not requested and len(options) == 1:
        return options[0].email
    for option in options:
        if option.email.casefold() == requested:
            return option.email
    raise EstimateEmailError('Select a registered customer email for this client.')


def send_estimates_email(*, sender_user, estimates, recipient):
    """Send immutable estimate snapshots without invoking the freight engine."""
    estimates = list(estimates)
    if not estimate_email_is_configured():
        raise EstimateEmailError('Estimate email delivery is not configured.')
    if not estimates:
        raise EstimateEmailError('Select at least one saved estimate.')
    if len(estimates) > MAX_ESTIMATES_PER_EMAIL:
        raise EstimateEmailError(
            f'Select no more than {MAX_ESTIMATES_PER_EMAIL} estimates per email.'
        )

    client_ids = {estimate.client_id for estimate in estimates}
    if len(client_ids) != 1:
        raise EstimateEmailError('All selected estimates must belong to one client.')

    client = estimates[0].client
    allowed_recipient = resolve_recipient(sender_user, client, recipient)
    context = {
        'client': client,
        'estimates': estimates,
        'recipient': allowed_recipient,
        'sent_by': sender_user,
    }
    subject = _subject_for(estimates, client)
    text_body = render_to_string('saved_estimates/email.txt', context)
    html_body = render_to_string('saved_estimates/email.html', context)
    message = EmailMultiAlternatives(
        subject=subject,
        body=text_body,
        from_email=settings.DEFAULT_FROM_EMAIL,
        to=[allowed_recipient],
    )
    message.attach_alternative(html_body, 'text/html')
    message.send(fail_silently=False)
    return allowed_recipient


def _subject_for(estimates, client):
    if len(estimates) == 1:
        return f'Freight estimate {estimates[0].reference} — {client.name}'
    return f'{len(estimates)} freight estimates — {client.name}'


def _valid_email(value):
    try:
        validate_email(value)
    except ValidationError:
        return False
    return True
