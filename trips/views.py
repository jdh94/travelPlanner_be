import hmac
import hashlib
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

from .models import Trip, TripMember, Spot, Comment
from .serializers import (
    UserSerializer, RegisterSerializer,
    TripSerializer, TripCreateSerializer, PinVerifySerializer,
    SpotSerializer, SpotListSerializer, CommentSerializer,
    TripMemberSerializer,
)

User = get_user_model()


# --- Auth ---

# generics.CreateAPIView: POST リクエストだけを受け付ける汎用ビュー。
# create() メソッドでシリアライザのバリデーション→保存を自動処理する。
class RegisterView(generics.CreateAPIView):
    queryset = User.objects.all()
    serializer_class = RegisterSerializer
    # AllowAny: 未ログインユーザーも呼べる（登録は誰でもできる必要があるため）。
    permission_classes = [permissions.AllowAny]

    # create() をオーバーライドして、登録後にJWTトークンをレスポンスに含める。
    def create(self, request, *args, **kwargs):
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
            # 自分が作った旅行 OR 自分がメンバーの旅行 を重複なしで返す。
            return Trip.objects.filter(
                Q(creator=user) | Q(members__user=user)
            ).distinct()
        return Trip.objects.filter(visibility='public')

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
        # super().get_object() → 親クラスが lookup_field で Trip を取得する。
        trip = super().get_object()
        if trip.pin_enabled:
            # クライアントが送ってきたカスタムヘッダー X-Pin-Token を取得する。
            token = self.request.headers.get('X-Pin-Token', '')
            expected = _generate_pin_token(trip.hash_url, self.request.user.id)
            # compare_digest(): タイミング攻撃（timing attack）を防ぐ定数時間比較。
            # == 演算子は一致しない文字を見つけた時点で処理を止めるため、攻撃に弱い。
            if not hmac.compare_digest(token, expected):
                from rest_framework.exceptions import PermissionDenied
                # pin_required: True をレスポンスに含めることで、
                # フロントエンドがPINページへリダイレクトするかどうかを判断できる。
                raise PermissionDenied({'pin_required': True, 'hash_url': trip.hash_url})
        return trip

    def destroy(self, request, *args, **kwargs):
        trip = self.get_object()
        # 作成者だけが削除できる。メンバーは削除できない。
        if trip.creator != request.user:
            return Response({'detail': '削除権限がありません。'}, status=status.HTTP_403_FORBIDDEN)
        trip.delete()
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
