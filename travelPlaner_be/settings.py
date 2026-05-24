from pathlib import Path
from datetime import timedelta
# decouple: .env ファイルから環境変数を読み込むライブラリ。
# config('KEY', default='値') → 環境変数 KEY があればそれを使い、なければ default を使う。
# コードに秘密情報（DBパスワード等）を直接書かずに済む。
from decouple import config
# PyMySQL: Pure Python で書かれた MySQL クライアント。
# Djangoのデフォルトの MySQLdb（C拡張）の代わりに使う。install_as_MySQLdb() で互換性を確保する。
import pymysql
pymysql.install_as_MySQLdb()

# BASE_DIR: このファイル（settings.py）の2つ上のディレクトリ = プロジェクトルート。
# 他のパス設定の基準になる。
BASE_DIR = Path(__file__).resolve().parent.parent

# Django の署名・暗号化に使われる秘密鍵。本番環境では必ず .env で管理し、外部に漏らさない。
SECRET_KEY = config('SECRET_KEY', default='django-insecure-jt4tht@*qwp(kuem6iruc48bfsd4vm0_r(%v!e&!5!ms@w89+6')

# DEBUG=True: 詳細なエラーページが表示される。本番では必ず False にする。
DEBUG = config('DEBUG', default=True, cast=bool)

# ALLOWED_HOSTS: Djangoが応答するホスト名のホワイトリスト。
# cast=lambda: カンマ区切りの文字列をリストに変換する。
ALLOWED_HOSTS = config('ALLOWED_HOSTS', default='localhost,127.0.0.1', cast=lambda v: v.split(','))

# INSTALLED_APPS: Django に認識させるアプリの一覧。
# ここに書いたアプリの models.py がマイグレーション対象になる。
INSTALLED_APPS = [
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    # djangorestframework: REST API を作るためのライブラリ。
    'rest_framework',
    # simplejwt: JWT（JSON Web Token）認証を提供するライブラリ。
    'rest_framework_simplejwt',
    # corsheaders: フロントエンド（Vue）からのクロスオリジンリクエストを許可する。
    'corsheaders',
    # 自作アプリ。trips/models.py・views.py などが認識される。
    'trips',
]

# MIDDLEWARE: リクエスト・レスポンスを処理するパイプライン。上から順に実行される。
# CorsMiddleware は SecurityMiddleware の直後に置く必要がある（公式推奨）。
MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'corsheaders.middleware.CorsMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
]

ROOT_URLCONF = 'travelPlaner_be.urls'

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [],
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
            ],
        },
    },
]

WSGI_APPLICATION = 'travelPlaner_be.wsgi.application'

# データベース設定。PyMySQL を使って外部 MySQL サーバーに接続する。
DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.mysql',
        'NAME': config('DB_NAME', default='travelPlaner'),
        'USER': config('DB_USER', default='root'),
        'PASSWORD': config('DB_PASSWORD', default='fldeldehdgn1!'),
        'HOST': config('DB_HOST', default='homejdh.iptime.org'),
        'PORT': config('DB_PORT', default='9002'),
        'OPTIONS': {
            # utf8mb4: 絵文字を含む全てのUnicode文字を保存できる文字コード。
            # utf8 は MySQL では3バイト文字までしか対応していないため utf8mb4 を使う。
            'charset': 'utf8mb4',
            'connect_timeout': 10,
        },
    }
}

AUTH_PASSWORD_VALIDATORS = [
    {'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator'},
    {'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator'},
    {'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator'},
    {'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator'},
]

LANGUAGE_CODE = 'ja'
TIME_ZONE = 'Asia/Tokyo'
USE_I18N = True
USE_TZ = True

STATIC_URL = 'static/'

DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'

# DRF（Django REST Framework）のグローバル設定。
REST_FRAMEWORK = {
    'DEFAULT_AUTHENTICATION_CLASSES': (
        # JWTAuthentication: Authorization: Bearer <token> ヘッダーを読み取ってユーザーを認証する。
        'rest_framework_simplejwt.authentication.JWTAuthentication',
    ),
    'DEFAULT_PERMISSION_CLASSES': (
        # IsAuthenticatedOrReadOnly: GET は誰でも、POST/PATCH/DELETE はログイン必須。
        # ただし各 View で permission_classes を指定するとそちらが優先される。
        'rest_framework.permissions.IsAuthenticatedOrReadOnly',
    ),
}

# JWT トークンの有効期限設定。
SIMPLE_JWT = {
    # ACCESS_TOKEN_LIFETIME: アクセストークンの有効期限（短め）。
    # 期限切れになるとリフレッシュトークンで再発行する（client.ts の interceptor が自動処理）。
    'ACCESS_TOKEN_LIFETIME': timedelta(hours=2),
    # REFRESH_TOKEN_LIFETIME: リフレッシュトークンの有効期限（長め）。
    'REFRESH_TOKEN_LIFETIME': timedelta(days=7),
    # ROTATE_REFRESH_TOKENS: リフレッシュ時に新しいリフレッシュトークンも発行する。
    # 古いリフレッシュトークンは無効化され、セキュリティが向上する。
    'ROTATE_REFRESH_TOKENS': True,
}

# CORS（Cross-Origin Resource Sharing）設定。
# ブラウザは異なるオリジン（ドメイン・ポート）へのリクエストをデフォルトでブロックする。
# フロントエンド（localhost:5173）からバックエンド（localhost:8000）へアクセスするために必要。
CORS_ALLOWED_ORIGINS = [
    'http://localhost:5173',
    'http://127.0.0.1:5173',
]
CORS_ALLOW_CREDENTIALS = True
# CORS_ALLOW_HEADERS: プリフライト（OPTIONS リクエスト）で許可するヘッダー一覧。
# カスタムヘッダー X-Pin-Token を明示的に追加する必要がある。
# 追加しないと、X-Pin-Token を含むリクエストがブラウザに CORS エラーとして弾かれる。
CORS_ALLOW_HEADERS = [
    'accept',
    'accept-encoding',
    'authorization',
    'content-type',
    'dnt',
    'origin',
    'user-agent',
    'x-csrftoken',
    'x-requested-with',
    'x-pin-token',  # PIN認証トークン用カスタムヘッダー
]

GOOGLE_MAPS_API_KEY = config('GOOGLE_MAPS_API_KEY', default='')

# Flask メールサービスの URL。
# pythonEmailService/app.py が localhost:5000 で起動していることを前提とする。
EMAIL_SERVICE_URL = config('EMAIL_SERVICE_URL', default='http://localhost:5001')

# AUTH_USER_MODEL: Django が認証に使うユーザーモデルを独自クラスに変更する。
# AbstractUser を継承した trips.User を使うことで email ログインが可能になる。
# この設定は初回 migrate 前にしか変更できない（変えると既存のマイグレーションが壊れる）。
AUTH_USER_MODEL = 'trips.User'
