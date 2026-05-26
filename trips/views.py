import hmac
import hashlib
import requests as http_client  # Flask メールサービスへの HTTP リクエストに使う
from django.conf import settings
from django.contrib.auth import get_user_model
from django.db.models import Q
# generics: CRUD に必要な処理（get/post/patch/delete）が実装済みの汎用ビュークラス。
# 例: generics.ListCreateAPIView → GET（一覧）とPOST（作成）を自動で処理する。
from rest_framework import generics, status, permissions
from rest_framework.decorators import api_view, permission_classes
from rest_framework.response import Response
# APIView: HTTPメソッド（get/post/patch/delete）を自分で実装する低レベルなビュー。
# generics より柔軟だが、記述量が増える。
from rest_framework.views import APIView
# RefreshToken: JWT（JSON Web Token）のリフレッシュトークンを生成するクラス。
# for_user(user) でアクセストークンとリフレッシュトークンのペアを発行できる。
from rest_framework_simplejwt.tokens import RefreshToken
from rest_framework_simplejwt.views import TokenObtainPairView as _TokenObtainPairView


# Flask メールサービスの URL。settings.py の EMAIL_SERVICE_URL で変更可能。
EMAIL_SERVICE_URL = getattr(settings, 'EMAIL_SERVICE_URL', 'http://localhost:5000')


# メール認証完了後に発行する HMAC トークン。
# email を含む文字列を SECRET_KEY でハッシュ化することで、
# ① このサーバーだけが生成できる ② DB に何も保存しなくていい の2点を保証する。
def _generate_email_verification_token(email: str) -> str:
    key = settings.SECRET_KEY.encode()
    msg = f"email_verified:{email}".encode()
    return hmac.new(key, msg, hashlib.sha256).hexdigest()[:40]


# HMAC（Hash-based Message Authentication Code）でPINトークンを生成する関数。
# PIN検証後、クライアントに渡す「合言葉」として機能する。
# SECRET_KEY + hash_url + user_id を組み合わせることで、
# ① ユーザーごとに異なるトークン ② サーバーだけが正しい値を知っている
# の2点を保証する。セッションやDBに何も保存しなくていい。
def _generate_pin_token(hash_url: str, user_id) -> str:
    key = settings.SECRET_KEY.encode()
    msg = f"{hash_url}:{user_id}".encode()
    # hmac.new(...).hexdigest() → 64文字の16進文字列。先頭40文字を使う。
    return hmac.new(key, msg, hashlib.sha256).hexdigest()[:40]

from decimal import Decimal
from .models import Trip, TripMember, Spot, Comment, Expense
from .serializers import (
    UserSerializer, RegisterSerializer,
    TripSerializer, TripCreateSerializer, PinVerifySerializer,
    SpotSerializer, SpotListSerializer, CommentSerializer,
    TripMemberSerializer, ExpenseSerializer,
)

User = get_user_model()


class JapaneseTokenObtainPairView(_TokenObtainPairView):
    """simplejwt のデフォルト英語エラーを日本語に上書きする。"""
    def post(self, request, *args, **kwargs):
        try:
            return super().post(request, *args, **kwargs)
        except Exception as e:
            from rest_framework.exceptions import AuthenticationFailed
            from rest_framework_simplejwt.exceptions import InvalidToken, TokenError
            if isinstance(e, (AuthenticationFailed, InvalidToken, TokenError)):
                return Response(
                    {'detail': 'メールアドレスまたはパスワードが正しくありません。'},
                    status=status.HTTP_401_UNAUTHORIZED
                )
            raise


# --- Auth ---

# --- メール認証 ---

