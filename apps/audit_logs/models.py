"""Immutable audit trail for every consequential simulation action (Section 17).

Two rules make this table trustworthy, so both are enforced by the database
rather than by convention:

* **Append-only** - :meth:`AuditLog.save` refuses any update of an existing row
  and :meth:`AuditLog.delete` refuses deletion outright, so a student (or a
  careless instructor) cannot rewrite history after the fact.
* **Never cascading away with its subject** - the session, establishment,
  transaction, actor and role links all use ``SET_NULL``. Deleting a session
  must not erase the record that it was once activated, who activated it, and
  what happened inside it; the audit row survives with its denormalised
  ``session_label`` / ``establishment_label`` strings still readable.
"""

from django.conf import settings
from django.db import models
from django.utils import timezone


class AuditLog(models.Model):
    """One recorded action: who did what, in which role, session and establishment."""

    class Action(models.TextChoices):
        # -- session & role administration (Section 17) ----------------------
        SESSION_CREATED = 'SESSION_CREATED', 'Simulation session created'
        SESSION_UPDATED = 'SESSION_UPDATED', 'Simulation session updated'
        SESSION_ACTIVATED = 'SESSION_ACTIVATED', 'Simulation session activated'
        SESSION_COMPLETED = 'SESSION_COMPLETED', 'Simulation session completed'
        SESSION_REOPENED = 'SESSION_REOPENED', 'Simulation session reopened'
        ROLE_ASSIGNED = 'ROLE_ASSIGNED', 'Role assigned'
        ROLE_MODIFIED = 'ROLE_MODIFIED', 'Role modified'
        ROLE_DEACTIVATED = 'ROLE_DEACTIVATED', 'Role deactivated'
        ROLE_REACTIVATED = 'ROLE_REACTIVATED', 'Role reactivated'
        ESTABLISHMENT_ASSIGNED = 'ESTABLISHMENT_ASSIGNED', 'Establishment assigned'
        # -- role switching / acting ------------------------------------------
        ROLE_SWITCHED = 'ROLE_SWITCHED', 'Role switched'
        TRANSACTION_SUBMITTED = 'TRANSACTION_SUBMITTED', 'Transaction submitted'
        TRANSACTION_CLAIMED = 'TRANSACTION_CLAIMED', 'Transaction claimed'
        TRANSACTION_RELEASED = 'TRANSACTION_RELEASED', 'Transaction released'
        TRANSACTION_APPROVED = 'TRANSACTION_APPROVED', 'Transaction approved'
        TRANSACTION_REJECTED = 'TRANSACTION_REJECTED', 'Transaction rejected'
        TRANSACTION_CANCELLED = 'TRANSACTION_CANCELLED', 'Transaction cancelled'
        TRANSACTION_COMPLETED = 'TRANSACTION_COMPLETED', 'Transaction completed'
        TICKET_GENERATED = 'TICKET_GENERATED', 'Simulated ticket generated'
        QUOTATION_PREPARED = 'QUOTATION_PREPARED', 'Quotation prepared'
        VEHICLE_DISPATCHED = 'VEHICLE_DISPATCHED', 'Vehicle dispatched'
        BILLING_CREATED = 'BILLING_CREATED', 'Simulated billing created'
        PAYMENT_RECORDED = 'PAYMENT_RECORDED', 'Simulated payment recorded'
        PAYMENT_REJECTED = 'PAYMENT_REJECTED', 'Simulated payment rejected'
        SELF_APPROVAL_BLOCKED = 'SELF_APPROVAL_BLOCKED', 'Self-approval blocked'
        ACCESS_DENIED = 'ACCESS_DENIED', 'Access denied'

    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='audit_entries')
    action = models.CharField(max_length=40, choices=Action.choices, db_index=True)
    details = models.TextField(blank=True)

    #: The role the actor was *acting as*, which is not always their account type.
    role = models.ForeignKey(
        'simulation.Role', on_delete=models.SET_NULL, null=True, blank=True,
        related_name='audit_entries')
    role_code = models.CharField(max_length=40, blank=True)

    session = models.ForeignKey(
        'simulation.SimulationSession', on_delete=models.SET_NULL, null=True, blank=True,
        related_name='audit_entries')
    session_label = models.CharField(max_length=150, blank=True)
    establishment = models.ForeignKey(
        'establishments.Establishment', on_delete=models.SET_NULL, null=True, blank=True,
        related_name='audit_entries')
    establishment_label = models.CharField(max_length=150, blank=True)
    transaction = models.ForeignKey(
        'simulation.SimulationTransaction', on_delete=models.SET_NULL, null=True, blank=True,
        related_name='audit_entries')

    #: Before/after snapshots for state changes (status, amount, establishment).
    previous_value = models.TextField(blank=True)
    new_value = models.TextField(blank=True)
    remarks = models.TextField(blank=True)

    ip_address = models.GenericIPAddressField(null=True, blank=True)
    created_at = models.DateTimeField(default=timezone.now, editable=False, db_index=True)

    class Meta:
        ordering = ['-created_at', '-id']
        indexes = [
            models.Index(fields=['session', '-created_at'], name='audit_session_idx'),
            models.Index(fields=['actor', '-created_at'], name='audit_actor_idx'),
            models.Index(fields=['transaction'], name='audit_transaction_idx'),
        ]

    def __str__(self):
        return f'{self.get_action_display()} by {self.actor}'

    # -- append-only enforcement ---------------------------------------------

    def save(self, *args, **kwargs):
        if self.pk is not None:
            raise ValueError(
                'AuditLog rows are append-only; create a new entry instead of '
                'editing an existing one (Section 17).')
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValueError(
            'AuditLog rows cannot be deleted (Section 17).')