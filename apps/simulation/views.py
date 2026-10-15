import json

from django.contrib import messages
from django.contrib.auth import get_user_model
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.db.models import Count, Max, Prefetch, Q
from django.http import HttpResponseForbidden, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone

from establishments.models import Establishment

from atrue_core.decorators import manager_required
from atrue_core.services import is_manager, log_activity

from .models import (
    ActivityLog, BILLING_OFFICER_ROLE_CODES, Role, SimulationRoleAssignment,
    SimulationSession,
)
from .role_catalogue import (
    ACTIVITY_ROLE_CODES,
    active_entries,
    missing_active_codes,
    sync_activity_roles,
    sync_roles,
)
from .task_routing import (
    TASK_ASSIGNMENT_SESSION_KEY,
    GUEST_MODULES,
    operation_with_urls,
    task_operation_for,
)


def _is_instructor(user):
    return user.is_staff or user.account_type in ('INSTRUCTOR', 'ADMIN', 'SYSTEM_ADMIN')


@login_required
def do_task(request, assignment_id):
    """Show the operations entry point for one of the student's assignments.

    The assignment is looked up through ``request.user.simulation_roles`` so the
    student cannot reach another student's task by guessing the id, and only
    ACTIVE assignments start. The assignment context is saved in this tab's
    private Django session so operation views can enforce its role and
    establishment on every subsequent request.
    """
    assignment = get_object_or_404(
        request.user.simulation_roles.select_related(
            'hotel', 'establishment', 'role_ref',
        ),
        pk=assignment_id,
        status=SimulationRoleAssignment.AssignmentStatus.ACTIVE,
    )
    operation = task_operation_for(assignment)
    if operation is None:
        messages.error(
            request,
            'There is no operations module available for this role and establishment.',
        )
        return redirect('simulation:workspace')

    request.session[TASK_ASSIGNMENT_SESSION_KEY] = assignment.pk
    operation = operation_with_urls(assignment, operation)

    log_activity(
        request.user, "Started simulation task",
        f"{assignment.get_role_display()} at "
        f"{assignment.establishment.name if assignment.establishment_id else assignment.hotel.name if assignment.hotel_id else 'n/a'}",
        session=assignment.session,
    )
    return render(request, 'simulation/task_operations.html', {
        'assignment': assignment,
        'operation': operation,
    })


@login_required
def workspace(request):
    is_instructor = _is_instructor(request.user)
    modal_context = {}

    if is_instructor:
        roles = SimulationRoleAssignment.objects.select_related(
            'student', 'assigned_by', 'session', 'hotel',
        ).all()
        sessions = list(SimulationSession.objects.prefetch_related(Prefetch(
            'assignments',
            queryset=SimulationRoleAssignment.objects.select_related(
                'student', 'assigned_by', 'hotel', 'role_ref',
            ),
        )))
        # The session page is the class roster: every student gets a row in each
        # session -- whether or not they already hold a role there -- so the
        # instructor can see at a glance who still needs an assignment.
        roster = list(_load_students(request))
        _attach_session_student_rows(sessions, roster)
        modal_context = {
            'student_roles_map': _student_roles_map(roster),
            **_assignment_picker_data(),
        }
    else:
        roles = request.user.simulation_roles.select_related(
            'assigned_by', 'session', 'hotel', 'role_ref',
        ).all()
        sessions = SimulationSession.objects.filter(
            assignments__student=request.user,
        ).distinct().prefetch_related(Prefetch(
            'assignments',
            queryset=SimulationRoleAssignment.objects.filter(
                student=request.user,
            ).select_related('student', 'assigned_by', 'hotel', 'role_ref'),
        ))
        students = None
        if request.method == 'POST' and request.POST.get('action') == 'deactivate':
            role = get_object_or_404(
                request.user.simulation_roles, pk=request.POST.get('role_id')
            )
            role.status = SimulationRoleAssignment.AssignmentStatus.INACTIVE
            role.save(update_fields=['status'])
            log_activity(request.user, "Deactivated own simulation role", role.get_role_display(),
                         session=role.session)
            messages.success(request, "Role deactivated.")
            return redirect('simulation:workspace')
    return render(request, 'simulation/workspace.html', {
        'roles': roles,
        'legacy_roles': roles.filter(session__isnull=True),
        'sessions': sessions,
        'is_instructor': is_instructor,
        'can_manage_all_sessions': is_manager(request.user),
        **modal_context,
    })


@login_required
def add_session(request):
    if not _is_instructor(request.user):
        return redirect('simulation:workspace')

    if request.method == 'POST':
        name = (request.POST.get('name') or '').strip()
        description = (request.POST.get('description') or '').strip()
        if not name:
            messages.error(request, 'Enter a name for the session.')
            return render(request, 'simulation/add_session.html', {
                'name': name, 'description': description, 'error': 'Enter a name for the session.',
            })
        if len(name) > 150:
            messages.error(request, 'Session names must be 150 characters or fewer.')
            return render(request, 'simulation/add_session.html', {
                'name': name, 'description': description, 'error': 'Session names must be 150 characters or fewer.',
            })

        session = SimulationSession.objects.create(
            name=name,
            description=description,
            instructor=request.user,
        )
        log_activity(request.user, 'Created simulation session', session.name, session=session)
        messages.success(request, f'{session.name} created. Add activities from its session card.')
        return redirect('simulation:workspace')

    return render(request, 'simulation/add_session.html')


