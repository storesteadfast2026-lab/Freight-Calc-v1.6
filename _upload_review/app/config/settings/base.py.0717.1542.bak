from pathlib import Path
import os

BASE_DIR = Path(__file__).resolve().parent.parent.parent

SECRET_KEY = os.getenv('SECRET_KEY', 'unsafe-local-key')
DEBUG = os.getenv('DEBUG', '0') == '1'
ALLOWED_HOSTS = [h.strip() for h in os.getenv('DJANGO_ALLOWED_HOSTS', 'localhost,127.0.0.1').split(',') if h.strip()]

INSTALLED_APPS = [
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    'apps.clients',
    'apps.locations',
    'apps.products',
    'apps.carriers',
    'apps.rates',
    'apps.imports',
    'apps.audit',
    'apps.authentication_gateway',
    'apps.freight',
]

MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'whitenoise.middleware.WhiteNoiseMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'apps.authentication_gateway.middleware.ExternalAuthMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
]

ROOT_URLCONF = 'config.urls'

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [BASE_DIR / 'templates'],
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.debug',
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
            ],
        },
    },
]

WSGI_APPLICATION = 'config.wsgi.application'
ASGI_APPLICATION = 'config.asgi.application'

DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.postgresql',
        'NAME': os.getenv('POSTGRES_DB', 'freight_platform'),
        'USER': os.getenv('POSTGRES_USER', 'freight_user'),
        'PASSWORD': os.getenv('POSTGRES_PASSWORD', 'freight_password'),
        'HOST': os.getenv('POSTGRES_HOST', 'localhost'),
        'PORT': os.getenv('POSTGRES_PORT', '5432'),
    }
}

LANGUAGE_CODE = 'en-us'
TIME_ZONE = 'Australia/Adelaide'
USE_I18N = True
USE_TZ = True

STATIC_URL = '/static/'
STATIC_ROOT = BASE_DIR / 'staticfiles'
STATICFILES_DIRS = [BASE_DIR / 'static'] if (BASE_DIR / 'static').exists() else []

MEDIA_URL = '/media/'
MEDIA_ROOT = Path(os.getenv('MEDIA_ROOT', str(BASE_DIR / 'uploaded_data')))

DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'

CALCULATOR_REQUIRE_AUTH = os.getenv('CALCULATOR_REQUIRE_AUTH', '0') == '1'
EXTERNAL_AUTH_HEADER = os.getenv('EXTERNAL_AUTH_HEADER', 'HTTP_X_AUTH_USER')

# Freight calculation constants matching the Excel workbook defaults.
# Excel source: CalcLines!J7 = pallet weight, CalcLines!K7 = pallet cubic.
# These can be changed later through environment variables without code changes.
FREIGHT_PALLET_WEIGHT_KG = os.getenv('FREIGHT_PALLET_WEIGHT_KG', '32.5')
FREIGHT_PALLET_CUBIC_M3 = os.getenv('FREIGHT_PALLET_CUBIC_M3', '0.02')

# Manual fuel import source and validation limits.
FUEL_SOURCE_URL = os.getenv('FUEL_SOURCE_URL', 'https://www.poscat.com.au/fuelsc/fuel.csv')
FUEL_FETCH_TIMEOUT_SECONDS = int(os.getenv('FUEL_FETCH_TIMEOUT_SECONDS', '30'))
FUEL_RATE_MAX = os.getenv('FUEL_RATE_MAX', '1.0')
