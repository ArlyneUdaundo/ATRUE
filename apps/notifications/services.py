"""The one function every module calls to raise a notification (Section 16).

Keeping the "who gets told what" decision here rather than in each workflow
means the notification table (Section 16) and the audit trail (Section 17) stay
in step, and that a recipient can never be widened accidentally: recipients are
resolved from role assignments by the transaction engine and passed in.
"""

from django.contrib.auth import get_user_model
from django.core.exceptions import ObjectDoesNotExist

from .models import Notification

User = get_user_model()


def notify(recipient, notification_type, message, *, transaction=None,
           session=None, establishment=None, title='', assignment=None,
           role=None, actor=None, related_object=None):
    """Create one notification for ``recipient`` and return it (or None).

    Anonymous / missing recipients are ignored rather than raising: a
    notification is never important enough to fail the operation that produced
    it, and the audit log records the action regardless.
    """
    if recipient is None:
        return None
    if isinstance(recipient, (list, tuple, set)):
        return [notify(one, notification_type, message, transaction=transaction,
                       session=session, establishment=establishment, title=title,
                       assignment=assignment, role=role, actor=actor,
                       related_object=related_object)
                for one in recipient]
    if not getattr(recipient, 'pk', None):
        return None

    # Accept either the transaction or a raw pk so callers that only hold the id
    # do not have to re-fetch it, and so a notification can be written before
    # the transaction itself is saved.
    transaction_id = getattr(transaction, 'pk', transaction)
    if related_object is None and transaction is not None:
        related_object = getattr(transaction, 'subject', None)
    if session is None and transaction_id:
        session = (transaction.session if hasattr(transaction, 'session') else None)

    notification = Notification(
        recipient=recipient,
        notification_type=notification_type,
        title=title or '',
        message=message,
        transaction_id=transaction_id or None,
        session=session,
        establishment=establishment,
        assignment=assignment,
        role=role,
        actor=actor,
    )
    if related_object is not None and getattr(related_object, 'pk', None):
        from django.contrib.contenttypes.models import ContentType
        notification.related_content_type = ContentType.objects.get_for_model(related_object)
        notification.related_object_id = related_object.pk
    notification.save()
    return notification


def notify_role_assignment(assignment, actor, *, modified=False, removed=False):
    """Notify the assigned student after an assignment has been saved."""
    role = assignment.get_role_display()
    session_name = assignment.session.name if assignment.session_id else assignment.activity_name
    session_id = assignment.session.session_id if assignment.session_id else ''
    establishment = assignment.establishment
    instructor = actor.get_full_name().strip() or actor.get_username()
    if removed:
        message = f'Instructor {instructor} ended your assignment as {role}'
    else:
        message = f'Instructor {instructor} assigned you the role of {role}'
    if establishment:
        message += f' at {establishment.name}'
    message += f' for {session_name}'
    if session_id:
        message += f' (Session {session_id})'
    message += '.'
    return notify(
        assignment.student,
        (Notification.Type.ROLE_REMOVED if removed else
         Notification.Type.ROLE_MODIFIED if modified else Notification.Type.ROLE_ASSIGNED),
        message,
        title=('Role Assignment Ended' if removed else
               'Role Assignment Updated' if modified else 'New Role Assigned'),
        assignment=assignment,
        session=assignment.session,
        establishment=establishment,
        role=assignment.role_ref,
        actor=actor,
    )


def notify_assignment_task_completed(assignment, task_label, actor, *,
                                     booking_reference='', completion_event=''):
    """Notify the assigned student and instructor when a workflow task completes."""
    session = assignment.session
    student = assignment.student
    student_name = student.get_full_name().strip() or student.get_username()
    role = assignment.get_role_display()
    session_name = session.name if session else assignment.activity_name
    action_labels = {
        'BOOKING_CONFIRMED': 'confirmed a booking',
        'BOOKING_FULFILLED': 'completed a booking',
        'CUSTOMER_BOOKING_SUBMITTED': 'submitted a booking',
        'PAYMENT_VERIFIED': 'verified a payment',
        'PAYMENT_REJECTED': 'rejected a payment',
    }
    action = action_labels.get(completion_event, '')
    details = f'"{task_label}"'
    if action:
        details += f' ({action})'
    details += f' as {role}'
    if assignment.establishment_id:
        details += f' at {assignment.establishment.name}'
    details += f' for {session_name}'
    if booking_reference:
        details += f' (Reference: {booking_reference})'
    details += '.'

    student_notification = notify(
        student,
        Notification.Type.STUDENT_WORK_COMPLETED,
        f'You completed {details}',
        title='Your workflow task completed',
        assignment=assignment,
        session=session,
        establishment=assignment.establishment,
        role=assignment.role_ref,
        actor=actor,
    )
    instructor = session.instructor if session else assignment.assigned_by
    instructor_notification = None
    if (instructor is not None
            and instructor.pk not in {
                getattr(student, 'pk', None), getattr(actor, 'pk', None),
            }):
        instructor_notification = notify(
            instructor,
            Notification.Type.STUDENT_WORK_COMPLETED,
            f'{student_name} completed {details}',
            title='Student workflow completed',
            assignment=assignment,
            session=session,
            establishment=assignment.establishment,
            role=assignment.role_ref,
            actor=actor,
        )
    return instructor_notification or student_notification


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


def notify_announcement(recipients, announcement_type, title, message, *,
                        session=None, actor=None):
    """Deliver one instructor announcement or update to every session student."""
    notification_type = (
        Notification.Type.UPDATE if announcement_type == Notification.Type.UPDATE
        else Notification.Type.ANNOUNCEMENT
    )
    return notify_many(
        recipients,
        notification_type,
        message,
        title=title,
        session=session,
        actor=actor,
        related_object=session,
    )


def notify_service_booking(booking, event, actor=None):
    """Notify the booking owner about a persisted event in a bookable service."""
    labels = {
        'resorts.reservation': ('RESORT_RESERVATION', 'resort reservation'),
        'staycations.reservation': ('STAYCATION_RESERVATION', 'staycation reservation'),
        'activities.booking': ('ACTIVITY_BOOKING', 'activity booking'),
        'landmarks.ticket': ('LANDMARK_TICKET', 'landmark ticket'),
    }
    try:
        prefix, description = labels[booking._meta.label_lower]
    except (AttributeError, KeyError):
        return None
    suffixes = {
        'submitted': ('SUBMITTED', 'Submitted', 'was submitted'),
        'confirmed': ('CONFIRMED', 'Confirmed', 'was confirmed'),
        'rejected': ('REJECTED', 'Declined', 'was declined'),
        'cancelled': ('CANCELLED', 'Cancelled', 'was cancelled'),
        'updated': ('UPDATED', 'Updated', 'was updated'),
    }
    if event not in suffixes:
        return None
    code, title, verb = suffixes[event]
    notification_type = getattr(Notification.Type, f'{prefix}_{code}', Notification.Type.GENERAL)
    owner = getattr(booking, 'customer', None)
    reference = getattr(booking, 'booking_reference', str(booking.pk))
    service = None
    for path in ('unit.resort', 'staycation', 'activity', 'destination'):
        value = booking
        try:
            for part in path.split('.'):
                value = getattr(value, part)
            service = value
            break
        except (AttributeError, ObjectDoesNotExist):
            continue
    service_name = getattr(service, 'name', None) or str(service or description)
    return notify(
        owner, notification_type,
        f'Your {description} {reference} for {service_name} {verb}.',
        title=f'{description.title()} {title}', actor=actor,
        related_object=booking,
    )


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
