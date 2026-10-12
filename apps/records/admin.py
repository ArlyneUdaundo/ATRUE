from django.contrib import admin

from .models import TransactionRecord


@admin.register(TransactionRecord)
class TransactionRecordAdmin(admin.ModelAdmin):
    list_display = ('record_type', 'reference_number', 'user', 'recorded_at')
    list_filter = ('record_type', 'recorded_at')
    date_hierarchy = 'recorded_at'