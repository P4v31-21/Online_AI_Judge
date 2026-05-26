import os
os.environ.setdefault('DJANGO_SETTINGS_MODULE','oj.settings')
from django.conf import settings
print('ROOT_URLCONF' in dir(settings))
print('ROOT_URLCONF=', getattr(settings,'ROOT_URLCONF',None))
print('DATA_DIR=', getattr(settings,'DATA_DIR',None))
print('SECRET_KEY set=', getattr(settings,'SECRET_KEY',None) is not None)
print('INSTALLED_APPS count=', len(getattr(settings,'INSTALLED_APPS',[])))
