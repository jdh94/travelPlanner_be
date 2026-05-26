import uuid
import hashlib
# Django ORM: テーブル定義をPythonクラスで書く。
# django.db.models を継承したクラス1つ = DBテーブル1つ。
# マイグレーション（makemigrations / migrate）を実行すると
# このクラスの内容から CREATE TABLE SQL が自動生成される。
from django.db import models
# AbstractUser: Djangoが提供するデフォルトのユーザーモデルを継承して
# 独自フィールドを追加できるベースクラス。
# パスワードのハッシュ化・認証ロジックはすでに内包されている。
from django.contrib.auth.models import AbstractUser


# AbstractUser を継承することで、Django標準の username/password/is_active 等を
# そのまま引き継ぎながら、email や notification_enabled を追加できる。
class User(AbstractUser):
    # unique=True → DBにUNIQUE制約が付く。同じメールで2件登録不可。
    email = models.EmailField(unique=True)
    notification_enabled = models.BooleanField(default=True)
    # auto_now_add=True → レコード作成時に自動で現在時刻を入れる。更新はしない。
    created_at = models.DateTimeField(auto_now_add=True)

    # USERNAME_FIELD: 認証（ログイン）に使うフィールドを email に変更。
    # デフォルトは 'username'。これを変えることでメールアドレスでログインできる。
    USERNAME_FIELD = 'email'
    # REQUIRED_FIELDS: createsuperuser コマンドで追加入力を求めるフィールド。
    REQUIRED_FIELDS = ['username']

    class Meta:
        # db_table: 実際のMySQLテーブル名を指定する。
        # 指定しないと Django が "trips_user" のような名前を自動生成する。
        db_table = 'users'


class Trip(models.Model):
    # choices: フィールドに入れられる値を制限するリスト。
    # DB上は 'public' 等の文字列で保存されるが、管理画面では '公開' と表示される。
    VISIBILITY_CHOICES = [
        ('public', '公開'),
        ('private', '非公開（PIN保護）'),
    ]
    CURRENCY_CHOICES = [
        ('JPY', '円'),
        ('KRW', 'ウォン'),
        ('USD', 'ドル'),
    ]

    # UUIDField: 連番(1,2,3...)の代わりにランダムな一意IDを使う。
    # default=uuid.uuid4 → 保存時に自動生成。editable=False → 管理画面で編集不可。
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    title = models.CharField(max_length=200)
    # blank=True → バリデーション上「空文字OK」。null=True がないのでDBはNULLではなく空文字で保存。
    description = models.TextField(blank=True)
    start_date = models.DateField()
    end_date = models.DateField()
    # editable=False → シリアライザやフォームから書き込み不可。save()メソッドで自動生成。
    hash_url = models.CharField(max_length=64, unique=True, editable=False)
    pin = models.CharField(max_length=4, blank=True)
    pin_enabled = models.BooleanField(default=False)
    visibility = models.CharField(max_length=10, choices=VISIBILITY_CHOICES, default='public')
    currency = models.CharField(max_length=3, choices=CURRENCY_CHOICES, default='JPY')
    # ForeignKey: 「多対1」のリレーション。Trip 多 → User 1。
    # on_delete=SET_NULL → ユーザーが削除されても旅行は残り、creator が NULL になる。
    # related_name='created_trips' → user.created_trips.all() で逆引きできる。
    creator = models.ForeignKey(
        'User', on_delete=models.SET_NULL, null=True, blank=True, related_name='created_trips'
    )
    guest_token = models.CharField(max_length=64, blank=True)
    # ソフトデリート: 物理削除せずフラグで論理削除する。
    is_deleted = models.BooleanField(default=False)
    deleted_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    # auto_now=True → レコードを save() するたびに自動で現在時刻に更新される。
    updated_at = models.DateTimeField(auto_now=True)

    # save() をオーバーライドすることで、保存前に独自ロジックを差し込める。
    # super().save() を呼ぶことで元の保存処理も実行する（必須）。
    def save(self, *args, **kwargs):
        # hash_url が未設定の場合だけ生成する（既存レコードの上書きを防ぐ）。
        # UUID を SHA-256 でハッシュ化して先頭32文字を使う。推測不可能な URL になる。
        if not self.hash_url:
            self.hash_url = hashlib.sha256(str(self.id).encode()).hexdigest()[:32]
        super().save(*args, **kwargs)

    class Meta:
        db_table = 'trips'
        # ordering: QuerySet のデフォルト並び順。'-' は降順（新しい順）。
        ordering = ['-created_at']


class TripMember(models.Model):
    ROLE_CHOICES = [
        ('organizer', '幹事'),
        ('member', 'メンバー'),
        ('viewer', '閲覧者'),
    ]

    # on_delete=CASCADE → Trip が削除されたとき、紐づく TripMember も全部消える。
    # related_name='members' → trip.members.all() で逆引きできる。
    trip = models.ForeignKey(Trip, on_delete=models.CASCADE, related_name='members')
    user = models.ForeignKey('User', on_delete=models.CASCADE, null=True, blank=True)
    guest_token = models.CharField(max_length=64, blank=True)
    role = models.CharField(max_length=10, choices=ROLE_CHOICES, default='member')
    notification_enabled = models.BooleanField(default=True)
    joined_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'trip_members'