class SendVerificationView(APIView):
    """
    STEP 1: メールアドレスに6桁の認証コードを送信する。
    Flask メールサービス（POST /sendMail/join）に中継するだけ。
    Redis に email → コード を1時間保存するのは Flask 側で行う。
    """
    permission_classes = [permissions.AllowAny]

    def post(self, request):
        email = request.data.get('email', '').strip()
        if not email:
            return Response({'detail': 'メールアドレスを入力してください。'}, status=status.HTTP_400_BAD_REQUEST)
        # 既存アカウントの確認（アクティブなユーザーのみ）
        if User.objects.filter(email=email, is_active=True).exists():
            return Response({'detail': 'このメールアドレスはすでに使用されています。'}, status=status.HTTP_400_BAD_REQUEST)
        try:
            # Flask サービスに POST して認証コードメールを送ってもらう。
            resp = http_client.post(
                f'{EMAIL_SERVICE_URL}/sendMail/join',
                json={'email': email},
                timeout=10,
            )
            if resp.text.strip() == 'success':
                return Response({'detail': '認証コードを送りました。メールをご確認ください。'})
            return Response({'detail': 'メール送信に失敗しました。'}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
        except Exception:
            return Response({'detail': 'メールサービスに接続できません。'}, status=status.HTTP_503_SERVICE_UNAVAILABLE)


class VerifyEmailCodeView(APIView):
    """
    STEP 2: ユーザーが入力したコードを Flask に確認させる。
    成功した場合、HMAC で生成した verification_token を返す。
    このトークンを STEP 3（登録）で使う。
    """
    permission_classes = [permissions.AllowAny]

    def post(self, request):
        email = request.data.get('email', '').strip()
        code = request.data.get('code', '').strip()
        if not email or not code:
            return Response({'detail': 'パラメータが不足しています。'}, status=status.HTTP_400_BAD_REQUEST)
        try:
            # Flask の /chkValid に email と入力されたコードを送って検証してもらう。
            resp = http_client.post(
                f'{EMAIL_SERVICE_URL}/chkValid',
                json={'email': email, 'authNumber': code},
                timeout=10,
            )
            result = resp.text.strip()
            if result == 'success':
                # 検証成功 → HMAC トークンを発行して返す。登録時の証明書として使う。
                token = _generate_email_verification_token(email)
                return Response({'verification_token': token})
            elif result == 'expired':
                return Response({'detail': '認証コードの有効期限が切れました。もう一度送信してください。'}, status=status.HTTP_400_BAD_REQUEST)
            else:
                return Response({'detail': '認証コードが正しくありません。'}, status=status.HTTP_400_BAD_REQUEST)
        except Exception:
            return Response({'detail': 'メールサービスに接続できません。'}, status=status.HTTP_503_SERVICE_UNAVAILABLE)


# generics.CreateAPIView: POST リクエストだけを受け付ける汎用ビュー。
# create() メソッドでシリアライザのバリデーション→保存を自動処理する。
class RegisterView(generics.CreateAPIView):
    queryset = User.objects.all()
    serializer_class = RegisterSerializer
    # AllowAny: 未ログインユーザーも呼べる（登録は誰でもできる必要があるため）。
    permission_classes = [permissions.AllowAny]

    # create() をオーバーライドして、メール認証トークンの確認と JWT 発行を行う。
    def create(self, request, *args, **kwargs):
        # verification_token: VerifyEmailCodeView が発行したHMACトークン。
        # これがないと登録できない（メール認証の強制）。
        verification_token = request.data.get('verification_token', '').strip()
        email = request.data.get('email', '').strip()

        if not verification_token or not email:
            return Response({'detail': 'メール認証が必要です。'}, status=status.HTTP_400_BAD_REQUEST)

        # サーバー側で同じ HMAC を再生成して比較する（DBに保存不要）。
        expected = _generate_email_verification_token(email)
        if not hmac.compare_digest(verification_token, expected):
            return Response({'detail': 'メール認証が無効です。もう一度認証してください。'}, status=status.HTTP_400_BAD_REQUEST)

        serializer = self.get_serializer(data=request.data)
        # is_valid(raise_exception=True): バリデーション失敗時に自動で 400 エラーを返す。
        serializer.is_valid(raise_exception=True)
        user = serializer.save()
        # RefreshToken.for_user(): アクセストークン（短命）とリフレッシュトークン（長命）を発行。
        refresh = RefreshToken.for_user(user)
        return Response({
            'user': UserSerializer(user).data,
            'access': str(refresh.access_token),
            'refresh': str(refresh),
        }, status=status.HTTP_201_CREATED)


# RetrieveUpdateAPIView: GET（取得）と PATCH/PUT（更新）を処理する汎用ビュー。
class MeView(generics.RetrieveUpdateAPIView):
    serializer_class = UserSerializer
    # IsAuthenticated: JWTトークンが有効なユーザーだけがアクセスできる。
    permission_classes = [permissions.IsAuthenticated]

    # get_object(): 対象オブジェクトを返すメソッド。
    # /auth/me/ は「自分自身」を返すので、URLパラメータではなくリクエストのユーザーを使う。
    def get_object(self):
        return self.request.user


# --- Trips ---

# ListCreateAPIView: GET（一覧）と POST（作成）を処理する汎用ビュー。
class TripListCreateView(generics.ListCreateAPIView):
    permission_classes = [permissions.IsAuthenticated]

    # get_serializer_class(): リクエストのメソッドによって使うシリアライザを切り替える。
    # 一覧は TripSerializer（ネストあり）、作成は TripCreateSerializer（シンプル）。
    def get_serializer_class(self):
        if self.request.method == 'POST':
            return TripCreateSerializer
        return TripSerializer

    # get_queryset(): このビューが返す QuerySet（DBからのデータ取得条件）を定義する。
    # Django ORM: Q オブジェクトで OR 条件を組み立てられる。
    def get_queryset(self):
        user = self.request.user
        if user.is_authenticated:
            # 削除済み（is_deleted=True）は一覧から除外する。
            return Trip.objects.filter(
                Q(creator=user) | Q(members__user=user)
            ).filter(is_deleted=False).distinct()
        return Trip.objects.filter(visibility='public', is_deleted=False)

    def get_serializer_context(self):
        # シリアライザに request を渡す。TripCreateSerializer の create() 内で使う。
        ctx = super().get_serializer_context()
        ctx['request'] = self.request
        return ctx

    def create(self, request, *args, **kwargs):
        serializer = TripCreateSerializer(data=request.data, context={'request': request})
        serializer.is_valid(raise_exception=True)
        trip = serializer.save()
        # 作成後は TripSerializer（ネストあり）で完全なデータを返す。
        return Response(TripSerializer(trip, context={'request': request}).data, status=status.HTTP_201_CREATED)


# RetrieveUpdateDestroyAPIView: GET（単体取得）・PATCH/PUT（更新）・DELETE（削除）を処理。
class TripDetailView(generics.RetrieveUpdateDestroyAPIView):
    permission_classes = [permissions.IsAuthenticated]
    # lookup_field: URLの <hash_url> をどのモデルフィールドと照合するかを指定する。
    # デフォルトは 'pk'（主キー）。ここでは hash_url で Trip を特定する。
    lookup_field = 'hash_url'

    def get_serializer_class(self):
        return TripSerializer

    def get_queryset(self):
        return Trip.objects.all()

    # get_object(): 単体オブジェクトを返す前にPINチェックを挿入する。
    def get_object(self):
        trip = super().get_object()
        # 削除済みの旅行は特別なレスポンスで返す（404ではなく専用フラグ）
        if trip.is_deleted:
            from rest_framework.exceptions import NotFound
            raise NotFound({'deleted': True, 'message': 'この旅行は削除されました。'})
        if trip.pin_enabled:
            token = self.request.headers.get('X-Pin-Token', '')
            expected = _generate_pin_token(trip.hash_url, self.request.user.id)
            if not hmac.compare_digest(token, expected):
                from rest_framework.exceptions import PermissionDenied
                raise PermissionDenied({'pin_required': True, 'hash_url': trip.hash_url})
        # PIN認証通過 or PIN不要 → ログイン済みユーザーを自動でメンバー登録する
        if self.request.user.is_authenticated:
            TripMember.objects.get_or_create(
                trip=trip, user=self.request.user,
                defaults={'role': 'member'}
            )
        return trip

    def destroy(self, request, *args, **kwargs):
        trip = super().get_object()  # get_object()ではなく直接取得（削除済みでも操作できるように）
        if trip.creator != request.user:
            return Response({'detail': '削除権限がありません。'}, status=status.HTTP_403_FORBIDDEN)
        # ソフトデリート: 物理削除せずフラグを立てる
        from django.utils import timezone
        trip.is_deleted = True
        trip.deleted_at = timezone.now()
        trip.save()
        return Response(status=status.HTTP_204_NO_CONTENT)


class PinVerifyView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request, hash_url):
        # URLパラメータ hash_url で旅行を特定する。
        try:
            trip = Trip.objects.get(hash_url=hash_url)
        except Trip.DoesNotExist:
            return Response({'detail': '旅行が見つかりません。'}, status=status.HTTP_404_NOT_FOUND)

        # PinVerifySerializer でリクエストボディの pin フィールドを検証する。
        serializer = PinVerifySerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        # DB に保存されている PIN と比較する。
        if trip.pin != serializer.validated_data['pin']:
            return Response({'detail': 'PINが正しくありません。'}, status=status.HTTP_400_BAD_REQUEST)

        # 認証成功 → HMACトークンを生成してクライアントに返す。
        # 次回から X-Pin-Token ヘッダーにこのトークンを付けることでPIN入力不要になる。
        token = _generate_pin_token(hash_url, request.user.id)
        return Response({'pin_token': token})