@login_required
def update_session(request, session_id):
    """FR Update Simulation Session – instructor edits an existing session.

    Only the session's own instructor (or a manager) may edit it, and only the
    editable fields change: name, description, the optional date window and the
    status. Assignments and transactions are untouched - a session edit must not
    re-point the students already working inside it.
    """
    if not _is_instructor(request.user):
        return redirect('simulation:workspace')
    session = get_object_or_404(SimulationSession, pk=session_id)
    if session.instructor_id != request.user.pk and not is_manager(request.user):
        messages.error(request, "You may only edit sessions you created.")
        return redirect('simulation:workspace')

    if request.method == 'POST':
        name = (request.POST.get('name') or '').strip()
        description = (request.POST.get('description') or '').strip()
        start_date = (request.POST.get('start_date') or '').strip() or None
        end_date = (request.POST.get('end_date') or '').strip() or None
        status = (request.POST.get('status') or '').strip()

        errors = []
        if not name:
            errors.append('Enter a name for the session.')
        if len(name) > 150:
            errors.append('Session names must be 150 characters or fewer.')
        if status not in SimulationSession.Status.values:
            errors.append('Select a valid session status.')
        try:
            import datetime
            parsed = (
                datetime.date.fromisoformat(start_date) if start_date else None,
                datetime.date.fromisoformat(end_date) if end_date else None,
            )
        except ValueError:
            errors.append('Enter valid start and end dates.')
        else:
            start_date, end_date = parsed
            if start_date and end_date and end_date < start_date:
                errors.append('The end date cannot be earlier than the start date.')

        if errors:
            for error in errors:
                messages.error(request, error)
            return render(request, 'simulation/update_session.html', {
                'session': session,
                'name': name,
                'description': description,
                'start_date': start_date.isoformat() if start_date else '',
                'end_date': end_date.isoformat() if end_date else '',
                'status_values': SimulationSession.Status.values,
            })

        session.name = name
        session.description = description
        session.start_date = start_date
        session.end_date = end_date
        previous_status = session.status
        if status == SimulationSession.Status.ACTIVE and previous_status != status:
            session.activate()
        elif status == SimulationSession.Status.COMPLETED and previous_status != status:
            session.complete()
        else:
            session.status = status
        try:
            session.full_clean(exclude=['session_id', 'instructor', 'created_at',
                                        'updated_at', 'activated_at', 'completed_at'])
            session.save()
        except ValidationError:
            messages.error(
                request,
                'This session starts in the future. Leave it Scheduled until it '
                'actually begins.')
            return render(request, 'simulation/update_session.html', {
                'session': session,
                'name': name,
                'description': description,
                'start_date': start_date.isoformat() if start_date else '',
                'end_date': end_date.isoformat() if end_date else '',
                'status_values': SimulationSession.Status.values,
            })
        log_activity(request.user, 'Updated simulation session', session.name, session=session)
        messages.success(request, f'{session.name} updated.')
        return redirect('simulation:workspace')

    return render(request, 'simulation/update_session.html', {
        'session': session,
        'name': session.name,
        'description': session.description,
        'start_date': session.start_date.isoformat() if session.start_date else '',
        'end_date': session.end_date.isoformat() if session.end_date else '',
        'status_values': SimulationSession.Status.values,
    })


def _load_students(request):
    from accounts.models import User
    return User.objects.filter(account_type=User.AccountType.STUDENT).order_by('username')


def _parse_schedule(date_str, start_str, end_str):
    """Validate the optional simulation window.

    Returns the model kwargs on success, or an error message string. All three
    fields travel together: a date with no times (or vice versa) would describe
    a window the platform cannot enforce, so a partial schedule is rejected
    rather than silently stored as "no schedule".
    """
    import datetime

    values = (date_str, start_str, end_str)
    if not any(values):
        return {}
    if not all(values):
        return "Set the simulation date, start time and end time together."

    try:
        sim_date = datetime.date.fromisoformat(date_str)
    except ValueError:
        return "Enter a valid simulation date."
    try:
        start = datetime.time.fromisoformat(start_str)
        end = datetime.time.fromisoformat(end_str)
    except ValueError:
        return "Enter valid start and end times."

    if start >= end:
        return "The end time must be later than the start time."

    return {'simulation_date': sim_date, 'start_time': start, 'end_time': end}


def _active_hotels():
    from hotels.models import Hotel
    return Hotel.objects.filter(status='ACTIVE').order_by('name')


def _student_display_name(student):
    """The student's name as an instructor reads it on a roster.

    ``User.get_full_name`` drops the middle name, but a class list usually
    shows it ("Arlyne Joy Udaundo"), and the admin types what they see.
    """
    parts = [student.first_name, student.middle_name, student.last_name]
    joined = ' '.join(p for p in parts if p).strip()
    return joined or student.username


def _student_search_keys(student):
    """The strings the admin may type to find ``student``.

    A single keystroke should already narrow the list, and "Ar" or "AJ" should
    both find Arlyne Joy Udaundo. The key therefore carries the full name, the
    name reversed (surname-first, as it is often written on a roster), the
    initials and the username, all lower-cased.
    """
    first = (student.first_name or '').strip()
    middle = (student.middle_name or '').strip()
    last = (student.last_name or '').strip()
    full = _student_display_name(student)
    initials = ''.join(part[0] for part in (first, middle, last) if part)
    parts = [
        full,
        f"{last} {first} {middle}".strip(),
        f"{first} {last}".strip(),
        initials,
        student.username,
    ]
    return ' '.join(p for p in parts if p).lower()


def _resolve_student(raw_id):
    """Turn a posted id into a real student, or ``None``.

    The Student box is a free-text autocomplete, so this field is untrusted: it
    can be blank, non-numeric (someone typed a name), or a valid number for a
    deleted row. Only a genuine student id is accepted -- the typed text is
    never treated as a student.
    """
    try:
        pk = int(str(raw_id).strip())
    except (TypeError, ValueError):
        return None
    return get_user_model().objects.filter(pk=pk).first()


def _establishments_for_type(establishment_type):
    """The selectable establishments of one type, for the dynamic picker."""
    if not establishment_type:
        return Establishment.objects.none()
    return Establishment.objects.filter(
        type=establishment_type, status=Establishment.Status.ACTIVE,
    ).order_by('name')


def _resolve_establishment(raw_id, establishment_type):
    """Turn a posted establishment id into a real row *of the expected type*.

    The establishment box is a client-side picker fed from the database, so it is
    untrusted input: a hand-edited POST can name any id, including an airline
    when a hotel role was chosen. Scoping the lookup to ``establishment_type``
    means a mismatch is simply "not found", so it can never be stored.
    """
    try:
        pk = int(str(raw_id).strip())
    except (TypeError, ValueError):
        return None
    return _establishments_for_type(establishment_type).filter(pk=pk).first()


