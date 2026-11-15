"""Time-window helpers for scheduled simulation assignments."""

from datetime import datetime

from django.utils import timezone


def task_window_for(assignment, now=None):
    """Return the authoritative execution state for an assignment's schedule.

    Assignments without a complete schedule keep their existing unrestricted
    behavior. Scheduled wall-clock times are interpreted in the project's
    current timezone and use an inclusive start, exclusive end boundary.
    """
    schedule_values = (
        assignment.simulation_date, assignment.start_time, assignment.end_time,
    )
    if not any(schedule_values):
        return {
            'state': 'unscheduled', 'can_start': True,
            'start_at': '', 'end_at': '', 'server_now': '',
            'message': '',
        }

    if not all(schedule_values):
        now = timezone.localtime(now or timezone.now(), timezone.get_current_timezone())
        return {
            'state': 'expired', 'can_start': False,
            'start_at': '', 'end_at': '', 'server_now': now.isoformat(),
            'message': 'This task has an incomplete schedule and is locked. Contact your instructor.',
        }

    current_tz = timezone.get_current_timezone()
    start_at = timezone.make_aware(
        datetime.combine(assignment.simulation_date, assignment.start_time), current_tz)
    end_at = timezone.make_aware(
        datetime.combine(assignment.simulation_date, assignment.end_time), current_tz)
    now = timezone.localtime(now or timezone.now(), current_tz)

    if now < start_at:
        state = 'upcoming'
        message = f"This task becomes available at {start_at.strftime('%b %d, %Y %I:%M %p').lstrip('0')}."
    elif now >= end_at:
        state = 'expired'
        message = 'The assigned task time window has ended.'
    else:
        state = 'available'
        message = f"Available until {end_at.strftime('%b %d, %Y %I:%M %p').lstrip('0')}."

    return {
        'state': state,
        'can_start': state == 'available',
        'start_at': start_at.isoformat(),
        'end_at': end_at.isoformat(),
        'server_now': now.isoformat(),
        'message': message,
    }