class Spot(models.Model):
    CATEGORY_CHOICES = [
        ('restaurant', '飲食店'),
        ('attraction', '観光地'),
        ('accommodation', '宿泊'),
        ('transport', '交通'),
        ('other', 'その他'),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    # CASCADE: Spot は Trip に従属。Trip が消えたら Spot も消える。
    trip = models.ForeignKey(Trip, on_delete=models.CASCADE, related_name='spots')
    name = models.CharField(max_length=200)
    place_id = models.CharField(max_length=100, blank=True)
    category = models.CharField(max_length=15, choices=CATEGORY_CHOICES, default='other')
    address = models.TextField(blank=True)
    # null=True, blank=True → DBにNULLが入ってもOK、かつバリデーションでも空でOK。
    latitude = models.DecimalField(max_digits=10, decimal_places=7, null=True, blank=True)
    longitude = models.DecimalField(max_digits=10, decimal_places=7, null=True, blank=True)
    visit_time = models.TimeField(null=True, blank=True)
    duration_min = models.IntegerField(null=True, blank=True)
    memo = models.TextField(blank=True, max_length=500)
    order_index = models.IntegerField(default=0)
    estimated_cost = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    # スポット固有の通貨。空欄の場合は旅行の通貨をデフォルトとして使う。
    currency = models.CharField(max_length=3, choices=Trip.CURRENCY_CHOICES, blank=True, default='')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'spots'
        # order_index の昇順でスポットを並べる（タイムライン順）。
        ordering = ['order_index']


class Comment(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    spot = models.ForeignKey(Spot, on_delete=models.CASCADE, related_name='comments')
    # SET_NULL: ユーザーが退会しても、コメント本文は残す。
    author = models.ForeignKey('User', on_delete=models.SET_NULL, null=True, blank=True)
    guest_name = models.CharField(max_length=50, blank=True)
    content = models.TextField(max_length=1000)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'comments'
        ordering = ['created_at']


class Image(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    trip = models.ForeignKey(Trip, on_delete=models.CASCADE, null=True, blank=True, related_name='images')
    spot = models.ForeignKey(Spot, on_delete=models.CASCADE, null=True, blank=True, related_name='images')
    url = models.URLField(max_length=500)
    uploaded_by = models.ForeignKey('User', on_delete=models.SET_NULL, null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'images'


class Expense(models.Model):
    # 通貨の選択肢。Trip.CURRENCY_CHOICES と同じ値を使う。
    CURRENCY_CHOICES = [
        ('JPY', '円'),
        ('KRW', 'ウォン'),
        ('USD', 'ドル'),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    # CASCADE: Trip が削除されたら費用も全て削除する。
    trip = models.ForeignKey(Trip, on_delete=models.CASCADE, related_name='expenses')
    # SET_NULL: スポットが削除されても費用レコードは残す（旅行全体の費用として扱う）。
    # null=True, blank=True → スポットに紐づかない旅行全体の費用も登録できる。
    spot = models.ForeignKey(
        Spot, on_delete=models.SET_NULL, null=True, blank=True, related_name='expenses'
    )
    # SET_NULL: メンバーが削除されても費用レコードは残す（payer が NULL になる）。
    payer = models.ForeignKey(
        TripMember, on_delete=models.SET_NULL, null=True, blank=True, related_name='paid_expenses'
    )
    name = models.CharField(max_length=200)
    # max_digits=12, decimal_places=2 → 最大9,999,999,999.99まで対応。
    amount = models.DecimalField(max_digits=12, decimal_places=2)
    currency = models.CharField(max_length=3, choices=CURRENCY_CHOICES, default='JPY')
    date = models.DateField(null=True, blank=True)
    memo = models.TextField(blank=True, max_length=500)
    # ManyToManyField: 費用を割り勘する参加者リスト（中間テーブル expense_participants が自動生成）。
    # through='ExpenseParticipant' を使わず、シンプルな M2M にする。
    participants = models.ManyToManyField(
        TripMember, related_name='participating_expenses', blank=True
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'expenses'
        ordering = ['date', 'created_at']


class NotificationLog(models.Model):
    STATUS_CHOICES = [
        ('SENT', '送信済'),
        ('FAILED', '失敗'),
        ('SKIPPED', 'スキップ'),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey('User', on_delete=models.CASCADE)
    trip = models.ForeignKey(Trip, on_delete=models.CASCADE)
    status = models.CharField(max_length=10, choices=STATUS_CHOICES)
    sent_at = models.DateTimeField(auto_now_add=True)
    error_message = models.TextField(blank=True)

    class Meta:
        db_table = 'notifications_log'