def _offered_roles():
    """``{code: Role}`` for every role the assign form is allowed to offer.

    The catalogue decides what is *offered*, the ``Role`` table decides what can be
    *stored* (an assignment keeps the role as a code *and* as a foreign key). The
    two normally agree because ``simulation.migrations`` syncs the catalogue into
    the table, but a database that has not taken that migration yet -- or a role
    added to the catalogue since -- leaves the table short a row. Reading only the
    catalogue then lists a role the POST handler rejects as "Select a valid role.",
    which is exactly what the instructor saw.

    So the row is created on demand rather than left missing: the catalogue is the
    source of truth, and this keeps the form and the validator agreeing without
    asking anyone to run anything.
    """
    catalogue = active_entries()
    codes = [entry[0] for entry in catalogue]
    missing = set(missing_active_codes())
    if missing:
        if missing.issubset(ACTIVITY_ROLE_CODES):
            sync_activity_roles()
        else:
            sync_roles()
    return {
        role.code: role
        for role in Role.objects.filter(code__in=codes, is_active=True)
    }


def _assignable_roles(offered=None):
    """``(code, label, establishment_type)`` for every role still on offer.

    Driven by the catalogue rather than ``SimulationRoleAssignment.Role.choices``
    so a retired role stops appearing on the form. Only codes with a live ``Role``
    row are returned, so anything this function lists is something the view will
    accept; the label comes from that row, so renaming a role renames it here too.
    """
    if offered is None:
        offered = _offered_roles()
    return [
        (
            code,
            offered[code].name if code in offered else label,
            (None if code.endswith('_OWNER') else
             Role.ESTABLISHMENT_TYPE_MAP.get(establishment_type)),
        )
        for code, label, _category, establishment_type, _operation, _order
        in active_entries()
        if code in offered
    ]


def _guest_destination_types():
    """``{role code: establishment type}`` for guest roles an instructor may
    attach a place to ("Do the Task" then deep-links the student onto it)."""
    return {
        code: module['establishment_type']
        for code, module in GUEST_MODULES.items()
        if module['establishment_type'] and module['detail_route']
    }


def _initials(student):
    """A one- or two-character avatar label for the class roster."""
    first = (student.first_name or '').strip()
    last = (student.last_name or '').strip()
    initials = (first[:1] + last[:1]).strip()
    if not initials:
        initials = (student.username or '?')[:1]
    return initials.upper()


def _attach_session_student_rows(sessions, students):
    """Give every session a row per student for the expandable class list.

    The session page shows the whole class: a student with no assignment in a
    session still gets a row labelled "No role assigned" so the instructor can
    place them. A student may hold more than one role in the same session (the
    assign form allows a deliberate re-run), so the row shows the most
    significant assignment -- a live one beats a finished one, and the most
    recent wins a tie -- and notes how many others sit behind it.
    """
    sessions = list(sessions)
    students = list(students)
    by_session = {}
    counts = {}
    if sessions:
        assignments = (
            SimulationRoleAssignment.objects
            .filter(session__in=sessions)
            .select_related('establishment', 'hotel', 'role_ref')
            .order_by('assigned_at', 'pk')
        )
        priority = {'ACTIVE': 3, 'DONE': 2, 'INACTIVE': 1}
        for assignment in assignments:
            key = (assignment.session_id, assignment.student_id)
            counts[key] = counts.get(key, 0) + 1
            current = by_session.setdefault(assignment.session_id, {}).get(assignment.student_id)
            if (current is None
                    or priority.get(assignment.status, 0)
                    >= priority.get(current.status, 0)):
                by_session[assignment.session_id][assignment.student_id] = assignment
    for session in sessions:
        bucket = by_session.get(session.pk, {})
        session.student_rows = [
            {
                'student': student,
                'assignment': bucket.get(student.pk),
                'count': counts.get((session.pk, student.pk), 0),
                'initials': _initials(student),
                'display_name': _student_display_name(student),
                'username': student.username,
            }
            for student in students
        ]
        session.student_count = len(students)
    return sessions


def _student_roles_map(students):
    """``{student id: [assignment summary, ...]}`` for the modal-clash prompt.

    The browser uses this to warn -- and offer the "assign this role again"
    override -- before a role the student already holds live elsewhere is posted.
    The server re-checks the same rule, so this is a convenience, not the guard.
    """
    return {
        s.id: [
            {
                'id': a.pk,
                'value': a.role,
                'role': a.get_role_display(),
                'activity': a.activity_name,
                'status': a.get_status_display(),
                'active': a.status == SimulationRoleAssignment.AssignmentStatus.ACTIVE,
                'completed': a.status == SimulationRoleAssignment.AssignmentStatus.DONE,
                'date': a.assigned_at.strftime('%b %d, %Y'),
            }
            for a in s.simulation_roles.all()
        ]
        for s in students
    }


def _student_options(students):
    return [
        {
            'id': s.id,
            'name': _student_display_name(s),
            'username': s.username,
            'search': _student_search_keys(s),
        }
        for s in students
    ]


def _assignment_picker_data():
    """The role/establishment picker data the assign form and the modal share."""
    assignable_roles = _assignable_roles()
    return {
        'role_choices': assignable_roles,
        'role_establishment_types': {
            code: establishment_type
            for code, _label, establishment_type in assignable_roles
        },
        'guest_destinations': _guest_destination_types(),
        'establishment_types': [
            {'value': value, 'label': label}
            for value, label in Establishment.Type.choices
        ],
        'establishments_by_type': {
            value: [
                {'id': establishment.pk, 'name': establishment.name}
                for establishment in _establishments_for_type(value)
            ]
            for value, _label in Establishment.Type.choices
        },
    }


def _assignment_json(assignment):
    """One assignment as the JSON the session-page modal refreshes its row with."""
    def clock(value):
        return value.strftime('%H:%M') if value else ''

    time_display = ''
    if assignment.start_time and assignment.end_time:
        time_display = (
            f"{assignment.start_time.strftime('%I:%M %p').lstrip('0')} – "
            f"{assignment.end_time.strftime('%I:%M %p').lstrip('0')}"
        )
    return {
        'id': assignment.pk,
        'student_id': assignment.student_id,
        'student_name': _student_display_name(assignment.student),
        'role': assignment.role,
        'role_display': assignment.get_role_display(),
        'establishment_id': assignment.establishment_id or '',
        'establishment': assignment.establishment.name if assignment.establishment_id else None,
        'activity_name': assignment.activity_name,
        'simulation_date': assignment.simulation_date.isoformat() if assignment.simulation_date else '',
        'date_display': assignment.simulation_date.strftime('%b %d, %Y') if assignment.simulation_date else '',
        'start_time': clock(assignment.start_time),
        'end_time': clock(assignment.end_time),
        'time_display': time_display,
        'status': assignment.status,
        'status_display': assignment.get_status_display(),
        'assigned_by_display': (
            _student_display_name(assignment.assigned_by)
            if assignment.assigned_by_id else 'Not assigned'
        ),
        'assigned_at_display': assignment.assigned_at.strftime('%b %d, %Y %H:%M'),
        'assignment_count': SimulationRoleAssignment.objects.filter(
            student_id=assignment.student_id, session_id=assignment.session_id,
        ).count(),
        'view_url': reverse('simulation:role_detail', args=[assignment.pk]),
        'unassign_url': reverse('simulation:unassign', args=[assignment.pk]),
    }


