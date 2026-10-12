"""Checks that stop the two lists of roles drifting apart.

There are two places role names live: ``SimulationRoleAssignment.Role`` (what a
form will let you choose) and :data:`simulation.role_catalogue.ROLE_CATALOGUE`
(what the database is seeded with and what the data migration reads). They were
maintained by hand and quietly diverged once - the assignment form offered 34
roles while the catalogue seeded 35 - and nothing complained, so a student could
be assigned a role that had no row in the database.

These checks make that failure loud instead of silent.
"""

from django.core.checks import Error, Warning, register

from .role_catalogue import (
    OPERATIONAL_CATEGORIES,
    REQUIRED_OPERATIONAL_CATEGORIES,
    ROLE_CATALOGUE,
    active_codes,
    operational_codes_for,
    permissions_for,
)


def _catalogue_codes():
    return [entry[0] for entry in ROLE_CATALOGUE]


@register('simulation')
def role_choices_match_catalogue(app_configs, **kwargs):
    """Every assignable role must exist in the catalogue, and vice versa.

    "Assignable" means the roles an instructor may still pick. A retired code is
    deliberately absent from the assignment form but present in the catalogue as
    an inactive row, so it is not an error that it has no assignable choice.
    """
    from .models import SimulationRoleAssignment

    assignable = {code for code, _ in SimulationRoleAssignment.Role.choices}
    catalogued = set(_catalogue_codes())
    active = set(active_codes())

    errors = []
    missing_from_catalogue = sorted(active - catalogued)
    missing_from_choices = sorted(catalogued - assignable)

    if missing_from_catalogue:
        errors.append(Error(
            'Roles can be assigned but are not in ROLE_CATALOGUE, so no database '
            'row will exist for them: %s' % ', '.join(missing_from_catalogue),
            hint='Add them to simulation/role_catalogue.py ROLE_CATALOGUE.',
            id='simulation.E001'))
    if missing_from_choices:
        errors.append(Error(
            'Roles exist in ROLE_CATALOGUE but cannot be assigned to a student: %s'
            % ', '.join(missing_from_choices),
            hint=('Add them to SimulationRoleAssignment.Role in '
                  'simulation/models.py, then run makemigrations.'),
            id='simulation.E002'))

    return errors


@register('simulation')
def catalogue_entries_are_well_formed(app_configs, **kwargs):
    """Each catalogue row needs a code, label, category, stage and permissions."""
    errors = []
    seen = set()

    for entry in ROLE_CATALOGUE:
        code = entry[0]
        label = entry[1]
        if code in seen:
            errors.append(Error(
                'ROLE_CATALOGUE lists %s more than once.' % code,
                id='simulation.E003'))
        seen.add(code)

        if not str(label).strip():
            errors.append(Error(
                'Role %s has no label.' % code, id='simulation.E004'))

        permissions = permissions_for(code)
        if not permissions:
            errors.append(Error(
                'Role %s grants no permissions, so it could never be given '
                'anything to do.' % code, id='simulation.E005'))

    if not ROLE_CATALOGUE:
        errors.append(Error(
            'ROLE_CATALOGUE is empty; every role would be unusable.',
            id='simulation.E006'))

    return errors


