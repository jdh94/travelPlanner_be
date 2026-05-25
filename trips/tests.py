"""
TravelPlaner バックエンド テストコード
======================================

【Django テストの仕組み】
- TestCase を継承したクラスを作る（JUnit の @Test クラスと同じ）
- def test_〇〇(self): で始まるメソッドが自動でテストとして実行される
- setUp(): 各テストメソッドの前に毎回実行される（JUnit の @BeforeEach）
- self.client: Django が提供するテスト用 HTTP クライアント（ブラウザの代わり）
- テスト用 DB が自動で作られ、テスト後に自動削除される（本番DBは絶対に変わらない）

【実行方法】
  python3 manage.py test trips                               # trips アプリ全テスト
  python3 manage.py test trips.tests.AuthTest                # クラス単位
  python3 manage.py test trips.tests.AuthTest.test_ログイン成功  # メソッド単位
"""

from django.test import TestCase
from rest_framework.test import APIClient
from rest_framework import status
from .models import Trip, TripMember, Spot, Expense
from django.contrib.auth import get_user_model

User = get_user_model()


# ============================================================
# ヘルパー関数
# ============================================================

def create_user(email='test@example.com', username='testuser', password='password123'):
    """テスト用ユーザーを作成するヘルパー関数。"""
    return User.objects.create_user(email=email, username=username, password=password)


def get_auth_client(user, password='password123'):
    """
    JWT トークンを取得してヘッダーにセットした APIClient を返す。
    credentials() で以降のリクエストに Authorization ヘッダーを自動付与する。
    """
    client = APIClient()
    response = client.post('/api/auth/login/', {
        'email': user.email,
        'password': password,
    }, format='json')
    token = response.data['access']
    client.credentials(HTTP_AUTHORIZATION=f'Bearer {token}')
    return client


# ============================================================
# 1. 認証テスト
# ============================================================

class AuthTest(TestCase):
    """ログイン・ユーザー情報取得のテスト。"""

    def setUp(self):
        self.user = create_user()

    def test_ログイン成功(self):
        """正しいメール・パスワードで JWT トークンが返ることを確認する。"""
        response = self.client.post('/api/auth/login/', {
            'email': 'test@example.com',
            'password': 'password123',
        }, content_type='application/json')

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn('access', response.json())
        self.assertIn('refresh', response.json())

    def test_ログイン失敗_パスワード間違い(self):
        """間違ったパスワードでは 401 が返ることを確認する。"""
        response = self.client.post('/api/auth/login/', {
            'email': 'test@example.com',
            'password': 'wrongpassword',
        }, content_type='application/json')

        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_ログイン失敗_存在しないメール(self):
        """存在しないメールアドレスでは 401 が返ることを確認する。"""
        response = self.client.post('/api/auth/login/', {
            'email': 'notexist@example.com',
            'password': 'password123',
        }, content_type='application/json')

        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_自分の情報取得(self):
        """ログイン済みユーザーが /auth/me/ で自分の情報を取得できることを確認する。"""
        client = get_auth_client(self.user)
        response = client.get('/api/auth/me/')

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json()['email'], 'test@example.com')

    def test_未ログインはme取得不可(self):
        """未認証のリクエストは 401 が返ることを確認する。"""
        response = self.client.get('/api/auth/me/')
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)


# ============================================================
# 2. 旅行テスト
# ============================================================

