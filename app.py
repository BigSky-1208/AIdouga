import os
import io
import base64
from flask import Flask, render_template, jsonify, session, redirect, url_for, request
import logging
from authlib.integrations.flask_client import OAuth
from urllib.parse import urlencode
from werkzeug.middleware.proxy_fix import ProxyFix

# Google Cloud & Driveライブラリ
from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseUpload
# ★追加: Google Cloud Vision AIのライブラリ
from google.cloud import vision

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

# --- Google Cloud Service Setup ---
SERVICE_ACCOUNT_FILE = '/etc/secrets/google-credentials.json'
DRIVE_FOLDER_ID = os.getenv("GOOGLE_DRIVE_FOLDER_ID")
YOUTUBE_API_KEY = os.getenv("YOUTUBE_API_KEY")

# --- Routes (Auth0 and other routes are unchanged) ---
@app.route('/')
def index():
    return render_template('index.html', session=session.get('user'))

# ... (login, callback, logout, get-video-info routes are unchanged)
@app.route('/login')
def login(): return auth0.authorize_redirect(redirect_uri=url_for("callback", _external=True))
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
@app.route('/get-video-info/<video_id>')
def get_video_info(video_id):
    if 'user' not in session: return jsonify({"error": "認証が必要です。"}), 401
    if not YOUTUBE_API_KEY: return jsonify({"error": "サーバー側でAPIキーが設定されていません。"}), 500
    try:
        youtube = build("youtube", "v3", developerKey=YOUTUBE_API_KEY)
        request_yt = youtube.videos().list(part="snippet,status", id=video_id)
        response = request_yt.execute()
        items = response.get("items", [])
        if not items: return jsonify({"error": "動画が見つかりませんでした。"}), 404
        video_item = items[0]
        if not video_item.get('status', {}).get('embeddable'): return jsonify({"error": "この動画は埋め込みが許可されていません。"}), 403
        title = video_item['snippet']['title']
        return jsonify({"id": video_id, "title": title})
    except Exception as e:
        app.logger.error(f"YouTube API access error: {e}")
        return jsonify({"error": f"サーバーエラー: {str(e)}"}), 500
# --- End of unchanged routes ---

# ★ここからがメインの変更箇所です★

def get_drive_service():
    """Google Driveサービスを生成する関数"""
    if not os.path.exists(SERVICE_ACCOUNT_FILE):
        app.logger.error("Google credentials secret file not found!")
        return None
    creds = service_account.Credentials.from_service_account_file(
        SERVICE_ACCOUNT_FILE, scopes=['https://www.googleapis.com/auth/drive.file'])
    return build('drive', 'v3', credentials=creds)

def find_folder_id(drive_service, parent_id, folder_name):
    """指定された親フォルダ内で、名前が一致するサブフォルダのIDを探す"""
    query = f"'{parent_id}' in parents and name = '{folder_name}' and mimeType = 'application/vnd.google-apps.folder' and trashed = false"
    response = drive_service.files().list(q=query, supportsAllDrives=True, includeItemsFromAllDrives=True, fields="files(id)").execute()
    files = response.get('files', [])
    return files[0]['id'] if files else None

@app.route('/upload-screenshot', methods=['POST'])
def upload_screenshot():
    if 'user' not in session:
        return jsonify({"error": "認証が必要です。"}), 401
    
    try:
        data = request.json
        image_data_b64 = data['image'].split(',')[1]
        image_bytes = base64.b64decode(image_data_b64)

        # 1. AIで人数を数える
        vision_client = vision.ImageAnnotatorClient.from_service_account_json(SERVICE_ACCOUNT_FILE)
        image = vision.Image(content=image_bytes)
        response = vision_client.object_localization(image=image)
        person_count = sum(1 for obj in response.localized_object_annotations if obj.name == 'Person')
        
        # 2. 人数に応じてフォルダ名を決定
        target_folder_name = ""
        if 3 <= person_count <= 5:
            target_folder_name = "3~5人"
        elif 6 <= person_count <= 10:
            target_folder_name = "6~10人"
        elif person_count >= 11:
            target_folder_name = "11人~"
        else:
            # どのカテゴリにも当てはまらない場合 (例: 0~2人)
            # ユーザーに「その他」などのフォルダを作成してもらう想定
            target_folder_name = "その他" 

        # 3. Google Driveサービスを準備し、保存先フォルダIDを決定
        drive_service = get_drive_service()
        if not drive_service or not DRIVE_FOLDER_ID:
            raise Exception("Google Driveサービスまたは親フォルダIDが設定されていません。")

        target_folder_id = find_folder_id(drive_service, DRIVE_FOLDER_ID, target_folder_name)
        
        # もしサブフォルダが見つからなければ、親フォルダに保存
        upload_folder_id = target_folder_id if target_folder_id else DRIVE_FOLDER_ID
        final_folder_name = target_folder_name if target_folder_id else "（親フォルダ）"

        # 4. ファイルをアップロード
        file_name = data['fileName']
        media_bytes = io.BytesIO(image_bytes)
        media = MediaIoBaseUpload(media_bytes, mimetype='image/jpeg', resumable=True)
        file_metadata = {'name': file_name, 'parents': [upload_folder_id]}
        
        file = drive_service.files().create(
            body=file_metadata, media_body=media, fields='id', supportsAllDrives=True
        ).execute()
        
        return jsonify({ 
            "success": True, 
            "fileId": file.get('id'),
            "message": f"「{final_folder_name}」に保存しました ({person_count}人検出)"
        })

    except Exception as e:
        app.logger.error(f"Upload and classify error: {e}")
        return jsonify({"error": f"サーバーエラー: {str(e)}"}), 500

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 8080))
    app.run(host='0.0.0.0', port=port)