@login_required
def assign_role(request):
    """Instructor creates a simulation session and places a student in it.

    The four inputs are independent: ``activity_name`` is the instructor's own
    label for the session (free text, shared by every student in it), ``role``
    is what the student performs, ``hotel`` is where a hotel role happens, and
    the schedule is the window it is allowed to run in. Naming an activity
    never implies a role, venue or time.
    """
    if not _is_instructor(request.user):
        return redirect('simulation:workspace')
    session_id = request.GET.get('session') or request.POST.get('session')
    selected_session = None
    if session_id:
        selected_session = get_object_or_404(SimulationSession, pk=session_id)
        if selected_session.instructor_id != request.user.id and not is_manager(request.user):
            messages.error(request, 'Only the instructor responsible for this session can add activities.')
            return redirect('simulation:workspace')
        if selected_session.status in {
            SimulationSession.Status.COMPLETED,
            SimulationSession.Status.ARCHIVED,
        }:
            messages.error(request, 'Completed or archived sessions cannot accept new activities.')
            return redirect('simulation:workspace')
    if request.method == 'POST':
        # A rejected submission comes back to the form with everything the
        # instructor had already chosen still filled in, rather than as a fresh
        # blank page that silently drops the student, role, establishment and
        # schedule they had just typed.
        def again(message):
            messages.error(request, message)
            return _assign_page(request, selected_session)

        student_id = request.POST.get('student')
        role = (request.POST.get('role') or '').strip()
        activity_name = (request.POST.get('activity_name') or '').strip()
        establishment_id = (request.POST.get('establishment') or '').strip()
        sim_date = (request.POST.get('simulation_date') or '').strip()
        start_time = (request.POST.get('start_time') or '').strip()
        end_time = (request.POST.get('end_time') or '').strip()

        if not activity_name:
            return again("Name the activity.")
        if not student_id or not role:
            return again("Select a student and a role.")

        # Both ids arrive from hidden fields, so they are untrusted input: the
        # student box is free text and the establishment box is client-side
        # optional. Resolve them to real rows here rather than letting create()
        # raise an IntegrityError/ValueError and return a 500.
        student = _resolve_student(student_id)
        if student is None:
            return again("Select a student from the list.")

        offered = _offered_roles()
        role_row = offered.get(role)
        if role_row is None:
            # The form only lists codes from ``offered``, so reaching here means
            # the POST was not one this form could have produced: a retired role,
            # an administrative role, a stale page, or a scripted client.
            return again("Select a valid role.")

        # The establishment the role belongs to. Resolving it *through* the
        # role's own type is what makes "Hotel Manager + Cebu Pacific" impossible
        # rather than merely discouraged.
        if role_row.requires_establishment and not role_row.code.endswith('_OWNER'):
            if not establishment_id:
                return again(
                    f"{role_row.name} is performed inside an establishment, so select "
                    f"the one this student will work at."
                )
            establishment = _resolve_establishment(
                establishment_id, role_row.establishment_category)
            if establishment is None:
                return again(
                    f"Select an active {role_row.get_establishment_category_display()} "
                    "from the list.")
            # The legacy hotel column is a mirror kept for the older templates and
            # atrue_core.hotel_scope; only set it for an actual hotel.
            hotel = establishment.entity if establishment.type == Establishment.Type.HOTEL else None
        elif role_row.code in _guest_destination_types():
            # A guest is still performed outside an establishment, so this is
            # deliberately *optional*: the instructor can point the guest at one
            # specific place so "Do the Task" lands on it, or leave it empty to
            # let them browse the whole module.
            if establishment_id:
                guest_type = _guest_destination_types()[role_row.code]
                establishment = _resolve_establishment(establishment_id, guest_type)
                if establishment is None:
                    label = dict(Establishment.Type.choices).get(
                        guest_type, guest_type).lower()
                    return again(
                        f"Select an active {label} from the list, or leave it "
                        "empty to let the guest browse all."
                    )
            else:
                establishment = None
            hotel = None
        else:
            # A customer or administrative role is performed outside an
            # establishment. The form clears this in JS, but the server must not
            # trust that: a stray establishment on, say, a Passenger assignment
            # would feed the scoping helpers and hand the student access they
            # were never given.
            establishment = None
            hotel = None

        # A student should not hold the same role in two live sessions, but the
        # instructor may deliberately re-run a role (a repeat drill, a second
        # group). Only ACTIVE assignments count: a finished one is history and
        # must not block the student from being assessed again later.
        active_status = SimulationRoleAssignment.AssignmentStatus.ACTIVE
        target_session = selected_session
        if target_session is None:
            target_session = SimulationSession.objects.filter(
                name=activity_name,
                instructor=request.user,
                status__in=(
                    SimulationSession.Status.DRAFT,
                    SimulationSession.Status.SCHEDULED,
                    SimulationSession.Status.ACTIVE,
                ),
            ).first()
        if target_session and SimulationRoleAssignment.objects.filter(
                student=student,
                session=target_session,
                status=SimulationRoleAssignment.AssignmentStatus.DONE,
        ).exists():
            return again("This student has already completed this activity.")

        clash = list(SimulationRoleAssignment.objects.filter(
            student_id=student.pk, role=role, status=active_status
        ).order_by('-assigned_at'))
        repeat_override = request.POST.get('assign_again') == 'yes'
        if clash and not repeat_override:
            return again(
                f"{clash[0].get_role_display()} is already an active assignment for this "
                f"student in “{clash[0].activity_name}”. Tick “Assign this role again” to "
                f"put them in this session as well."
            )

        # A posted ``hotel_id`` is no longer consulted. Every role that is
        # performed inside a hotel now names its establishment above, so a stray
        # id from an older form is ignored rather than being allowed to pick the
        # place the student works.

        schedule = _parse_schedule(sim_date, start_time, end_time)
        if isinstance(schedule, str):
            return again(schedule)

        if selected_session is None:
            selected_session = SimulationSession.objects.filter(
                name=activity_name,
                instructor=request.user,
                status__in=(
                    SimulationSession.Status.DRAFT,
                    SimulationSession.Status.SCHEDULED,
                    SimulationSession.Status.ACTIVE,
                ),
            ).first()
            if selected_session is None:
                selected_session = SimulationSession.objects.create(
                    name=activity_name,
                    instructor=request.user,
                )

        assignment = SimulationRoleAssignment.objects.create(
            student=student,
            assigned_by=request.user,
            role=role,
            role_ref=role_row,
            activity_name=activity_name,
            session=selected_session,
            establishment=establishment,
            hotel=hotel,
            **schedule,
        )
        role_label = SimulationRoleAssignment(role=role).get_role_display()
        log_activity(request.user, f"Assigned {role} role",
                     f"{activity_name} — {role_label}",
                     session=selected_session)
        if repeat_override and clash:
            # Deliberate override of the one-active-role-per-session rule, so
            # leave a trail naming the sessions it was duplicated from.
            log_activity(
                request.user, "Re-assigned an already active role",
                f"{role_label} repeated in {activity_name} (already active in "
                + "; ".join(f"{a.activity_name}, {a.assigned_at:%b %d, %Y}" for a in clash)
                + ")",
                session=selected_session,
            )
            messages.warning(
                request,
                f"{role_label} is now active in {len(clash) + 1} sessions for this student.",
            )
        else:
            messages.success(request, f"{activity_name} assigned successfully.")
        return redirect('simulation:workspace')

    return _assign_page(request, selected_session)


