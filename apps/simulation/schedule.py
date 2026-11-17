"""Shared time-window helpers for simulation sessions and their assignments."""

from datetime import datetime
from types import SimpleNamespace

from django.utils import timezone


def _unconfigured_window(now):
    return {
        'state': 'unconfigured',
        'can_start': False,
        'start_at': '',
        'end_at': '',
        'server_now': now.isoformat(),
        'message': (
            'Your session schedule is not set yet. Please contact your instructor.'),
    }


def session_window_for(session, now=None):
    """Return the shared session state using the configured server timezone.

    The start boundary is inclusive and the end boundary is exclusive. An
    incomplete legacy schedule fails closed; instructors can set it on the
    session edit page and all linked assignments take effect immediately.
    """
    current_tz = timezone.get_current_timezone()
    now = timezone.localtime(now or timezone.now(), current_tz)
    schedule = (session.session_date, session.start_time, session.end_time)
    if not all(schedule):
        return _unconfigured_window(now)

    start_at = timezone.make_aware(
        datetime.combine(session.session_date, session.start_time), current_tz)
    end_at = timezone.make_aware(
        datetime.combine(session.session_date, session.end_time), current_tz)
    if end_at <= start_at:
        return _unconfigured_window(now)

    if now < start_at:
        state = 'upcoming'
        display_start = start_at.strftime('%b %d, %Y %I:%M %p').replace(' 0', ' ')
        message = (
            'Your session has not started yet. Please wait until the scheduled '
            f'start time. Scheduled start time: {display_start}.')
    elif now >= end_at:
        state = 'expired'
        message = (
            'This session has ended. Access to your assigned task is no longer '
            'available.')
    else:
        state = 'available'
        message = (
            'Session is active until '
            f"{end_at.strftime('%b %d, %Y %I:%M %p').replace(' 0', ' ')}")

    return {
        'state': state,
        'can_start': state == 'available',
        'start_at': start_at.isoformat(),
        'end_at': end_at.isoformat(),
        'server_now': now.isoformat(),
        'message': message,
    }


def task_window_for(assignment, now=None):
    """Return the access state shared by every assignment in its session.

    Session-linked assignments always use the shared session schedule. A
    sessionless record is a legacy assignment from before sessions existed; keep
    its historical window behavior for compatibility while all new assignments
    are created inside scheduled sessions.
    """
    session = getattr(assignment, 'session', None) if assignment is not None else None
    if session is None:
        legacy_schedule = (
            getattr(assignment, 'simulation_date', None),
            getattr(assignment, 'start_time', None),
            getattr(assignment, 'end_time', None),
        )
        if all(legacy_schedule):
            session = SimpleNamespace(
                session_date=legacy_schedule[0],
                start_time=legacy_schedule[1],
                end_time=legacy_schedule[2],
            )
            return session_window_for(session, now=now)
        current_tz = timezone.get_current_timezone()
        current = timezone.localtime(now or timezone.now(), current_tz)
        return {
            'state': 'unscheduled',
            'can_start': True,
            'start_at': '',
            'end_at': '',
            'server_now': current.isoformat(),
            'message': '',
        }
    return session_window_for(session, now=now)
