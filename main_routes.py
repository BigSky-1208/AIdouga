from flask import Blueprint, render_template, jsonify, session, redirect, url_for, request, current_app
import base64
import requests
import io

from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseUpload

# app.pyから共有オブジェクトと関数をインポート
from app import auth0, get_drive_service, requires_auth, folder_id_cache

# 'main'という名前でブループリントを作成
main_bp = Blueprint('main', __name__)

def populate_folder_cache(drive_service, parent_id):
    """フォルダIDをキャッシュする関数（main_routes専用）"""
    if parent_id in folder_id_cache: return folder_id_cache[parent_id]

    query = f"'{parent_id}' in parents and mimeType = 'application/vnd.google-apps.folder' and trashed = false"
    list_params = {
        'q': query, 'supportsAllDrives': True, 'includeItemsFromAllDrives': True,
        'fields': "files(id, name)"
    }
    if current_app.config.get("SHARED_DRIVE_ID"):
        list_params.update({'corpora': 'drive', 'driveId': current_app.config.get("SHARED_DRIVE_ID")})
    
    response = drive_service.files().list(**list_params).execute()
    subfolders = {folder['name']: folder['id'] for folder in response.get('files', [])}
    folder_id_cache[parent_id] = subfolders
    return subfolders

@main_bp.route('/')
def index():
    return render_template('index.html', session=session.get('user'))

@main_bp.route('/login')
def login(): 
    return auth0.authorize_redirect(redirect_uri=url_for("main.callback", _external=True))

@main_bp.route("/callback")
def callback():
    token = auth0.authorize_access_token()
    session["user"] = token["userinfo"]
    return redirect(url_for("main.index"))

@main_bp.route("/logout")
def logout():
    from urllib.parse import urlencode
    session.clear()
    params = {"returnTo": url_for("main.index", _external=True), "client_id": current_app.config.get("AUTH0_CLIENT_ID"),}
    return redirect(auth0.api_base_url + "/v2/logout?" + urlencode(params))

@main_bp.route('/get-video-info/<video_id>')
@requires_auth
def get_video_info(video_id):
    if not current_app.config.get("YOUTUBE_API_KEY"): return jsonify({"error": "サーバー側でAPIキーが設定されていません。"}), 500
    try:
        youtube = build("youtube", "v3", developerKey=current_app.config.get("YOUTUBE_API_KEY"))
        request_yt = youtube.videos().list(part="snippet,status", id=video_id)
        response = request_yt.execute()
        items = response.get("items", [])
        if not items: return jsonify({"error": "動画が見つかりませんでした。"}), 404
        video_item = items[0]
        if not video_item.get('status', {}).get('embeddable'): return jsonify({"error": "この動画は埋め込みが許可されていません。"}), 403
        title = video_item['snippet']['title']
        return jsonify({"id": video_id, "title": title})
    except Exception as e:
        current_app.logger.error(f"YouTube API access error: {e}")
        return jsonify({"error": f"サーバーエラー: {str(e)}"}), 500

@main_bp.route('/upload-screenshot', methods=['POST'])
@requires_auth
def upload_screenshot():
    try:
        data = request.json
        image_data_b64 = data['image'].split(',')[1]

        if not all([current_app.config.get("ROBOFLOW_API_KEY"), current_app.config.get("ROBOFLOW_MODEL_ID"), current_app.config.get("ROBOFLOW_VERSION_NUMBER")]):
            raise Exception("RoboflowのAPI設定が不足しています。")

        upload_url = f"https://detect.roboflow.com/{current_app.config.get('ROBOFLOW_MODEL_ID')}/{current_app.config.get('ROBOFLOW_VERSION_NUMBER')}?api_key={current_app.config.get('ROBOFLOW_API_KEY')}"
        headers = {"Content-Type": "application/x-www-form-urlencoded"}
        response = requests.post(upload_url, data=image_data_b64, headers=headers)
        response.raise_for_status()
        
        predictions = response.json().get('predictions', [])
        person_count = len(predictions)
        
        target_folder_name = "その他"
        if 3 <= person_count <= 5: target_folder_name = "3～5人"
        elif 6 <= person_count <= 10: target_folder_name = "6～10人"
        elif person_count >= 11: target_folder_name = "11人～"
        
        drive_service = get_drive_service()
        drive_folder_id = current_app.config.get("DRIVE_FOLDER_ID")
        if not drive_service or not drive_folder_id:
            raise Exception("Google Driveサービスまたは親フォルダIDが設定されていません。")
        
        subfolders = populate_folder_cache(drive_service, drive_folder_id)
        target_folder_id = subfolders.get(target_folder_name)
        
        upload_folder_id = target_folder_id if target_folder_id else drive_folder_id
        final_folder_name = target_folder_name if target_folder_id else "（親フォルダ）"

        file_name = data['fileName']
        image_bytes = base64.b64decode(image_data_b64)
        media_bytes = io.BytesIO(image_bytes)
        media = MediaIoBaseUpload(media_bytes, mimetype='image/jpeg', resumable=True)
        file_metadata = {'name': file_name, 'parents': [upload_folder_id]}
        
        file = drive_service.files().create(
            body=file_metadata, media_body=media, fields='id', supportsAllDrives=True
        ).execute()
        
        return jsonify({ "success": True, "fileId": file.get('id'), "message": f"「{final_folder_name}」に保存しました ({person_count}人検出)"})
    except Exception as e:
        current_app.logger.error(f"Upload error: {e}")
        return jsonify({"error": f"サーバーエラー: {str(e)}"}), 500
