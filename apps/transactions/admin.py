from django.contrib import admin

from .models import AdditionalTransaction, Bill, Cancellation, Payment


@admin.register(Bill)
class BillAdmin(admin.ModelAdmin):
    list_display = ('pk', 'service', 'customer',
                    'total_amount', 'amount_paid', 'balance_due', 'status', 'created_at')
    list_filter = ('service', 'status', 'created_at')
    date_hierarchy = 'created_at'


@admin.register(AdditionalTransaction)
class AdditionalTransactionAdmin(admin.ModelAdmin):
    list_display = ('pk', 'customer',
                    'description', 'quantity', 'rate', 'total_amount', 'created_at')
    list_filter = ('created_at',)
    date_hierarchy = 'created_at'


@admin.register(Cancellation)
class CancellationAdmin(admin.ModelAdmin):
    list_display = ('pk', 'requested_by', 'status', 'requested_at')
    list_filter = ('status', 'requested_at')
    date_hierarchy = 'requested_at'


@admin.register(Payment)
class PaymentAdmin(admin.ModelAdmin):
    list_display = ('pk', 'bill', 'customer', 'amount',
                    'method', 'status', 'paid_at')
    list_filter = ('method', 'status', 'paid_at')