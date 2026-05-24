# Django の URL ルーティング:
# クライアントがリクエストしたURLを、どのビュー関数・クラスで処理するかを定義する。
# urls.py → views.py の対応表のような役割。
from django.urls import path
# simplejwt が提供するビュー:
# TokenObtainPairView → POST /auth/login/ でメール+パスワードを受け取り JWT を発行する。
# TokenRefreshView → POST /auth/token/refresh/ でリフレッシュトークンを使いアクセストークンを再発行する。
from rest_framework_simplejwt.views import TokenObtainPairView, TokenRefreshView
from . import views

urlpatterns = [
    # --- 認証 ---
    # .as_view(): クラスベースビューを Django が扱える関数に変換する（必須）。
    # メール認証 STEP1: 認証コードを送信する
    path('auth/send-verification/', views.SendVerificationView.as_view(), name='send-verification'),
    # メール認証 STEP2: 入力されたコードを検証し verification_token を返す
    path('auth/verify-email/', views.VerifyEmailCodeView.as_view(), name='verify-email'),
    # 会員登録 STEP3: verification_token 付きで登録する
    path('auth/register/', views.RegisterView.as_view(), name='register'),
    path('auth/login/', TokenObtainPairView.as_view(), name='login'),
    path('auth/token/refresh/', TokenRefreshView.as_view(), name='token_refresh'),
    path('auth/me/', views.MeView.as_view(), name='me'),

    # --- 旅行 ---
    # <str:hash_url>: URL の該当部分を文字列として views.py の kwargs に渡す。
    # /trips/ → 一覧取得（GET）と新規作成（POST）
    path('trips/', views.TripListCreateView.as_view(), name='trip-list'),
    # /trips/<hash_url>/ → 単体取得（GET）・更新（PATCH）・削除（DELETE）
    path('trips/<str:hash_url>/', views.TripDetailView.as_view(), name='trip-detail'),
    path('trips/<str:hash_url>/pin/', views.PinVerifyView.as_view(), name='pin-verify'),
    path('trips/<str:hash_url>/join/', views.TripJoinView.as_view(), name='trip-join'),

    # --- メンバー ---
    path('trips/<str:hash_url>/members/', views.TripMemberListView.as_view(), name='member-list'),
    path('trips/<str:hash_url>/members/add/', views.TripMemberAddView.as_view(), name='member-add'),
    # <int:member_id>: 整数として受け取る。自動でint型にキャストされる。
    path('trips/<str:hash_url>/members/<int:member_id>/', views.TripMemberDetailView.as_view(), name='member-detail'),

    # --- スポット ---
    path('trips/<str:hash_url>/spots/', views.SpotListCreateView.as_view(), name='spot-list'),
    path('trips/<str:hash_url>/spots/order/', views.SpotOrderView.as_view(), name='spot-order'),
    # <uuid:pk>: UUID形式の文字列を uuid.UUID 型として受け取る。
    path('spots/<uuid:pk>/', views.SpotDetailView.as_view(), name='spot-detail'),

    # --- コメント ---
    # spot_pk という名前でビューに渡す（views.py の self.kwargs['spot_pk'] で参照）。
    path('spots/<uuid:spot_pk>/comments/', views.CommentListCreateView.as_view(), name='comment-list'),

    # --- 費用・精算 ---
    # GET/POST /trips/<hash_url>/expenses/ → 費用一覧取得・新規登録
    path('trips/<str:hash_url>/expenses/', views.ExpenseListCreateView.as_view(), name='expense-list'),
    # GET/PATCH/DELETE /expenses/<uuid:pk>/ → 費用詳細・更新・削除
    path('expenses/<uuid:pk>/', views.ExpenseDetailView.as_view(), name='expense-detail'),
    # GET /trips/<hash_url>/settlement/ → 精算計算結果を返す
    path('trips/<str:hash_url>/settlement/', views.SettlementView.as_view(), name='settlement'),
]