@register('simulation')
def three_operational_roles_per_establishment(app_configs, **kwargs):
    """Every establishment type needs exactly one of each required operational role.

    Section 6.3 gives each operational area the same three jobs - a Manager, a
    Reservation role and a Front Desk role - and Section 9.2 routes work by
    ``operation_category``. Activity and Tour Package roles are distinct
    operational areas scoped to their own resource establishments and carry just
    the Reservation role plus the Operator (which is their Front Desk); the
    Manager authority for them stays at the parent Tour Operator. If an area is
    missing a required job, transactions reach a stage with nobody qualified to
    handle them, which is exactly the kind of dead end a simulation should not
    have. Extra roles are just as much a problem: the whole point of the model is
    that the jobs are the same everywhere, so a fourth would mean some
    establishment is special.
    """
    from .models import Role

    establishment_types = set(Role.ESTABLISHMENT_TYPE_MAP)
    errors = []

    for establishment_type in sorted(establishment_types):
        codes = operational_codes_for(establishment_type)
        required = REQUIRED_OPERATIONAL_CATEGORIES.get(
            establishment_type, OPERATIONAL_CATEGORIES)
        by_category = {entry[4]: entry[0] for entry in ROLE_CATALOGUE
                       if entry[3] == establishment_type and entry[4] in OPERATIONAL_CATEGORIES}
        for category in required:
            if category not in by_category:
                errors.append(Error(
                    '%s has no %s role, so a transaction that reaches that stage '
                    'has nobody who can handle it.'
                    % (establishment_type, category),
                    hint=('Add a %s role for %s to ROLE_CATALOGUE in '
                          'simulation/role_catalogue.py.' % (category, establishment_type)),
                    id='simulation.W001'))
        if len(codes) > len(required):
            errors.append(Warning(
                '%s has %d operational roles; the model defines exactly %d: %s.'
                % (establishment_type, len(codes), len(required),
                   ', '.join(required)),
                hint='Fold the extra role into one of the required ones.',
                id='simulation.W002'))

    return errors


@register('simulation')
def every_operational_role_has_operations(app_configs, **kwargs):
    """Every operational role must have somewhere to be sent.

    "Do the Task" resolves through ``task_routing.task_operation_for``, which
    looks the role up in ``_OPERATIONS`` by the establishment type it belongs to.
    A role with no entry there has no operations page and no allowed routes, so
    the button leads nowhere and the student has nothing to do. This is how eight
    of the fifteen new roles were missed when the catalogue was rebuilt: the
    catalogue and the routing table are two more lists of role names, and they
    had already drifted once.
    """
    from .task_routing import _OPERATIONS

    errors = []
    for entry in ROLE_CATALOGUE:
        code, _label, _category, establishment_type, operation, _order = entry[:6]
        if operation not in OPERATIONAL_CATEGORIES:
            continue
        if code not in _OPERATIONS.get(establishment_type, {}):
            errors.append(Error(
                '%s is an operational %s role but task_routing has no operations '
                'for it, so "Do the Task" would have nothing to open.'
                % (code, operation),
                hint=('Add %s to _OPERATIONS[%r] in simulation/task_routing.py, '
                      'aliasing it to the retired role it replaces where one '
                      'exists.' % (code, establishment_type)),
                id='simulation.E007'))

    return errors


@register('simulation')
def customer_roles_have_no_establishment(app_configs, **kwargs):
    """Customer roles act on the platform, never inside an establishment.

    A customer books and pays; a student acting *inside* an establishment is one
    of the three operational roles. Keeping the two apart is what stops a
    customer row from acquiring establishment scope, so any role whose job is
    ``CUSTOMER`` must not be bound to an establishment type.
    """
    from .role_catalogue import active_entries

    scoped = [entry[0] for entry in active_entries()
              if entry[4] == 'CUSTOMER' and entry[3] is not None]

    if scoped:
        return [Error(
            'Customer roles must not be bound to an establishment: %s'
            % ', '.join(sorted(scoped)),
            hint=('Keep customer roles establishment-free by setting '
                  'establishment_type to None on their catalogue row in '
                  'simulation/role_catalogue.py.'),
            id='simulation.W003')]

    return []


@register('simulation')
def offered_roles_have_database_rows(app_configs, **kwargs):
    """Every role the assign form offers must exist as an active ``Role`` row.

    This is the check that catches the gap the "Select a valid role." error came
    from: the form is built from ``ROLE_CATALOGUE`` while the POST handler needs a
    ``Role`` row to store, so a database whose catalogue has not been synced yet
    offers roles the backend then rejects. The view now repairs the table on the
    fly, which is why this is a Warning rather than an Error, but a database
    missing rows is still not in the state a fresh ``migrate`` produces.
    """
    from .role_catalogue import missing_active_codes

    missing = missing_active_codes()
    if missing:
        return [Warning(
            'Roles offered by the assign form have no active Role row, so the '
            'first assignment would fail: %s' % ', '.join(missing),
            hint=('Run `manage.py migrate simulation` to apply '
                  '0010_backfill_operational_roles, or '
                  '`manage.py seed_roles` to re-sync the catalogue.'),
            id='simulation.W004')]

    return []