class TripJoinView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request, hash_url):
        try:
            trip = Trip.objects.get(hash_url=hash_url)
        except Trip.DoesNotExist:
            return Response({'detail': '旅行が見つかりません。'}, status=status.HTTP_404_NOT_FOUND)

        # get_or_create(): 既にメンバーなら既存レコードを返し、未登録なら作成する。
        # created（bool）で新規作成かどうかを判断できる（ここでは使っていない）。
        TripMember.objects.get_or_create(trip=trip, user=request.user, defaults={'role': 'member'})
        return Response(TripSerializer(trip, context={'request': request}).data)


# --- Spots ---

class SpotListCreateView(generics.ListCreateAPIView):
    permission_classes = [permissions.IsAuthenticated]

    # GET は軽量な SpotListSerializer、POST は comments を含む SpotSerializer を使う。
    def get_serializer_class(self):
        return SpotListSerializer if self.request.method == 'GET' else SpotSerializer

    # URLの hash_url を使って、その旅行のスポットだけをフィルタリングする。
    # self.kwargs: URLパラメータ（<str:hash_url>）が辞書形式で入っている。
    def get_queryset(self):
        return Spot.objects.filter(trip__hash_url=self.kwargs['hash_url'])

    # perform_create(): 保存前に追加フィールド（trip）をセットする。
    # serializer.save(trip=trip) → validated_data に trip を加えて save() を実行する。
    def perform_create(self, serializer):
        trip = Trip.objects.get(hash_url=self.kwargs['hash_url'])
        serializer.save(trip=trip)


