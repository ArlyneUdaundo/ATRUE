from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.shortcuts import render

from accounts.roles import can_access_module
from .models import TransactionRecord


@login_required
def record_list(request):
    management = can_access_module(request.user, 'records')
    records = TransactionRecord.objects.select_related('user')
    if not management:
        records = records.filter(user=request.user)

    record_type = request.GET.get('type', '')
    if record_type:
        records = records.filter(record_type=record_type)

    records = records.order_by('-recorded_at', '-pk')
    record_page = Paginator(records, 50).get_page(request.GET.get('page'))

    from django.db.models import Count
    base = TransactionRecord.objects.all() if management else TransactionRecord.objects.filter(user=request.user)
    by_type = dict(base.values_list('record_type').annotate(count=Count('id')))
    summary = [(value, label, by_type.get(value, 0)) for value, label in TransactionRecord.RecordType.choices]

    return render(request, 'records/list.html', {
        'records': record_page,
        'record_count': record_page.paginator.count,
        'current_type': record_type,
        'types': TransactionRecord.RecordType.choices,
        'summary': summary,
        'staff': management,
    })