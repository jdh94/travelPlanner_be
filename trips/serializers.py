# DRF（Django REST Framework）のシリアライザ:
# モデル（Pythonオブジェクト）↔ JSON（APIのデータ）を変換する橋渡し役。
# ① クライアントからのJSONを受け取り、バリデーション後にDBへ保存（デシリアライズ）
# ② DBのオブジェクトをJSONに変換してレスポンスとして返す（シリアライズ）
from rest_framework import serializers
from django.contrib.auth import get_user_model
from .models import Trip, TripMember, Spot, Comment, Image

# get_user_model(): settings.AUTH_USER_MODEL で指定したモデルを取得する。
# User を直接 import するより、この方法が推奨される（カスタムモデルに対応）。
User = get_user_model()


class UserSerializer(serializers.ModelSerializer):
    # ModelSerializer: モデルのフィールドを自動でシリアライザフィールドに変換する。
    # fields に列挙したものだけが API のレスポンスに含まれる。
    class Meta:
        model = User
        fields = ['id', 'email', 'username', 'notification_enabled']
        # read_only_fields: レスポンスには含まれるが、リクエストからの書き込みは無視される。
        read_only_fields = ['id']


class RegisterSerializer(serializers.ModelSerializer):
    # write_only=True → リクエスト受信時のみ使用。レスポンスに password は含まれない。
    # min_length=8 → DRF のバリデーションで8文字未満はエラーにする。
    password = serializers.CharField(write_only=True, min_length=8)

    class Meta:
        model = User
        fields = ['email', 'username', 'password']

    # create() をオーバーライドして、Djangoの create_user() を使う。
    # create_user() は password を自動でハッシュ化してDBに保存する（平文では保存しない）。
    def create(self, validated_data):
        return User.objects.create_user(
            email=validated_data['email'],
            username=validated_data['username'],
            password=validated_data['password'],
        )


class CommentSerializer(serializers.ModelSerializer):
    # SerializerMethodField: モデルに存在しない計算済みフィールドを定義する。
    # get_<フィールド名>() という名前のメソッドが自動で呼ばれる。
    author_name = serializers.SerializerMethodField()

    class Meta:
        model = Comment
        fields = ['id', 'spot', 'author', 'author_name', 'content', 'created_at']
        # spot と author は views.py の perform_create() でセットするため
        # クライアントから送ってもらう必要がない → read_only にする。
        read_only_fields = ['id', 'spot', 'author', 'created_at']

    def get_author_name(self, obj):
        # obj はシリアライズ対象の Comment インスタンス。
        if obj.author:
            return obj.author.username
        return obj.guest_name or '匿名'


class SpotSerializer(serializers.ModelSerializer):
    # many=True, read_only=True: Spot に紐づく Comment を全件ネストして返す。
    # SpotのJSONの中に "comments": [...] が含まれるようになる。
    comments = CommentSerializer(many=True, read_only=True)

    class Meta:
        model = Spot
        fields = [
            'id', 'trip', 'name', 'place_id', 'category', 'address',
            'latitude', 'longitude', 'visit_time', 'duration_min',
            'memo', 'order_index', 'estimated_cost', 'comments',
            'created_at', 'updated_at',
        ]
        # trip は views.py の perform_create() で hash_url から取得してセットする。
        read_only_fields = ['id', 'trip', 'created_at', 'updated_at']


# スポット一覧取得専用のシリアライザ（コメントを含まない軽量版）。
# GET /trips/<hash_url>/spots/ は SpotListSerializer、
# POST /trips/<hash_url>/spots/ は SpotSerializer と使い分ける。
class SpotListSerializer(serializers.ModelSerializer):
    class Meta:
        model = Spot
        fields = [
            'id', 'name', 'place_id', 'category', 'address',
            'latitude', 'longitude', 'visit_time', 'duration_min',
            'memo', 'order_index', 'estimated_cost',
        ]
        read_only_fields = ['id']


class TripMemberSerializer(serializers.ModelSerializer):
    user_email = serializers.SerializerMethodField()
    user_name = serializers.SerializerMethodField()

    class Meta:
        model = TripMember
        fields = ['id', 'user', 'user_email', 'user_name', 'guest_token', 'role', 'joined_at']

    def get_user_email(self, obj):
        return obj.user.email if obj.user else None

    def get_user_name(self, obj):
        return obj.user.username if obj.user else obj.guest_token[:8] + '...'


class TripSerializer(serializers.ModelSerializer):
    # Trip に紐づく Spot・Member を全件ネストしてレスポンスに含める。
    # read_only=True なので、このシリアライザ経由で Spot を作成することはできない。
    spots = SpotListSerializer(many=True, read_only=True)
    members = TripMemberSerializer(many=True, read_only=True)
    # SerializerMethodField でモデルにないフィールドを追加する。
    share_url = serializers.SerializerMethodField()
    # write_only=True → PINはリクエストでのみ受け取り、レスポンスには含めない（セキュリティ）。
    # required=False, allow_blank=True → PIN変更しない場合は省略可。
    pin = serializers.CharField(max_length=4, min_length=4, write_only=True, required=False, allow_blank=True)

    class Meta:
        model = Trip
        fields = [
            'id', 'title', 'description', 'start_date', 'end_date',
            'hash_url', 'share_url', 'pin_enabled', 'pin', 'visibility', 'currency',
            'creator', 'spots', 'members', 'created_at', 'updated_at',
        ]
        read_only_fields = ['id', 'hash_url', 'share_url', 'created_at', 'updated_at']

    def get_share_url(self, obj):
        # obj は Trip インスタンス。hash_url を使ってフロントエンドの URL を返す。
        return f'/trips/{obj.hash_url}'


# 旅行作成専用のシリアライザ。
# TripSerializer はネストデータを含む複雑な構造なので、作成時は別クラスを使う。
class TripCreateSerializer(serializers.ModelSerializer):
    class Meta:
        model = Trip
        fields = ['title', 'description', 'start_date', 'end_date', 'currency', 'visibility']

    def create(self, validated_data):
        # self.context['request'] → views.py から渡されたリクエストオブジェクト。
        # シリアライザ単体ではリクエストにアクセスできないので context 経由で受け取る。
        request = self.context.get('request')
        trip = Trip(**validated_data)
        if request and request.user.is_authenticated:
            trip.creator = request.user
        trip.save()
        # 作成者を自動的に 'organizer' としてメンバーに追加する。
        if request and request.user.is_authenticated:
            TripMember.objects.create(trip=trip, user=request.user, role='organizer')
        return trip


# PIN検証専用のシリアライザ（モデルに紐づかない単純なバリデーション用）。
# ModelSerializer ではなく Serializer を直接継承する。
class PinVerifySerializer(serializers.Serializer):
    pin = serializers.CharField(max_length=4, min_length=4)