# RetrieveUpdateDestroyAPIView: スポット単体の取得・更新・削除。
# URLに UUID が入る（/spots/<uuid:pk>/）。
class SpotDetailView(generics.RetrieveUpdateDestroyAPIView):
    serializer_class = SpotSerializer
    permission_classes = [permissions.IsAuthenticated]
    queryset = Spot.objects.all()
    lookup_field = 'pk'


class SpotOrderView(APIView):
    permission_classes = [permissions.IsAuthenticatedOrReadOnly]

    def post(self, request, hash_url):
        # リクエストボディ: { "orders": [{ "id": "...", "order_index": 0 }, ...] }
        orders = request.data.get('orders', [])
        for item in orders:
            # filter(...).update() → 対象レコードを直接 UPDATE する（インスタンスを作らない分高速）。
            Spot.objects.filter(id=item['id'], trip__hash_url=hash_url).update(order_index=item['order_index'])
        return Response({'detail': '順序を更新しました。'})


# --- Members ---

class TripMemberListView(generics.ListAPIView):
    serializer_class = TripMemberSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        return TripMember.objects.filter(trip__hash_url=self.kwargs['hash_url'])


class TripMemberAddView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request, hash_url):
        try:
            trip = Trip.objects.get(hash_url=hash_url)
        except Trip.DoesNotExist:
            return Response({'detail': '旅行が見つかりません。'}, status=status.HTTP_404_NOT_FOUND)

        if trip.creator != request.user:
            # 幹事のみ追加可能
            organizer = TripMember.objects.filter(trip=trip, user=request.user, role='organizer').exists()
            if not organizer:
                return Response({'detail': 'メンバー追加権限がありません。'}, status=status.HTTP_403_FORBIDDEN)

        email = request.data.get('email', '').strip()
        role = request.data.get('role', 'member')
        if not email:
            return Response({'detail': 'メールアドレスを入力してください。'}, status=status.HTTP_400_BAD_REQUEST)

        try:
            user = User.objects.get(email=email)
        except User.DoesNotExist:
            return Response({'detail': 'そのメールアドレスのユーザーが見つかりません。'}, status=status.HTTP_404_NOT_FOUND)

        member, created = TripMember.objects.get_or_create(trip=trip, user=user, defaults={'role': role})
        if not created:
            return Response({'detail': 'すでにメンバーです。'}, status=status.HTTP_400_BAD_REQUEST)

        return Response(TripMemberSerializer(member).data, status=status.HTTP_201_CREATED)


