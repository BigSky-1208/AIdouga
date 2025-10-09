import os
from flask import Flask, session
from authlib.integrations.flask_client import OAuth
from werkzeug.middleware.proxy_fix import ProxyFix
import logging
from functools import wraps
from google.oauth2 import service_account
from googleapiclient.discovery import build

logging.basicConfig(level=logging.INFO)

# --------------------------------------------------------------------------
# アプリケーションの基本的な設定 (App Initialization & Config)
# --------------------------------------------------------------------------
app = Flask(__name__, template_folder='templates')
app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1, x_prefix=1)

# 環境変数から設定を読み込み
app.secret_key = os.getenv("APP_SECRET_KEY")
app.config.update(
    AUTH0_CLIENT_ID=os.getenv("AUTH0_CLIENT_ID"),
    AUTH0_CLIENT_SECRET=os.getenv("AUTH0_CLIENT_SECRET"),
    AUTH0_DOMAIN=os.getenv("AUTH0_DOMAIN"),
    SERVICE_ACCOUNT_FILE='/etc/secrets/google-credentials.json',
    DRIVE_FOLDER_ID=os.getenv("GOOGLE_DRIVE_FOLDER_ID"),
    SHARED_DRIVE_ID=os.getenv("GOOGLE_SHARED_DRIVE_ID"),
    YOUTUBE_API_KEY=os.getenv("YOUTUBE_API_KEY"),
    ROBOFLOW_API_KEY=os.getenv("ROBOFLOW_API_KEY"),
    ROBOFLOW_MODEL_ID=os.getenv("ROBOFLOW_MODEL_ID"),
    ROBOFLOW_VERSION_NUMBER=os.getenv("ROBOFLOW_VERSION_NUMBER")
)
CLASSIFICATION_FOLDERS = ["3～5人", "6～10人", "11人～"]
folder_id_cache = {}

# Auth0の初期化
oauth = OAuth(app)
auth0 = oauth.register(
    'auth0',
    client_id=app.config.get("AUTH0_CLIENT_ID"),
    client_secret=app.config.get("AUTH0_CLIENT_SECRET"),
    api_base_url=f"https://{app.config.get('AUTH0_DOMAIN')}",
    access_token_url=f"https://{app.config.get('AUTH0_DOMAIN')}/oauth/token",
    authorize_url=f"https://{app.config.get('AUTH0_DOMAIN')}/authorize",
    server_metadata_url=f"https://{app.config.get('AUTH0_DOMAIN')}/.well-known/openid-configuration",
    client_kwargs={'scope': 'openid profile email'},
)

# --------------------------------------------------------------------------
# 全体で共有するヘルパー関数 (Shared Helper Functions)
# --------------------------------------------------------------------------
def get_drive_service():
    """Google Drive APIサービスへの接続を確立して返す"""
    if not os.path.exists(app.config.get("SERVICE_ACCOUNT_FILE")):
        app.logger.error("Google credentials secret file not found!")
        return None
    creds = service_account.Credentials.from_service_account_file(
        app.config.get("SERVICE_ACCOUNT_FILE"), scopes=['https://www.googleapis.com/auth/drive'])
    return build('drive', 'v3', credentials=creds)

def requires_auth(f):
    """ログイン状態をチェックするデコレーター"""
    @wraps(f)
    def decorated(*args, **kwargs):
        if 'user' not in session:
            return jsonify({"error": "認証が必要です。"}), 401
        return f(*args, **kwargs)
    return decorated

# --------------------------------------------------------------------------
# ブループリントの登録 (Blueprint Registration)
# --------------------------------------------------------------------------
# 他のファイルで定義された各機能を「事業部」として本社に登録します。
# ※循環参照を避けるため、ここでインポートします。
from main_routes import main_bp
from huriwake_routes import huriwake_bp

app.register_blueprint(main_bp)
app.register_blueprint(huriwake_bp)

# --------------------------------------------------------------------------
# アプリケーションの実行 (App Execution)
# --------------------------------------------------------------------------
if __name__ == '__main__':
    port = int(os.environ.get('PORT', 8080))
    app.run(host='0.0.0.0', port=port)