class TripTest(TestCase):
    """旅行の作成・取得・更新・削除のテスト。"""

    def setUp(self):
        self.user = create_user()
        self.client = get_auth_client(self.user)

        # テスト用の旅行を1件作成しておく。
        res = self.client.post('/api/trips/', {
            'title': 'テスト旅行',
            'description': 'テスト用の旅行です',
            'start_date': '2025-08-01',
            'end_date': '2025-08-05',
            'currency': 'JPY',
            'visibility': 'public',
        }, format='json')
        self.trip = res.json()
        self.hash_url = self.trip['hash_url']

    def test_旅行一覧取得(self):
        """自分の旅行が一覧に含まれることを確認する。"""
        response = self.client.get('/api/trips/')

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.json()), 1)
        self.assertEqual(response.json()[0]['title'], 'テスト旅行')

    def test_旅行作成(self):
        """旅行が正しく作成されることを確認する。"""
        response = self.client.post('/api/trips/', {
            'title': '新しい旅行',
            'start_date': '2025-09-01',
            'end_date': '2025-09-03',
            'currency': 'JPY',
            'visibility': 'private',
        }, format='json')

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.json()['title'], '新しい旅行')
        # hash_url が自動生成されることを確認する。
        self.assertIsNotNone(response.json()['hash_url'])

    def test_旅行詳細取得(self):
        """hash_url で旅行の詳細が取得できることを確認する。"""
        response = self.client.get(f'/api/trips/{self.hash_url}/')

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json()['title'], 'テスト旅行')

    def test_旅行更新(self):
        """旅行タイトルを PATCH で更新できることを確認する。"""
        response = self.client.patch(f'/api/trips/{self.hash_url}/', {
            'title': '更新後タイトル',
        }, format='json')

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json()['title'], '更新後タイトル')

    def test_旅行削除(self):
        """作成者が旅行を削除できることを確認する。"""
        response = self.client.delete(f'/api/trips/{self.hash_url}/')
        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)

        # 削除後は 404 が返ることを確認する。
        response = self.client.get(f'/api/trips/{self.hash_url}/')
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_他人は旅行削除不可(self):
        """作成者以外は旅行を削除できないことを確認する。"""
        other_user = create_user(email='other@example.com', username='other')
        other_client = get_auth_client(other_user)

        response = other_client.delete(f'/api/trips/{self.hash_url}/')
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_未ログインは旅行取得不可(self):
        """未認証では旅行一覧を取得できないことを確認する。"""
        unauth_client = APIClient()
        response = unauth_client.get('/api/trips/')
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)


# ============================================================
# 3. スポットテスト
# ============================================================

class SpotTest(TestCase):
    """スポットの追加・取得・削除のテスト。"""

    def setUp(self):
        self.user = create_user()
        self.client = get_auth_client(self.user)

        res = self.client.post('/api/trips/', {
            'title': 'テスト旅行',
            'start_date': '2025-08-01',
            'end_date': '2025-08-05',
            'currency': 'JPY',
            'visibility': 'public',
        }, format='json')
        self.hash_url = res.json()['hash_url']

    def test_スポット追加(self):
        """スポットを旅行に追加できることを確認する。"""
        response = self.client.post(f'/api/trips/{self.hash_url}/spots/', {
            'name': '東京タワー',
            'category': 'attraction',
            'address': '東京都港区芝公園4-2-8',
        }, format='json')

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.json()['name'], '東京タワー')

    def test_スポット一覧取得(self):
        """旅行のスポット一覧が取得できることを確認する。"""
        self.client.post(f'/api/trips/{self.hash_url}/spots/', {
            'name': '東京タワー', 'category': 'attraction',
        }, format='json')
        self.client.post(f'/api/trips/{self.hash_url}/spots/', {
            'name': '浅草寺', 'category': 'attraction',
        }, format='json')

        response = self.client.get(f'/api/trips/{self.hash_url}/spots/')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.json()), 2)

    def test_スポット削除(self):
        """スポットを削除できることを確認する。"""
        res = self.client.post(f'/api/trips/{self.hash_url}/spots/', {
            'name': '削除されるスポット', 'category': 'other',
        }, format='json')
        spot_id = res.json()['id']

        response = self.client.delete(f'/api/spots/{spot_id}/')
        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)

    def test_スポット更新(self):
        """スポットの名前を更新できることを確認する。"""
        res = self.client.post(f'/api/trips/{self.hash_url}/spots/', {
            'name': '旧スポット名', 'category': 'other',
        }, format='json')
        spot_id = res.json()['id']

        response = self.client.patch(f'/api/spots/{spot_id}/', {
            'name': '新スポット名',
        }, format='json')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json()['name'], '新スポット名')