def _assign_page(request, selected_session):
    """Render the assign form, optionally re-filling a rejected submission.

    ``request.POST`` is passed straight through as ``posted`` so every field the
    instructor had filled in survives a validation failure. The student field is
    an id in a hidden box with a free-text mirror next to it, so the visible text
    has to be rebuilt from the row or the two halves disagree on redisplay.
    """
    students = list(_load_students(request).prefetch_related('simulation_roles'))
    student_options = students
    if selected_session is not None:
        completed_student_ids = set(SimulationRoleAssignment.objects.filter(
            session=selected_session,
            status=SimulationRoleAssignment.AssignmentStatus.DONE,
        ).values_list('student_id', flat=True))
        student_options = [student for student in students
                           if student.id not in completed_student_ids]
    posted = getattr(request, 'POST', None) or None
    posted_student_name = ''
    if posted:
        resolved_student = _resolve_student(posted.get('student'))
        if resolved_student is not None:
            posted_student_name = _student_display_name(resolved_student)
    # These must be real Python objects, not pre-serialised JSON strings.
    # ``json_script`` runs ``json.dumps`` itself, so handing it a string emits that
    # string *quoted*, and the browser's JSON.parse then yields a str instead of a
    # list/dict -- which throws on the first .filter() and silently kills every
    # listener bound after it.
    context = {
        'session': selected_session,
        'students': students,
        'posted': posted,
        'posted_student_name': posted_student_name,
        'hotels': _active_hotels(),
        'student_roles': _student_roles_map(students),
        'student_options': _student_options(student_options),
    }
    # ``role_choices``/``role_establishment_types``/``guest_destinations``/
    # ``establishment_types``/``establishments_by_type`` come from the shared
    # picker helper so the assign form and the session-page modal cannot drift.
    context.update(_assignment_picker_data())
    return render(request, 'simulation/assign_role.html', context)


@login_required
def unassign_role(request, assignment_id):
    if not _is_instructor(request.user):
        return redirect('simulation:workspace')
    assignment = get_object_or_404(SimulationRoleAssignment, pk=assignment_id)
    if assignment.status != SimulationRoleAssignment.AssignmentStatus.ACTIVE:
        messages.info(request, "Only active role assignments can be marked as done.")
        return redirect('simulation:workspace')
    assignment.status = SimulationRoleAssignment.AssignmentStatus.DONE
    assignment.completed_at = timezone.now()
    assignment.save(update_fields=['status', 'completed_at'])
    log_activity(request.user, "Marked simulation role as done",
                 f"{assignment.get_role_display()} for {assignment.student.get_full_name()}",
                 session=assignment.session)
    if request.headers.get('x-requested-with') == 'XMLHttpRequest':
        return JsonResponse({'ok': True, 'status': 'DONE', 'message': 'Role marked as done.'})
    messages.success(request, "Role marked as done.")
    return redirect('simulation:workspace')