class TripMemberDetailView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    # 共通の権限チェックをメソッドに切り出して patch/delete で再利用する。
    def _get_trip_and_check_permission(self, request, hash_url):
        try:
            trip = Trip.objects.get(hash_url=hash_url)
        except Trip.DoesNotExist:
            return None, Response({'detail': '旅行が見つかりません。'}, status=status.HTTP_404_NOT_FOUND)
        is_organizer = (
            trip.creator == request.user or
            TripMember.objects.filter(trip=trip, user=request.user, role='organizer').exists()
        )
        if not is_organizer:
            return None, Response({'detail': '権限がありません。'}, status=status.HTTP_403_FORBIDDEN)
        return trip, None

    def patch(self, request, hash_url, member_id):
        trip, err = self._get_trip_and_check_permission(request, hash_url)
        if err:
            return err
        try:
            member = TripMember.objects.get(id=member_id, trip=trip)
        except TripMember.DoesNotExist:
            return Response({'detail': 'メンバーが見つかりません。'}, status=status.HTTP_404_NOT_FOUND)

        role = request.data.get('role')
        if role:
            member.role = role
            member.save()
        return Response(TripMemberSerializer(member).data)

    def delete(self, request, hash_url, member_id):
        trip, err = self._get_trip_and_check_permission(request, hash_url)
        if err:
            return err
        try:
            member = TripMember.objects.get(id=member_id, trip=trip)
        except TripMember.DoesNotExist:
            return Response({'detail': 'メンバーが見つかりません。'}, status=status.HTTP_404_NOT_FOUND)

        if member.user == trip.creator:
            return Response({'detail': '旅行作成者は削除できません。'}, status=status.HTTP_400_BAD_REQUEST)
        member.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


# --- Comments ---

class CommentListCreateView(generics.ListCreateAPIView):
    serializer_class = CommentSerializer
    permission_classes = [permissions.IsAuthenticated]

    # spot_pk は URL の <uuid:spot_pk> から来る（urls.py 参照）。
    def get_queryset(self):
        return Comment.objects.filter(spot_id=self.kwargs['spot_pk'])

    # perform_create(): spot_id と author をコメント保存時に自動でセットする。
    # クライアントから spot や author を送ってもらう必要がなくなる。
    def perform_create(self, serializer):
        author = self.request.user if self.request.user.is_authenticated else None
        serializer.save(spot_id=self.kwargs['spot_pk'], author=author)


# --- Expenses（費用管理） ---

class ExpenseListCreateView(generics.ListCreateAPIView):
    """
    GET  /trips/<hash_url>/expenses/  → その旅行の費用一覧を返す
    POST /trips/<hash_url>/expenses/  → 新しい費用を登録する

    Django の generics.ListCreateAPIView を使うことで、
    GETとPOSTの処理を自動でルーティングしてくれる。
    """
    serializer_class = ExpenseSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        # URLの hash_url から該当する旅行の費用だけを取得する。
        qs = Expense.objects.filter(
            trip__hash_url=self.kwargs['hash_url']
        ).prefetch_related('participants')
        # ?spot_id=<uuid> が指定された場合はそのスポットの費用だけに絞る。
        spot_id = self.request.query_params.get('spot_id')
        if spot_id:
            qs = qs.filter(spot_id=spot_id)
        return qs

    def create(self, request, *args, **kwargs):
        try:
            trip = Trip.objects.get(hash_url=self.kwargs['hash_url'])
        except Trip.DoesNotExist:
            return Response({'detail': '旅行が見つかりません。'}, status=status.HTTP_404_NOT_FOUND)

        participant_ids = request.data.get('participant_ids', [])

        # spot_id が送られてきた場合、そのスポットが同じ旅行のものか検証する。
        spot_id = request.data.get('spot')
        spot = None
        if spot_id:
            try:
                spot = Spot.objects.get(id=spot_id, trip=trip)
            except Spot.DoesNotExist:
                return Response({'detail': 'スポットが見つかりません。'}, status=status.HTTP_400_BAD_REQUEST)

        serializer = ExpenseSerializer(
            data=request.data,
            context={'participant_ids': participant_ids, 'request': request}
        )
        serializer.is_valid(raise_exception=True)
        serializer.save(trip=trip, spot=spot)
        return Response(serializer.data, status=status.HTTP_201_CREATED)


