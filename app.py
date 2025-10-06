import os
import io
import base64
from flask import Flask, render_template, jsonify, session, redirect, url_for
import googleapiclient.discovery
import logging
from authlib.integrations.flask_client import OAuth
from urllib.parse import urlencode
from werkzeug.middleware.proxy_fix import ProxyFix

# ★変更点: Google Service Accountライブラリをインポート
from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseUpload

# Basic logging setup
logging.basicConfig(level=logging.INFO)

app = Flask(__name__, template_folder='templates')
app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1, x_prefix=1)
app.secret_key = os.getenv("APP_SECRET_KEY")

# --- Auth0 Setup (変更なし) ---
oauth = OAuth(app)
auth0 = oauth.register(
    'auth0',
    client_id=os.getenv("AUTH0_CLIENT_ID"),
    client_secret=os.getenv("AUTH0_CLIENT_SECRET"),
    api_base_url=f"https://{os.getenv('AUTH0_DOMAIN')}",
    access_token_url=f"https://{os.getenv('AUTH0_DOMAIN')}/oauth/token",
    authorize_url=f"https://{os.getenv('AUTH0_DOMAIN')}/authorize",
    server_metadata_url=f"https://{os.getenv('AUTH0_DOMAIN')}/.well-known/openid-configuration",
    client_kwargs={'scope': 'openid profile email'},
)

# --- Google Drive Setup (★サービスアカウント方式に変更) ---
SERVICE_ACCOUNT_FILE = '/etc/secrets/google-credentials.json'
SCOPES = ['https://www.googleapis.com/auth/drive.file']
DRIVE_FOLDER_ID = os.getenv("GOOGLE_DRIVE_FOLDER_ID")

def get_drive_service():
    """サービスアカウントの認証情報を使ってDrive APIサービスを生成する"""
    if not os.path.exists(SERVICE_ACCOUNT_FILE):
        app.logger.error("Google credentials secret file not found!")
        return None
    creds = service_account.Credentials.from_service_account_file(
        SERVICE_ACCOUNT_FILE, scopes=SCOPES)
    return build('drive', 'v3', credentials=creds)

# --- YouTube API Setup (変更なし) ---
API_KEY = os.getenv("YOUTUBE_API_KEY")

# --- Routes ---
@app.route('/')
def index():
    # ★変更点: google_authedを削除
    return render_template('index.html', session=session.get('user'))

# (login, callback, logout ルートは変更なし)
@app.route('/login')
def login():
    return auth0.authorize_redirect(redirect_uri=url_for("callback", _external=True))

@app.route("/callback")
def callback():
    token = auth0.authorize_access_token()
    session["user"] = token["userinfo"]
    return redirect("/")

@app.route("/logout")
def logout():
    session.clear()
    params = {"returnTo": url_for("index", _external=True), "client_id": os.getenv("AUTH0_CLIENT_ID"),}
    return redirect(auth0.api_base_url + "/v2/logout?" + urlencode(params))

# --- Application API Routes ---
@app.route('/upload-screenshot', methods=['POST'])
def upload_screenshot():
    # ★変更点: Auth0のログインのみチェック
    if 'user' not in session:
        return jsonify({"error": "認証が必要です。"}), 401
    
    if not DRIVE_FOLDER_ID:
        return jsonify({"error": "Drive Folder IDがサーバーに設定されていません。"}), 500

    try:
        drive_service = get_drive_service()
        if not drive_service:
            raise Exception("Google Driveサービスを作成できませんでした。")

        data = request.json
        image_data = data['image'].split(',')[1]
        file_name = data['fileName']
        
        image_bytes = io.BytesIO(base64.b64decode(image_data))
        media = MediaIoBaseUpload(image_bytes, mimetype='image/jpeg', resumable=True)
        file_metadata = {'name': file_name, 'parents': [DRIVE_FOLDER_ID]}
        
        file = drive_service.files().create(body=file_metadata, media_body=media, fields='id').execute()
        
        return jsonify({"success": True, "fileId": file.get('id')})

    except Exception as e:
        app.logger.error(f"Google Drive upload error: {e}")
        return jsonify({"error": f"サーバーエラー: {str(e)}"}), 500

# (get_video_info ルートは変更なし)
@app.route('/get-video-info/<video_id>')
def get_video_info(video_id):
    if 'user' not in session: return jsonify({"error": "認証が必要です。"}), 401
    if not API_KEY: return jsonify({"error": "サーバー側でAPIキーが設定されていません。"}), 500
    try:
        youtube = googleapiclient.discovery.build("youtube", "v3", developerKey=API_KEY)
        request = youtube.videos().list(part="snippet,status", id=video_id)
        response = request.execute()
        items = response.get("items", [])
        if not items: return jsonify({"error": "動画が見つかりませんでした。"}), 404
        video_item = items[0]
        if not video_item.get('status', {}).get('embeddable'): return jsonify({"error": "この動画は埋め込みが許可されていません。"}), 403
        title = video_item['snippet']['title']
        return jsonify({"id": video_id, "title": title})
    except Exception as e:
        app.logger.error(f"YouTube API access error: {e}")
        return jsonify({"error": f"サーバーエラー: {str(e)}"}), 500

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 8080))
    app.run(host='0.0.0.0', port=port)

