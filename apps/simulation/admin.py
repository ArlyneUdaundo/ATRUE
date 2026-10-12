from django.contrib import admin

from .models import ActivityLog, SimulationRoleAssignment


@admin.register(SimulationRoleAssignment)
class SimulationRoleAssignmentAdmin(admin.ModelAdmin):
    list_display = ('student', 'role', 'activity_name', 'hotel', 'simulation_date',
                    'start_time', 'end_time', 'assigned_by', 'status', 'assigned_at')
    list_filter = ('role', 'status', 'simulation_date')
    search_fields = ('activity_name', 'student__username', 'student__first_name',
                     'student__last_name', 'hotel__name')


@admin.register(ActivityLog)
class ActivityLogAdmin(admin.ModelAdmin):
    list_display = ('user', 'action', 'simulation_activity', 'timestamp')
    list_filter = ('user',)
    search_fields = ('action', 'details')
