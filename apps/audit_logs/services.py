"""The single entry point for writing to the audit trail (Section 17).

``audit_logs.models.AuditLog`` makes the table append-only; this service is the
only supported way to fill it, which is what keeps the *set* of recorded actions
consistent with the list in Section 17 (role assignment, claiming, approval,
billing, ticketing, cancellation, session activation, ...).
"""

from .models import AuditLog


def audit(action, *, actor=None, session=None, establishment=None, transaction=None,
          role=None, details='', remarks='', previous_value='', new_value='',
          request=None):
    """Append one audit row and return it.

    ``session_label`` / ``establishment_label`` are denormalised onto the row so
    the entry stays readable after its subject is removed (the FKs are
    ``SET_NULL`` by design).
    """
    if actor is not None and not getattr(actor, 'pk', None):
        actor = None
    # ``role`` may be a Role instance or a bare role code string; the code is
    # also denormalised onto the row so an entry stays readable even after the
    # Role catalogue changes.
    role_instance = role if hasattr(role, 'pk') else None
    role_code = role if isinstance(role, str) else getattr(role, 'code', '') or ''

    # Derive the session/establishment from the transaction so a caller holding
    # only a transaction (the usual case in the engine) still records where the
    # action happened.
    if transaction is not None and hasattr(transaction, 'pk'):
        if session is None:
            session = getattr(transaction, 'session', None)
        if establishment is None:
            establishment = getattr(transaction, 'establishment', None)

    return AuditLog.objects.create(
        actor=actor,
        action=action,
        details=details or '',
        role=role_instance,
        role_code=role_code,
        session=session,
        session_label=getattr(session, 'name', '') or '',
        establishment=establishment,
        establishment_label=getattr(establishment, 'name', '') or '',
        transaction=transaction if hasattr(transaction, 'pk') else None,
        previous_value=str(previous_value) if previous_value not in (None, '') else '',
        new_value=str(new_value) if new_value not in (None, '') else '',
        remarks=remarks or '',
        ip_address=_client_ip(request),
    )


def _client_ip(request):
    if request is None:
        return None
    meta = getattr(request, 'META', None)
    if meta is None:
        return None
    forwarded = meta.get('HTTP_X_FORWARDED_FOR', '')
    if forwarded:
        # Left-most entry is the original client when a trusted proxy is in front.
        candidate = forwarded.split(',')[0].strip()
    else:
        candidate = meta.get('REMOTE_ADDR', '')
    if not candidate:
        return None
    return candidate[:45] or None