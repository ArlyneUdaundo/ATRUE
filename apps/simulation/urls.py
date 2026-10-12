from django.urls import path

from . import views

app_name = 'simulation'

urlpatterns = [
    path('workspace/', views.workspace, name='workspace'),
    path('sessions/add/', views.add_session, name='add_session'),
    path('sessions/<int:session_id>/update/', views.update_session, name='update_session'),
    path('sessions/<int:session_id>/assignment/', views.session_assignment, name='session_assignment'),
    path('assign/', views.assign_role, name='assign'),
    path('unassign/<int:assignment_id>/', views.unassign_role, name='unassign'),
    path('do-task/<int:assignment_id>/', views.do_task, name='do_task'),
    path('roles/', views.role_list, name='role_list'),
    path('roles/<int:assignment_id>/', views.role_detail, name='role_detail'),
    path('roles/<int:assignment_id>/update/', views.role_update, name='role_update'),
    path('logs/', views.view_logs, name='logs'),
    path('logs/<int:session_id>/', views.session_logs, name='session_logs'),
]