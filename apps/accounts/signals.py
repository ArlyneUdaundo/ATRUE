"""Keep Django admin permissions in step with platform roles.

The role registry in ``accounts.roles`` decides what an account may do on the
project's own pages, while ``/admin/`` only ever looks at real ``auth``
permissions. Without this bridge the two drift apart and a staff account ends up
locked out of the admin with a 403 on every changelist. Re-syncing on save (and
on role assignment) keeps them aligned.
"""

from django.db.models.signals import post_delete, post_save
from django.dispatch import receiver

from simulation.models import SimulationRoleAssignment

from .models import User
from .roles import sync_admin_permissions


@receiver(post_save, sender=User, dispatch_uid='accounts.sync_admin_permissions')
def sync_user_admin_permissions(sender, instance, created, **kwargs):
    """Re-derive admin permissions whenever an account is saved."""
    if kwargs.get('raw'):
        return
    sync_admin_permissions(instance)


@receiver(post_save, sender=SimulationRoleAssignment, dispatch_uid='accounts.sync_role_permissions')
def sync_assigned_student_permissions(sender, instance, created, **kwargs):
    """Re-derive permissions when a student is given, updated or clears a role.

    Active role assignments widen the student's effective role, while inactive or
    revoked assignments must be re-synced so stale Django-admin permissions do
    not linger.
    """
    if kwargs.get('raw'):
        return
    sync_admin_permissions(instance.student)


@receiver(post_delete, sender=SimulationRoleAssignment, dispatch_uid='accounts.sync_deleted_role_permissions')
def sync_deleted_student_permissions(sender, instance, **kwargs):
    """Re-sync after a role assignment is removed."""
    sync_admin_permissions(instance.student)
