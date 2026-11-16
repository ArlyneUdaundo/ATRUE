from django.contrib import admin

from .models import ActivityLog, SimulationRoleAssignment, SimulationSession


@admin.register(SimulationRoleAssignment)
class SimulationRoleAssignmentAdmin(admin.ModelAdmin):
    list_display = ('student', 'role', 'activity_name', 'hotel', 'session_schedule',
                    'assigned_by', 'status', 'assigned_at')
    list_filter = ('role', 'status', 'session__session_date')
    search_fields = ('activity_name', 'student__username', 'student__first_name',
                     'student__last_name', 'hotel__name')

    @admin.display(description='Session schedule')
    def session_schedule(self, obj):
        session = obj.session
        if not session or not session.session_date:
            return 'Schedule not set'
        return f'{session.session_date} {session.start_time} - {session.end_time}'


@admin.register(SimulationSession)
class SimulationSessionAdmin(admin.ModelAdmin):
    list_display = ('session_id', 'name', 'instructor', 'session_date', 'start_time',
                    'end_time', 'schedule_status_display', 'status')
    list_filter = ('status', 'session_date')
    search_fields = ('session_id', 'name', 'instructor__username')


@admin.register(ActivityLog)
class ActivityLogAdmin(admin.ModelAdmin):
    list_display = ('user', 'action', 'simulation_activity', 'timestamp')
    list_filter = ('user',)
    search_fields = ('action', 'details')
