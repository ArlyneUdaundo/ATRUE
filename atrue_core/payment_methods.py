"""Canonical payment methods offered by the simulation platform."""

PAYMENT_METHOD_CHOICES = (
    ('GCASH', 'GCash'),
    ('MAYA', 'Maya'),
    ('BANK_TRANSFER', 'Bank Transfer'),
    ('CREDIT_CARD', 'Credit Card'),
    ('DEBIT_CARD', 'Debit Card'),
    ('PAYPAL', 'PayPal'),
    ('QR_PH', 'QR Ph'),
)

PAYMENT_METHOD_VALUES = frozenset(value for value, _label in PAYMENT_METHOD_CHOICES)


def is_supported_payment_method(value):
    return value in PAYMENT_METHOD_VALUES


def validate_payment_method(value):
    """Reject stale or forged payment choices before recording a payment."""
    if not is_supported_payment_method(value):
        raise ValueError('Choose one of the supported payment methods.')
    return value


def payment_method_label(value):
    """Label new methods and keep legacy transaction values readable."""
    labels = dict(PAYMENT_METHOD_CHOICES)
    legacy_labels = {
        'CASH': 'Cash (historical)',
        'CARD': 'Card (historical)',
        'OTHER': 'Other (historical)',
        'E_WALLET': 'E-wallet (historical)',
    }
    return labels.get(value, legacy_labels.get(value, value or ''))


def validate_payment_method(value):
    """Reject stale or forged payment choices before recording a payment."""
    if not is_supported_payment_method(value):
        raise ValueError('Choose one of the supported payment methods.')
    return value
