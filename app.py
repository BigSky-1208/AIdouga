import os
import io
import base64
from flask import Flask, render_template, jsonify, session, redirect, url_for, request
import logging
from authlib.integrations.flask_client import OAuth
from urllib.parse import urlencode
from werkzeug.middleware.proxy_fix import ProxyFix
import requests # Roboflow API呼び出しのために追加

# Google Cloud & Driveライブラリ
from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseUpload

# Basic logging setup
logging.basicConfig(level=logging.INFO)

app = Flask(__name__, template_folder='templates')
app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1, x_prefix=1)
app.secret_key = os.getenv("APP_SECRET_KEY")

# --- Auth0 Setup ---
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

# --- Service Keys Setup ---
# Google
SERVICE_ACCOUNT_FILE = '/etc/secrets/google-credentials.json'
DRIVE_FOLDER_ID = os.getenv("GOOGLE_DRIVE_FOLDER_ID")
YOUTUBE_API_KEY = os.getenv("YOUTUBE_API_KEY")
# Roboflow
ROBOFLOW_API_KEY = os.getenv("ROBOFLOW_API_KEY")
ROBOFLOW_MODEL_ID = os.getenv("ROBOFLOW_MODEL_ID")
ROBOFLOW_VERSION_NUMBER = os.getenv("ROBOFLOW_VERSION_NUMBER")


# --- Routes ---
@app.route('/')
def index():
    return render_template('index.html', session=session.get('user'))

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

        # 1. Roboflow APIで人数を数える
        if not all([ROBOFLOW_API_KEY, ROBOFLOW_MODEL_ID, ROBOFLOW_VERSION_NUMBER]):
            raise Exception("RoboflowのAPI設定が不足しています。")

        upload_url = "".join([
            f"https://detect.roboflow.com/{ROBOFLOW_MODEL_ID}/{ROBOFLOW_VERSION_NUMBER}",
            f"?api_key={ROBOFLOW_API_KEY}"
        ])

        headers = {"Content-Type": "application/x-www-form-urlencoded"}
        response = requests.post(upload_url, data=image_data_b64, headers=headers)
        response.raise_for_status()
        
        predictions = response.json().get('predictions', [])
        person_count = len(predictions)
        
        # ★追加: デバッグのためのログ出力
        app.logger.info(f"AIが{person_count}人を検出しました。")
        
        # 2. 人数に応じてフォルダ名を決定
        target_folder_name = ""
        if 3 <= person_count <= 5:
            target_folder_name = "3~5人"
        elif 6 <= person_count <= 10:
            target_folder_name = "6~10人"
        elif person_count >= 11:
            target_folder_name = "11人~"
        else:
            target_folder_name = "その他" 
        
        app.logger.info(f"保存先のフォルダ名: '{target_folder_name}'")

        # 3. Google Driveサービスを準備し、保存先フォルダIDを決定
        drive_service = get_drive_service()
        if not drive_service or not DRIVE_FOLDER_ID:
            raise Exception("Google Driveサービスまたは親フォルダIDが設定されていません。")

        target_folder_id = find_folder_id(drive_service, DRIVE_FOLDER_ID, target_folder_name)
        
        if target_folder_id:
            app.logger.info(f"フォルダIDが見つかりました: {target_folder_id}")
        else:
            app.logger.warning(f"サブフォルダ '{target_folder_name}' が見つかりません。親フォルダに保存します。")

        upload_folder_id = target_folder_id if target_folder_id else DRIVE_FOLDER_ID
        final_folder_name = target_folder_name if target_folder_id else "（親フォルダ）"

        # 4. ファイルをアップロード
        file_name = data['fileName']
        image_bytes = base64.b64decode(image_data_b64)
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