# ============================================================
# 4. 費用・精算テスト
# ============================================================

class ExpenseTest(TestCase):
    """費用の登録・取得・精算計算のテスト。"""

    def setUp(self):
        # ユーザー2人を用意する（割り勘テスト用）。
        self.user1 = create_user(email='user1@example.com', username='user1')
        self.user2 = create_user(email='user2@example.com', username='user2')
        self.client = get_auth_client(self.user1)

        # 旅行を作成する。
        res = self.client.post('/api/trips/', {
            'title': 'テスト旅行',
            'start_date': '2025-08-01',
            'end_date': '2025-08-05',
            'currency': 'JPY',
            'visibility': 'public',
        }, format='json')
        self.hash_url = res.json()['hash_url']

        # user2 を旅行メンバーに追加する。
        self.client.post(f'/api/trips/{self.hash_url}/members/add/', {
            'email': 'user2@example.com',
            'role': 'member',
        }, format='json')

        # メンバーIDを取得して保存する。
        members = self.client.get(f'/api/trips/{self.hash_url}/members/').json()
        self.member1_id = next(m['id'] for m in members if m['user_email'] == 'user1@example.com')
        self.member2_id = next(m['id'] for m in members if m['user_email'] == 'user2@example.com')

    def test_費用登録(self):
        """費用を旅行に登録できることを確認する。"""
        response = self.client.post(f'/api/trips/{self.hash_url}/expenses/', {
            'name': '夕食',
            'amount': '3000',
            'currency': 'JPY',
            'payer': self.member1_id,
            'participant_ids': [self.member1_id, self.member2_id],
        }, format='json')

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.json()['name'], '夕食')
        self.assertEqual(float(response.json()['amount']), 3000.0)

    def test_費用一覧取得(self):
        """登録した費用が一覧に含まれることを確認する。"""
        self.client.post(f'/api/trips/{self.hash_url}/expenses/', {
            'name': '夕食',
            'amount': '3000',
            'currency': 'JPY',
            'payer': self.member1_id,
            'participant_ids': [self.member1_id, self.member2_id],
        }, format='json')

        response = self.client.get(f'/api/trips/{self.hash_url}/expenses/')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.json()), 1)

    def test_精算計算(self):
        """
        user1 が 3000円 立替 → user2 は 1500円 払う必要がある。
        settlement API が正しい精算リストを返すことを確認する。
        """
        self.client.post(f'/api/trips/{self.hash_url}/expenses/', {
            'name': '夕食',
            'amount': '3000',
            'currency': 'JPY',
            'payer': self.member1_id,
            'participant_ids': [self.member1_id, self.member2_id],
        }, format='json')

        response = self.client.get(f'/api/trips/{self.hash_url}/settlement/')
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        settlements = response.json()['settlements']
        # 精算が1件（user2 → user1 へ 1500円）あることを確認する。
        self.assertEqual(len(settlements), 1)
        self.assertEqual(settlements[0]['amount'], 1500.0)
        self.assertEqual(settlements[0]['from_member_name'], 'user2')
        self.assertEqual(settlements[0]['to_member_name'], 'user1')

    def test_費用削除(self):
        """費用を削除できることを確認する。"""
        res = self.client.post(f'/api/trips/{self.hash_url}/expenses/', {
            'name': '削除される費用',
            'amount': '1000',
            'currency': 'JPY',
            'payer': self.member1_id,
            'participant_ids': [self.member1_id],
        }, format='json')
        expense_id = res.json()['id']

        response = self.client.delete(f'/api/expenses/{expense_id}/')
        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)