class ExpenseDetailView(generics.RetrieveUpdateDestroyAPIView):
    """
    GET    /expenses/<uuid:pk>/  → 費用の詳細を返す
    PATCH  /expenses/<uuid:pk>/  → 費用を更新する
    DELETE /expenses/<uuid:pk>/  → 費用を削除する
    """
    serializer_class = ExpenseSerializer
    permission_classes = [permissions.IsAuthenticated]
    queryset = Expense.objects.prefetch_related('participants').all()

    def update(self, request, *args, **kwargs):
        partial = kwargs.pop('partial', False)
        instance = self.get_object()
        participant_ids = request.data.get('participant_ids', None)
        serializer = ExpenseSerializer(
            instance,
            data=request.data,
            partial=partial,
            context={'participant_ids': participant_ids, 'request': request}
        )
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(serializer.data)


# --- Account ---

class AccountDeactivateView(APIView):
    """会員脱退: アカウントを無効化（is_active=False）してデータは保持する。"""
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request):
        user = request.user
        user.is_active = False
        user.save()
        return Response({'detail': '退会しました。またのご利用をお待ちしています。'})


class ChangeUsernameView(APIView):
    """ニックネーム変更: ログイン中のユーザーのユーザー名を変更する。"""
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request):
        new_username = request.data.get('username', '').strip()
        if not new_username:
            return Response({'detail': 'ユーザー名を入力してください。'}, status=status.HTTP_400_BAD_REQUEST)
        if len(new_username) > 30:
            return Response({'detail': 'ユーザー名は30文字以内で入力してください。'}, status=status.HTTP_400_BAD_REQUEST)
        if User.objects.filter(username=new_username).exclude(pk=request.user.pk).exists():
            return Response({'detail': 'このユーザー名はすでに使用されています。'}, status=status.HTTP_400_BAD_REQUEST)
        request.user.username = new_username
        request.user.save()
        return Response({'detail': 'ユーザー名を変更しました。', 'username': new_username})


class ChangePasswordView(APIView):
    """ログイン中のパスワード変更: 現在のパスワードを確認してから新しいパスワードに変更する。"""
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request):
        user = request.user
        current = request.data.get('current_password', '')
        new_pw = request.data.get('new_password', '')

        if not user.check_password(current):
            return Response({'detail': '現在のパスワードが正しくありません。'}, status=status.HTTP_400_BAD_REQUEST)
        if len(new_pw) < 8:
            return Response({'detail': 'パスワードは8文字以上で設定してください。'}, status=status.HTTP_400_BAD_REQUEST)

        user.set_password(new_pw)
        user.save()
        return Response({'detail': 'パスワードを変更しました。再度ログインしてください。'})


