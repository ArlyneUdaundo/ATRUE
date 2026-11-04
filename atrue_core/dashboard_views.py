from django.contrib.auth.decorators import login_required
from django.shortcuts import render


@login_required
def dashboard_about(request):
    return render(request, 'dashboard/about.html')


@login_required
def dashboard_contact(request):
    return render(request, 'dashboard/contact.html')
