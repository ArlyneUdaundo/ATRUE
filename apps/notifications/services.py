"""The one function every module calls to raise a notification (Section 16).

Keeping the "who gets told what" decision here rather than in each workflow
means the notification table (Section 16) and the audit trail (Section 17) stay
in step, and that a recipient can never be widened accidentally: recipients are
resolved from role assignments by the transaction engine and passed in.
"""

from django.contrib.auth import get_user_model

from .models import Notification

User = get_user_model()


def notify(recipient, notification_type, message, *, transaction=None,
           session=None, establishment=None, title=''):
    """Create one notification for ``recipient`` and return it (or None).

    Anonymous / missing recipients are ignored rather than raising: a
    notification is never important enough to fail the operation that produced
    it, and the audit log records the action regardless.
    """
    if recipient is None:
        return None
    if isinstance(recipient, (list, tuple, set)):
        return [notify(one, notification_type, message, transaction=transaction,
                       session=session, establishment=establishment, title=title)
                for one in recipient]
    if not getattr(recipient, 'pk', None):
        return None

    # Accept either the transaction or a raw pk so callers that only hold the id
    # do not have to re-fetch it, and so a notification can be written before
    # the transaction itself is saved.
    transaction_id = getattr(transaction, 'pk', transaction)
    if session is None and transaction_id:
        session = (transaction.session if hasattr(transaction, 'session') else None)

    return Notification.objects.create(
        recipient=recipient,
        notification_type=notification_type,
        title=title or '',
        message=message,
        transaction_id=transaction_id or None,
        session=session,
        establishment=establishment,
    )


def notify_many(recipients, notification_type, message, **kwargs):
    """Fan a message out to several students; skips duplicates and empty sets."""
    if not recipients:
        return []
    unique = []
    seen = set()
    for user in recipients:
        pk = getattr(user, 'pk', None)
        if pk and pk not in seen:
            seen.add(pk)
            unique.append(user)
    return [notify(user, notification_type, message, **kwargs) for user in unique]


def mark_read(notification, *, user):
    """Mark ``notification`` read, refusing anything that is not ``user``'s.

    The ownership check is repeated here (not just in the view) so the rule holds
    for every caller, including internal ones.
    """
    if notification.recipient_id != user.pk:
        return False
    notification.mark_read()
    return True


def mark_all_read(*, user):
    """Mark the caller's whole inbox read and return how many rows changed."""
    from django.utils import timezone

    return Notification.objects.filter(
        recipient=user, is_read=False).update(is_read=True, read_at=timezone.now())


def unread_count(user):
    if user is None or not getattr(user, 'pk', None):
        return 0
    return Notification.objects.filter(recipient=user, is_read=False).count()