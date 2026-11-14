"""Time-window helpers for scheduled simulation assignments."""

from datetime import datetime, time, timedelta

from django.utils import timezone


def task_window_for(assignment, now=None):
    """Return the authoritative execution state for an assignment's schedule.

    Assignments without an assigned date keep their existing unrestricted
    behavior. Scheduled wall-clock times use the project's current timezone
    and retain an inclusive start, exclusive end boundary.
    """
    if not assignment.simulation_date:
        return {
            'state': 'unscheduled', 'can_start': True,
            'start_at': '', 'end_at': '', 'server_now': '',
            'message': '',
        }

    current_tz = timezone.get_current_timezone()
    now = timezone.localtime(now or timezone.now(), current_tz)
    day_end = datetime.combine(
        assignment.simulation_date + timedelta(days=1), time.min)
    start_at = timezone.make_aware(datetime.combine(
        assignment.simulation_date, assignment.start_time or time.min), current_tz)
    end_at = timezone.make_aware(
        datetime.combine(assignment.simulation_date, assignment.end_time)
        if assignment.end_time else day_end,
        current_tz,
    )

    if now.date() < assignment.simulation_date:
        state = 'upcoming'
        message = (
            f"This task becomes available at {start_at.strftime('%b %d, %Y %I:%M %p').lstrip('0')}."
            if assignment.start_time else
            f"This task becomes available on {assignment.simulation_date.strftime('%b %d, %Y').lstrip('0')}."
        )
    elif now.date() > assignment.simulation_date:
        state = 'expired'
        message = 'The assigned task time window has ended.'
    elif not (assignment.start_time and assignment.end_time):
        if now < start_at:
            state = 'upcoming'
            message = f"This task becomes available at {start_at.strftime('%b %d, %Y %I:%M %p').lstrip('0')}."
        elif now >= end_at:
            state = 'expired'
            message = 'The assigned task time window has ended.'
        else:
            state = 'available'
            message = f"Available until {end_at.strftime('%b %d, %Y %I:%M %p').lstrip('0')}."
    else:
        # Keep the existing Start Time and End Time rules for complete schedules.
        start_at = timezone.make_aware(
            datetime.combine(assignment.simulation_date, assignment.start_time), current_tz)
        end_at = timezone.make_aware(
            datetime.combine(assignment.simulation_date, assignment.end_time), current_tz)

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

