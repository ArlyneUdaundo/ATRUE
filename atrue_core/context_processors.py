import json
from functools import lru_cache

from atrue_core.location_hierarchy import build_location_hierarchy
from simulation.task_routing import (
    TASK_ASSIGNMENT_SESSION_KEY,
    operation_with_urls,
    task_operation_for,
)


@lru_cache(maxsize=16)
def _location_tree_cached(country_code=''):
    """Cache one country tree at a time.

    Keyed by country so ``/locations/api/?country=XX`` gets its own tree, and
    small enough that browsing a handful of countries does not evict the one the
    inlined page feed uses. Building a tree walks that country's GeoNames rows, so
    this is the difference between a per-page query storm and nothing.
    """
    return build_location_hierarchy(country_code or None)


def location_tree(request):
    """Expose the Country -> Province -> Municipality -> Barangay tree to every
    template as ``atrue_loc_tree`` (a dict) and ``atrue_loc_tree_json`` (a safe
    JSON blob meant for an inline <script>) so the hierarchical location picker
    works on any page without an extra round-trip.

    Only the platform's own country is inlined, from
    ``settings.LOCATION_PRIMARY_COUNTRY``. The GeoNames data is worldwide, and
    inlining every province in the world would add tens of megabytes to every
    page; the other countries are fetched on demand from
    ``/locations/api/?country=XX``.
    """
    tree = _location_tree_cached('')
    return {
        'atrue_loc_tree': tree,
        'atrue_loc_tree_json': json.dumps(tree, ensure_ascii=False),
    }


def notification_count(request):
    if not request.user.is_authenticated:
        return {'notification_count': 0}
    from simulation.models import ActivityLog
    return {
        'notification_count': ActivityLog.objects.filter(user=request.user).count(),
    }


def simulation_task_context(request):
    """Expose the current tab's assigned operations module to the dashboard nav."""
    assignment_id = request.session.get(TASK_ASSIGNMENT_SESSION_KEY)
    if assignment_id is None:
        return {
            'active_simulation_task_context': False,
            'active_simulation_task_operation': None,
        }
    if not request.user.is_authenticated:
        return {
            'active_simulation_task_context': True,
            'active_simulation_task_operation': None,
        }

    from simulation.models import SimulationRoleAssignment

    assignment = (
        SimulationRoleAssignment.objects
        .filter(
            pk=assignment_id,
            student=request.user,
            status=SimulationRoleAssignment.AssignmentStatus.ACTIVE,
        )
        .select_related('role_ref', 'establishment', 'hotel')
        .first()
    )
    operation = task_operation_for(assignment) if assignment else None
    if operation is not None:
        operation = operation_with_urls(assignment, operation)

    return {
        'active_simulation_task_context': True,
        'active_simulation_task_operation': operation,
    }
