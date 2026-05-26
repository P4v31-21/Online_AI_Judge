# Local override settings for quick local testing without Postgres
import os
from .dev_settings import *

# Use a local sqlite file for quick testing
DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.sqlite3',
        'NAME': os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'local_db.sqlite3'),
    }
}

# Ensure DATA_DIR exists under project for uploads/logs
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.path.join(BASE_DIR, 'data')
os.makedirs(DATA_DIR, exist_ok=True)

DEBUG = True
ALLOWED_HOSTS = ['*']