@login_required
def session_assignment(request, session_id):
    """Create or update one student's assignment from the session-page modal.

    The session page lists the whole class, so a row posts here either to place
    an unassigned student (no ``assignment_id``) or to edit the assignment that is
    already theirs. The reply is JSON so the page can refresh just that one row
    instead of navigating away.

    Every rule the standalone assign form enforces is applied here through the
    same helpers -- the live role catalogue, the role/establishment-type
    agreement, the schedule rules and the one-active-role-per-student clash -- so
    the modal cannot become a way around them.
    """
    if request.method != 'POST':
        return JsonResponse(
            {'ok': False, 'errors': ['Save the form to update this student.']},
            status=405,
        )
    if not _is_instructor(request.user):
        return JsonResponse(
            {'ok': False, 'errors': ['Only instructors can assign simulation roles.']},
            status=403,
        )

    session = get_object_or_404(SimulationSession, pk=session_id)
    if session.instructor_id != request.user.id and not is_manager(request.user):
        return JsonResponse(
            {'ok': False, 'errors': [
                'Only the instructor responsible for this session can assign roles.']},
            status=403,
        )
    if session.status in {
        SimulationSession.Status.COMPLETED,
        SimulationSession.Status.ARCHIVED,
    }:
        return JsonResponse(
            {'ok': False, 'errors': ['Completed or archived sessions cannot be changed.']},
            status=400,
        )

    def fail(messages_, clash=False, status=400):
        return JsonResponse({'ok': False, 'errors': list(messages_), 'clash': clash}, status=status)

    assignment_id = (request.POST.get('assignment_id') or '').strip()
    role = (request.POST.get('role') or '').strip()
    establishment_id = (request.POST.get('establishment') or '').strip()
    sim_date = (request.POST.get('simulation_date') or '').strip()
    start_time = (request.POST.get('start_time') or '').strip()
    end_time = (request.POST.get('end_time') or '').strip()
    repeat_override = request.POST.get('assign_again') == 'yes'

    existing = None
    if assignment_id:
        existing = get_object_or_404(
            SimulationRoleAssignment, pk=assignment_id, session=session)
        if existing.status == SimulationRoleAssignment.AssignmentStatus.DONE:
            return fail(['Completed role assignments cannot be edited.'])
        student = existing.student
    else:
        student = _resolve_student(request.POST.get('student'))
        if student is None:
            return fail(['Select a student from the list.'])

    offered = _offered_roles()
    role_row = offered.get(role)
    if role_row is None:
        return fail(['Select a valid role.'])

    # Role + establishment agreement, mirrored from ``assign_role`` so both doors
    # into the assignment table resolve the posted id instead of trusting it.
    if role_row.requires_establishment and not role_row.code.endswith('_OWNER'):
        if not establishment_id:
            return fail([
                f"{role_row.name} is performed inside an establishment, so select "
                f"the one this student will work at."])
        establishment = _resolve_establishment(
            establishment_id, role_row.establishment_category)
        if establishment is None:
            return fail([
                f"Select an active {role_row.get_establishment_category_display()} "
                "from the list."])
        hotel = establishment.entity if establishment.type == Establishment.Type.HOTEL else None
    elif role_row.code in _guest_destination_types():
        if establishment_id:
            guest_type = _guest_destination_types()[role_row.code]
            establishment = _resolve_establishment(establishment_id, guest_type)
            if establishment is None:
                label = dict(Establishment.Type.choices).get(
                    guest_type, guest_type).lower()
                return fail([
                    f"Select an active {label} from the list, or leave it empty to "
                    "let the guest browse all."])
        else:
            establishment = None
        hotel = None
    else:
        establishment = None
        hotel = None

    schedule = _parse_schedule(sim_date, start_time, end_time)
    if isinstance(schedule, str):
        return fail([schedule])

    # One live role per student, unless the instructor deliberately repeats it.
    # The row being edited is excluded so re-saving it is never a self-clash.
    active_status = SimulationRoleAssignment.AssignmentStatus.ACTIVE
    clash_qs = SimulationRoleAssignment.objects.filter(
        student=student, role=role, status=active_status)
    if role in BILLING_OFFICER_ROLE_CODES:
        clash_qs = clash_qs.filter(establishment=establishment)
    if existing is not None:
        clash_qs = clash_qs.exclude(pk=existing.pk)
    clash = list(clash_qs.order_by('-assigned_at'))
    if clash and not repeat_override:
        return fail(
            [f"{role_row.name} is already an active assignment for this student "
             f"in “{clash[0].activity_name}”. Tick “Assign this role again” to add "
             "another."],
            clash=True,
        )

    if existing is None:
        assignment = SimulationRoleAssignment.objects.create(
            student=student,
            assigned_by=request.user,
            role=role,
            role_ref=role_row,
            activity_name=session.name,
            session=session,
            establishment=establishment,
            hotel=hotel,
            **schedule,
        )
        action = 'assign'
        log_activity(request.user, f"Assigned {role} role",
                     f"{session.name} — {role_row.name}", session=session)
        if repeat_override and clash:
            log_activity(
                request.user, "Re-assigned an already active role",
                f"{role_row.name} repeated in {session.name} (already active in "
                + "; ".join(f"{a.activity_name}, {a.assigned_at:%b %d, %Y}" for a in clash)
                + ")",
                session=session,
            )
    else:
        old_role = existing.get_role_display()
        old_establishment = existing.establishment.name if existing.establishment_id else None
        # ``save`` re-derives role_ref/hotel/establishment_type from these, so the
        # fields are set plainly and saved whole rather than by field list.
        existing.role = role
        existing.role_ref = role_row
        existing.establishment = establishment
        existing.hotel = hotel
        existing.simulation_date = schedule.get('simulation_date')
        existing.start_time = schedule.get('start_time')
        existing.end_time = schedule.get('end_time')
        existing.save()
        assignment = existing
        action = 'edit'
        detail = f"{old_role} → {existing.get_role_display()}"
        new_establishment = establishment.name if establishment is not None else None
        if old_establishment != new_establishment:
            detail += (f" ({old_establishment or 'no establishment'}"
                       f" → {new_establishment or 'no establishment'})")
        log_activity(request.user, "Updated simulation role", detail, session=session)

    return JsonResponse({
        'ok': True,
        'action': action,
        'assignment': _assignment_json(assignment),
    })


@login_required
def role_list(request):
    """FR Retrieve Simulation Roles – search by student, role, status and activity (FR-036)."""
    if not (is_manager(request.user)):
        messages.error(request, "You are not authorised to review role assignments.")
        return redirect('simulation:workspace')

    qs = SimulationRoleAssignment.objects.select_related('student', 'assigned_by', 'hotel')
    q = (request.GET.get('q') or '').strip()
    role = (request.GET.get('role') or '').strip()
    status = (request.GET.get('status') or '').strip()
    activity = (request.GET.get('activity') or '').strip()
    sim_date = (request.GET.get('simulation_date') or '').strip()
    hotel = (request.GET.get('hotel') or '').strip()

    if q:
        qs = qs.filter(Q(student__first_name__icontains=q) | Q(student__last_name__icontains=q) |
                       Q(student__username__icontains=q) | Q(student__email__icontains=q) |
                       Q(activity_name__icontains=q) | Q(hotel__name__icontains=q))
    if role:
        qs = qs.filter(role=role)
    if status:
        qs = qs.filter(status=status)
    if activity:
        qs = qs.filter(activity_name__icontains=activity)
    if sim_date:
        qs = qs.filter(simulation_date=sim_date)
    if hotel:
        qs = qs.filter(hotel_id=hotel if hotel.isdigit() else 0)

    return render(request, 'simulation/role_list.html', {
        'roles': qs,
        'q': q,
        'role': role,
        'status': status,
        'activity': activity,
        'role_choices': SimulationRoleAssignment.Role.choices,
        'status_choices': SimulationRoleAssignment.AssignmentStatus.choices,
        'simulation_date': sim_date,
        'hotel': hotel,
        'hotels': _active_hotels(),
    })