class SendPasswordResetView(APIView):
    """パスワードリセット STEP1: 認証コードをメールで送信する（未ログイン用）。"""
    permission_classes = [permissions.AllowAny]

    def post(self, request):
        email = request.data.get('email', '').strip()
        if not email:
            return Response({'detail': 'メールアドレスを入力してください。'}, status=status.HTTP_400_BAD_REQUEST)
        # ユーザーが存在するか確認（存在しなくても同じレスポンスを返してユーザー列挙を防ぐ）
        if not User.objects.filter(email=email, is_active=True).exists():
            return Response({'detail': '認証コードを送りました。メールをご確認ください。'})
        try:
            resp = http_client.post(
                f'{EMAIL_SERVICE_URL}/sendMail/join',
                json={'email': email},
                timeout=10,
            )
            if resp.text.strip() == 'success':
                return Response({'detail': '認証コードを送りました。メールをご確認ください。'})
            return Response({'detail': 'メール送信に失敗しました。'}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
        except Exception:
            return Response({'detail': 'メールサービスに接続できません。'}, status=status.HTTP_503_SERVICE_UNAVAILABLE)


class ResetPasswordView(APIView):
    """パスワードリセット STEP2: 認証トークン確認後、新しいパスワードに変更する（未ログイン用）。"""
    permission_classes = [permissions.AllowAny]

    def post(self, request):
        email = request.data.get('email', '').strip()
        verification_token = request.data.get('verification_token', '').strip()
        new_password = request.data.get('new_password', '').strip()

        if not all([email, verification_token, new_password]):
            return Response({'detail': 'パラメータが不足しています。'}, status=status.HTTP_400_BAD_REQUEST)
        if len(new_password) < 8:
            return Response({'detail': 'パスワードは8文字以上で設定してください。'}, status=status.HTTP_400_BAD_REQUEST)

        expected = _generate_email_verification_token(email)
        if not hmac.compare_digest(verification_token, expected):
            return Response({'detail': '認証コードが無効です。もう一度やり直してください。'}, status=status.HTTP_400_BAD_REQUEST)

        try:
            user = User.objects.get(email=email, is_active=True)
        except User.DoesNotExist:
            return Response({'detail': 'ユーザーが見つかりません。'}, status=status.HTTP_404_NOT_FOUND)

        user.set_password(new_password)
        user.save()
        return Response({'detail': 'パスワードを再設定しました。新しいパスワードでログインしてください。'})


class SettlementView(APIView):
    """
    GET /trips/<hash_url>/settlement/

    各メンバーの収支を計算して「誰が誰にいくら払うか」のリストを返す。

    アルゴリズム:
    1. 各費用について、参加者が支払者に「割り勘額（amount / 参加人数）」を負う。
    2. 全費用を集計して、メンバーごとの純収支（balance）を計算する。
       balance > 0: 受け取るべき金額がある（多く払った人）
       balance < 0: 支払うべき金額がある（少なく払った人）
    3. Greedyアルゴリズムでbalanceをゼロに近づけながら「誰→誰へいくら」を決める。
    """
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request, hash_url):
        try:
            trip = Trip.objects.get(hash_url=hash_url)
        except Trip.DoesNotExist:
            return Response({'detail': '旅行が見つかりません。'}, status=status.HTTP_404_NOT_FOUND)

        # その旅行の全費用と参加者を一括取得する。
        expenses = Expense.objects.filter(trip=trip).prefetch_related('participants', 'payer__user')

        # --- STEP 1: メンバーごとの純収支を計算する ---
        # balance[member_id] = 受け取るべき金額（正）または払うべき金額（負）
        balance: dict[int, Decimal] = {}
        member_names: dict[int, str] = {}

        for expense in expenses:
            if not expense.payer:
                continue
            participants = list(expense.participants.all())
            if not participants:
                continue

            # 割り勘額（小数点以下2桁で計算）。
            each_share = expense.amount / Decimal(len(participants))

            payer_id = expense.payer.id
            payer_name = expense.payer.user.username if expense.payer.user else '不明'
            member_names[payer_id] = payer_name

            # 支払者の収支に「立替えた合計額」を加算する。
            balance[payer_id] = balance.get(payer_id, Decimal('0')) + expense.amount

            # 参加者全員の収支から「割り勘額」を引く（負債）。
            for participant in participants:
                pid = participant.id
                pname = participant.user.username if participant.user else '不明'
                member_names[pid] = pname
                balance[pid] = balance.get(pid, Decimal('0')) - each_share

        # --- STEP 2: 精算リストを作る（Greedy アルゴリズム） ---
        # balance が正の人（受け取る側）と負の人（払う側）をリストアップする。
        creditors = sorted(
            [(mid, b) for mid, b in balance.items() if b > Decimal('0.01')],
            key=lambda x: -x[1]
        )
        debtors = sorted(
            [(mid, -b) for mid, b in balance.items() if b < Decimal('-0.01')],
            key=lambda x: -x[1]
        )

        settlements = []
        i, j = 0, 0
        while i < len(creditors) and j < len(debtors):
            cred_id, cred_amount = creditors[i]
            debt_id, debt_amount = debtors[j]

            # 払う額は「負債額」と「受取額」の小さい方。
            transfer = min(cred_amount, debt_amount)
            settlements.append({
                'from_member_id': debt_id,
                'from_member_name': member_names.get(debt_id, '不明'),
                'to_member_id': cred_id,
                'to_member_name': member_names.get(cred_id, '不明'),
                'amount': round(float(transfer), 0),
                'currency': trip.currency,
            })

            # 残高を更新する。
            creditors[i] = (cred_id, cred_amount - transfer)
            debtors[j] = (debt_id, debt_amount - transfer)
            if creditors[i][1] <= Decimal('0.01'):
                i += 1
            if debtors[j][1] <= Decimal('0.01'):
                j += 1

        # --- STEP 3: メンバーごとの収支サマリも返す ---
        balance_summary = [
            {
                'member_id': mid,
                'member_name': member_names.get(mid, '不明'),
                'balance': round(float(b), 0),
                'currency': trip.currency,
            }
            for mid, b in sorted(balance.items(), key=lambda x: -x[1])
        ]

        return Response({
            'settlements': settlements,
            'balance_summary': balance_summary,
            'currency': trip.currency,
        })
