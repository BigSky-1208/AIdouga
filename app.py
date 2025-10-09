import os
import io
import base64
from flask import Flask, render_template, jsonify, session, redirect, url_for, request
import logging
from authlib.integrations.flask_client import OAuth
from urllib.parse import urlencode
from werkzeug.middleware.proxy_fix import ProxyFix
import requests

from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseUpload

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
SERVICE_ACCOUNT_FILE = '/etc/secrets/google-credentials.json'
DRIVE_FOLDER_ID = os.getenv("GOOGLE_DRIVE_FOLDER_ID")
SHARED_DRIVE_ID = os.getenv("GOOGLE_SHARED_DRIVE_ID")
YOUTUBE_API_KEY = os.getenv("YOUTUBE_API_KEY")
ROBOFLOW_API_KEY = os.getenv("ROBOFLOW_API_KEY")
ROBOFLOW_MODEL_ID = os.getenv("ROBOFLOW_MODEL_ID")
ROBOFLOW_VERSION_NUMBER = os.getenv("ROBOFLOW_VERSION_NUMBER")

folder_id_cache = {}

# --- Routes ---
# (login, callback, logout, get_video_info routes are unchanged)
@app.route('/')
def index():
    return render_template('index.html', session=session.get('user'))
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

def get_drive_service():
    if not os.path.exists(SERVICE_ACCOUNT_FILE):
        app.logger.error("Google credentials secret file not found!")
        return None
    # ★★★ 変更点: スコープを drive.file から drive に変更 ★★★
    # これにより、アプリが作成していない既存のフォルダやファイルも読み取れるようになります。
    creds = service_account.Credentials.from_service_account_file(
        SERVICE_ACCOUNT_FILE, scopes=['https://www.googleapis.com/auth/drive'])
    return build('drive', 'v3', credentials=creds)

def populate_folder_cache(drive_service, parent_id):
    global folder_id_cache
    if folder_id_cache: return

    app.logger.info(f"Searching for subfolders inside parent_id: {parent_id}")
    app.logger.info(f"Using Shared Drive ID: {SHARED_DRIVE_ID}") 

    app.logger.info("サブフォルダの情報をGoogle Driveから取得中...")
    query = (
        f"'{parent_id}' in parents and "
        f"mimeType = 'application/vnd.google-apps.folder' and "
        f"trashed = false"
    )

    files = []
    page_token = None
    while True:
        list_params = {
            'q': query,
            'supportsAllDrives': True,
            'includeItemsFromAllDrives': True,
            'fields': "nextPageToken, files(id, name)",
            'pageToken': page_token
        }
        if SHARED_DRIVE_ID:
            list_params['corpora'] = 'drive'
            list_params['driveId'] = SHARED_DRIVE_ID

        response = drive_service.files().list(**list_params).execute()
        files.extend(response.get('files', []))
        page_token = response.get('nextPageToken', None)
        if not page_token:
            break
            
    app.logger.info(f"{len(files)}個のサブフォルダが見つかりました。") # デバッグ用にログを追加
    folder_id_cache = {folder['name']: folder['id'] for folder in files}
    app.logger.info(f"フォルダキャッシュを作成しました: {folder_id_cache}")


@app.route('/upload-screenshot', methods=['POST'])
def upload_screenshot():
    if 'user' not in session:
        return jsonify({"error": "認証が必要です。"}), 401
    
    try:
        data = request.json
        image_data_b64 = data['image'].split(',')[1]

        if not all([ROBOFLOW_API_KEY, ROBOFLOW_MODEL_ID, ROBOFLOW_VERSION_NUMBER]):
            raise Exception("RoboflowのAPI設定が不足しています。")

        upload_url = f"https://detect.roboflow.com/{ROBOFLOW_MODEL_ID}/{ROBOFLOW_VERSION_NUMBER}?api_key={ROBOFLOW_API_KEY}"
        headers = {"Content-Type": "application/x-www-form-urlencoded"}
        response = requests.post(upload_url, data=image_data_b64, headers=headers)
        response.raise_for_status()
        
        predictions = response.json().get('predictions', [])
        person_count = len(predictions)
        app.logger.info(f"AIが{person_count}人を検出しました。")
        
        target_folder_name = ""
        if 3 <= person_count <= 5: target_folder_name = "3~5人"
        elif 6 <= person_count <= 10: target_folder_name = "6~10人"
        elif person_count >= 11: target_folder_name = "11人~"
        else: target_folder_name = "その他" 
        app.logger.info(f"保存先のフォルダ名: '{target_folder_name}'")
        
        drive_service = get_drive_service()
        if not drive_service or not DRIVE_FOLDER_ID:
            raise Exception("Google Driveサービスまたは親フォルダIDが設定されていません。")
        
        populate_folder_cache(drive_service, DRIVE_FOLDER_ID)
        target_folder_id = folder_id_cache.get(target_folder_name)

        if not target_folder_id:
             app.logger.warning(f"サブフォルダ '{target_folder_name}' が見つかりません。親フォルダに保存します。")
        
        upload_folder_id = target_folder_id if target_folder_id else DRIVE_FOLDER_ID
        final_folder_name = target_folder_name if target_folder_id else "（親フォルダ）"

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