@login_required
def role_detail(request, assignment_id):
    """FR View Simulation Role – owner and instructor/instructor views (FR-036)."""
    assignment = get_object_or_404(
        SimulationRoleAssignment.objects.select_related('establishment'),
        pk=assignment_id,
    )
    if assignment.student != request.user and not is_manager(request.user):
        messages.error(request, "You may only view your own role assignments.")
        return redirect('simulation:workspace')
    return render(request, 'simulation/role_detail.html', {
        'assignment': assignment,
        'permissions': assignment.role_permissions(),
        'is_manager': is_manager(request.user),
        'can_manage': _is_instructor(request.user),
        'role_choices': [
            (code, label) for code, label, _establishment_type
            in _assignable_roles()
        ],
        'role_establishment_types': {
            code: establishment_type for code, _label, establishment_type
            in _assignable_roles()
        },
        'guest_destinations': _guest_destination_types(),
        'establishment_types': [
            (value, label) for value, label in Establishment.Type.choices
        ],
        'establishments_by_type': {
            value: [
                {'id': establishment.pk, 'name': establishment.name}
                for establishment in _establishments_for_type(value)
            ]
            for value, _label in Establishment.Type.choices
        },
        'student_roles': SimulationRoleAssignment.objects
            .select_related('assigned_by', 'establishment')
            .filter(student=assignment.student)
            .exclude(pk=assignment.pk),
    })


@login_required
def role_update(request, assignment_id):
    """FR Update Simulation Role – instructor changes the role and/or where it is done.

    Changing either re-points the student's training environment, so an
    establishment that is no longer theirs stops being reachable the moment the
    row is saved (``atrue_core.hotel_scope`` and the engine's assignment lookups
    read this table on every request).

    The rules mirror :func:`assign_role`: only the active catalogue is on offer,
    and a role performed inside an establishment must be given one *of that role's
    own type*. Editing must not become a way around the checks the assign form
    applies, so the posted id is resolved rather than trusted.
    """
    if request.method != 'POST':
        return redirect('simulation:role_detail', assignment_id=assignment_id)
    if not _is_instructor(request.user):
        messages.error(request, "Only instructors may update role assignments.")
        return redirect('simulation:workspace')
    assignment = get_object_or_404(SimulationRoleAssignment, pk=assignment_id)
    if assignment.status == SimulationRoleAssignment.AssignmentStatus.DONE:
        messages.error(request, "Completed role assignments cannot be edited.")
        return redirect('simulation:role_detail', assignment_id=assignment_id)
    new_role = (request.POST.get('role') or '').strip()
    reason = (request.POST.get('reason') or '').strip()
    establishment_id = (request.POST.get('establishment') or '').strip()

    offered = {code for code, _label, _establishment_type in _assignable_roles()}
    role_row = Role.objects.filter(code=new_role, is_active=True).first()
    if not new_role or new_role not in offered or role_row is None:
        messages.error(request, "Select a valid role.")
        return redirect('simulation:role_detail', assignment_id=assignment_id)

    # An operational role keeps the establishment it already has unless a new one
    # is posted, so changing only the role does not silently strip the student of
    # the place they work. Switching *type* has to supply a new one, because the
    # old establishment is then of the wrong type.
    establishment = None
    if role_row.requires_establishment and not role_row.code.endswith('_OWNER'):
        wanted_type = role_row.establishment_category
        current = assignment.establishment
        if (not establishment_id and current is not None
                and current.type == wanted_type):
            establishment = current
        elif not establishment_id:
            messages.error(
                request,
                f"{role_row.name} is performed inside an establishment, so select "
                f"the {role_row.get_establishment_category_display()} where it happens.")
            return redirect('simulation:role_detail', assignment_id=assignment_id)
        else:
            establishment = _resolve_establishment(establishment_id, wanted_type)
            if establishment is None:
                messages.error(
                    request,
                    f"Select an active {role_row.get_establishment_category_display()} "
                    "from the list.")
                return redirect('simulation:role_detail', assignment_id=assignment_id)
    elif role_row.code in _guest_destination_types():
        # A guest's place is optional, like the assign form: post a new one of
        # the module's own type to re-point the student, keep the current one,
        # or leave it empty to browse the whole module.
        guest_type = _guest_destination_types()[role_row.code]
        current = assignment.establishment
        if establishment_id:
            establishment = _resolve_establishment(establishment_id, guest_type)
            if establishment is None:
                label = dict(Establishment.Type.choices).get(
                    guest_type, guest_type).lower()
                messages.error(
                    request,
                    f"Select an active {label} from the list, or leave it "
                    "empty to let the guest browse all.")
                return redirect('simulation:role_detail', assignment_id=assignment_id)
        elif current is not None and current.type == guest_type:
            establishment = current

    old_role = assignment.get_role_display()
    old_establishment = (assignment.establishment.name
                         if assignment.establishment_id else None)
    assignment.role = new_role
    assignment.role_ref = role_row
    assignment.establishment = establishment
    assignment.hotel = (
        establishment.entity
        if (establishment is not None
            and establishment.type == Establishment.Type.HOTEL
            and role_row.establishment_type)
        else None)
    # ``save`` re-derives role/hotel/establishment_type/establishment_required, so
    # the field list has to name every mirrored column it writes.
    assignment.save(update_fields=[
        'role', 'role_ref', 'hotel', 'establishment', 'establishment_type',
        'establishment_required'])

    detail = f"{old_role} → {assignment.get_role_display()}"
    new_establishment = establishment.name if establishment is not None else None
    if old_establishment != new_establishment:
        detail += (
            f" ({old_establishment or 'no establishment'}"
            f" → {new_establishment or 'no establishment'})")
    if reason:
        detail += f" ({reason})"
    log_activity(assignment.student, "Simulation role updated", detail, session=assignment.session)
    log_activity(request.user, "Updated simulation role", detail, session=assignment.session)
    messages.success(request, f"Role updated to {assignment.get_role_display()}.")
    return redirect('simulation:role_detail', assignment_id=assignment_id)


_ROLE_CHOICES = SimulationRoleAssignment.Role.choices
_ROLE_LABELS = dict(SimulationRoleAssignment.Role.choices)
_ESTABLISHMENT_TYPE_LABELS = dict(Establishment._meta.get_field('type').choices)


