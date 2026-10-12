from django.contrib import admin
from django.contrib.auth.admin import UserAdmin

from .models import User


@admin.register(User)
class AtruEUserAdmin(UserAdmin):
    list_display = ('username', 'get_full_name', 'email', 'account_type', 'status', 'is_staff')
    list_filter = ('account_type', 'status', 'is_staff', 'is_active')
    fieldsets = (
        (None, {'fields': ('username', 'password')}),
        ('Personal info', {'fields': (
            'first_name', 'last_name', 'middle_name', 'suffix',
            'email', 'date_of_birth', 'sex', 'contact_number',
            'residential_address', 'nationality',
        )}),
        ('Emergency contact', {'fields': (
            'emergency_contact_name', 'emergency_contact_number',
            'emergency_contact_relationship',
        )}),
        ('Account', {'fields': ('account_type', 'status')}),
        ('Permissions', {'fields': ('is_active', 'is_staff', 'is_superuser', 'groups', 'user_permissions')}),
        ('Important dates', {'fields': ('last_login', 'date_joined')}),
    )
    add_fieldsets = (
        (None, {
            'classes': ('wide',),
            'fields': ('username', 'password1', 'password2', 'account_type', 'is_staff'),
        }),
    )