import os,sys,django
sys.path.insert(0,'C:/Users/ariel/OneDrive/Desktop/ATRUE/EULA')
os.environ['DJANGO_SETTINGS_MODULE']='atrue_core.settings'
django.setup()
from django.urls import resolve
r=resolve('/resorts/')
print(r.url_name)
print(r.func.__module__)