def _match_assignment(log, assignments):
    """Find the role assignment a log entry was recorded under.

    Forward-written entries carry ``simulation_role`` (the student's role code)
    and the user id, which pin down the assignment within the session; the
    instructor's own rows are left without one.
    """
    if not log.simulation_role:
        return None
    candidates = [
        a for a in assignments
        if a.student_id == log.user_id and a.role == log.simulation_role
    ]
    if not candidates:
        return None
    return max(candidates, key=lambda a: (a.assigned_at, a.id))


def _row_context(log, assignments):
    """Build a display row: the log itself plus student/role/establishment
    context resolved from the session's role assignments."""
    assignment = _match_assignment(log, assignments)

    role_label = '-'
    if log.simulation_role:
        role_label = _ROLE_LABELS.get(log.simulation_role, log.simulation_role)
    elif assignment is not None:
        role_label = assignment.get_role_display()

    establishment = '-'
    if log.establishment_id:
        establishment = log.establishment.name
    elif assignment is not None:
        if assignment.establishment_id:
            establishment = assignment.establishment.name
        elif assignment.hotel_id:
            establishment = assignment.hotel.name

    establishment_type = '-'
    if log.establishment_id:
        establishment_type = _ESTABLISHMENT_TYPE_LABELS.get(
            log.establishment.type, log.establishment.type)
    elif assignment is not None and assignment.establishment_id:
        establishment_type = _ESTABLISHMENT_TYPE_LABELS.get(
            assignment.establishment.type, assignment.establishment.type)
    elif assignment is not None and assignment.hotel_id:
        establishment_type = 'Hotel'

    status = '-'
    if assignment is not None:
        status = assignment.get_status_display()

    return {
        'log': log,
        'student': log.user,
        'role_label': role_label,
        'establishment': establishment,
        'establishment_type': establishment_type,
        'status': status,
    }


def _row_to_json(row, session):
    """Shape one activity log row into the payload used by the mobile popup."""
    log = row['log']
    student = row['student']
    return {
        'student': student.get_full_name() or student.username,
        'session': session.name,
        'establishment': row['establishment'],
        'establishment_type': row['establishment_type'],
        'role': row['role_label'],
        'activity': log.action,
        'description': log.details or '',
        'date': log.timestamp.strftime('%B %d, %Y'),
        'time': log.timestamp.strftime('%I:%M %p').lstrip('0'),
        'status': row['status'],
    }


def _session_establishments(session, logs):
    """Filter dropdown options: establishments assigned inside the session plus
    any that appear on the session's recorded logs."""
    seen = set()
    result = []
    for assignment in SimulationRoleAssignment.objects.filter(
            session=session).select_related('establishment'):
        establishment = assignment.establishment
        if establishment is not None and establishment.id not in seen:
            seen.add(establishment.id)
            result.append(establishment)
    for log in logs:
        establishment = log.establishment
        if establishment is not None and establishment.id not in seen:
            seen.add(establishment.id)
            result.append(establishment)
    result.sort(key=lambda e: e.name.casefold())
    return result


@login_required
def view_logs(request):
    """Organize activity logs by simulation session (BR-085).

    The manager/instructor sees every session as a card with its recorded
    activity stats; any other account only sees the sessions it holds a role in
    and only its own recorded actions are counted.
    """
    can_view_all = request.user.is_staff or is_manager(request.user)
    if can_view_all:
        sessions = SimulationSession.objects.all()
        log_filter = Q()
    else:
        sessions = SimulationSession.objects.filter(
            assignments__student=request.user).distinct()
        log_filter = Q(activitylog__user=request.user)

    sessions = sessions.annotate(
        log_count=Count('activitylog', filter=log_filter),
        student_count=Count(
            'activitylog__user', distinct=True,
            filter=Q(activitylog__user__account_type='STUDENT') & log_filter),
        last_activity=Max('activitylog__timestamp', filter=log_filter),
    ).order_by('-last_activity', '-created_at')

    return render(request, 'simulation/logs.html', {
        'sessions': sessions,
        'can_view_all': can_view_all,
    })


@login_required
def session_logs(request, session_id):
    """Session-specific activity log page (BR-085).

    Shows only the logs recorded against the selected session, filtered through
    the actual ``ActivityLog.session`` foreign key. Managers/staff see the full
    session; a student sees only their own recordings and only if they hold a
    role in that session.
    """
    session = get_object_or_404(SimulationSession, pk=session_id)
    can_view_all = request.user.is_staff or is_manager(request.user)
    if not can_view_all:
        enrolled = SimulationRoleAssignment.objects.filter(
            session=session, student=request.user)
        if not enrolled.exists():
            return HttpResponseForbidden(
                'You do not have access to this session’s activity logs.')

    logs = ActivityLog.objects.filter(session=session).select_related(
        'user', 'establishment').order_by('-timestamp')
    if not can_view_all:
        logs = logs.filter(user=request.user)

    q = (request.GET.get('q') or '').strip()
    activity = (request.GET.get('activity') or '').strip()
    establishment_id = (request.GET.get('establishment') or '').strip()
    role = (request.GET.get('role') or '').strip()
    date_from = (request.GET.get('from') or '').strip()
    date_to = (request.GET.get('to') or '').strip()

    if q:
        logs = logs.filter(
            Q(user__first_name__icontains=q)
            | Q(user__last_name__icontains=q)
            | Q(user__username__icontains=q))
    if establishment_id:
        logs = logs.filter(establishment_id=establishment_id)
    if role:
        logs = logs.filter(simulation_role=role)
    if activity:
        logs = logs.filter(action__icontains=activity)
    if date_from:
        logs = logs.filter(timestamp__date__gte=date_from)
    if date_to:
        logs = logs.filter(timestamp__date__lte=date_to)

    assignments = list(
        SimulationRoleAssignment.objects.filter(session=session).select_related(
            'student', 'establishment', 'hotel'))
    rows = [_row_context(log, assignments) for log in logs]
    rows_json = [_row_to_json(row, session) for row in rows]

    return render(request, 'simulation/session_logs.html', {
        'session': session,
        'rows': rows,
        'rows_json': rows_json,
        'role_choices': _ROLE_CHOICES,
        'establishments': _session_establishments(session, logs),
        'q': q,
        'activity': activity,
        'role': role,
        'establishment': establishment_id,
        'date_from': date_from,
        'date_to': date_to,
    })
