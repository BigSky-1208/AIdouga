import os
import io
import base64
from flask import Flask, render_template, jsonify, session, redirect, url_for, request
import logging
from authlib.integrations.flask_client import OAuth
from urllib.parse import urlencode
from werkzeug.middleware.proxy_fix import ProxyFix
import requests # ★ Roboflow API呼び出しのために追加

# Google Cloud & Driveライブラリ (変更なし)
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
# ... (Auth0のコードは変更なし)

# --- Service Keys Setup ---
# Google
SERVICE_ACCOUNT_FILE = '/etc/secrets/google-credentials.json'
DRIVE_FOLDER_ID = os.getenv("GOOGLE_DRIVE_FOLDER_ID")
YOUTUBE_API_KEY = os.getenv("YOUTUBE_API_KEY")
# ★ Roboflow
ROBOFLOW_API_KEY = os.getenv("ROBOFLOW_API_KEY")
ROBOFLOW_MODEL_ID = os.getenv("ROBOFLOW_MODEL_ID")
ROBOFLOW_VERSION_NUMBER = os.getenv("ROBOFLOW_VERSION_NUMBER")


# --- Routes (Auth0 and other routes are unchanged) ---
@app.route('/')
def index():
    # ... (変更なし)
# ... (login, callback, logout, get-video-info routes are unchanged)


# ★ここからがメインの変更箇所です★

def get_drive_service():
    # ... (変更なし)

def find_folder_id(drive_service, parent_id, folder_name):
    # ... (変更なし)

@app.route('/upload-screenshot', methods=['POST'])
def upload_screenshot():
    if 'user' not in session:
        return jsonify({"error": "認証が必要です。"}), 401
    
    try:
        data = request.json
        image_data_b64 = data['image'].split(',')[1]

        # 1. ★ Roboflow APIで人数を数える ★
        if not all([ROBOFLOW_API_KEY, ROBOFLOW_MODEL_ID, ROBOFLOW_VERSION_NUMBER]):
            raise Exception("RoboflowのAPI設定が不足しています。")

        # Roboflow APIのエンドポイントを構築
        upload_url = "".join([
            f"https://detect.roboflow.com/{ROBOFLOW_MODEL_ID}/{ROBOFLOW_VERSION_NUMBER}",
            f"?api_key={ROBOFLOW_API_KEY}"
        ])

        # APIに画像を送信
        headers = {"Content-Type": "application/x-www-form-urlencoded"}
        response = requests.post(upload_url, data=image_data_b64, headers=headers)
        response.raise_for_status() # エラーがあれば例外を発生させる
        
        # 結果から人数をカウント
        predictions = response.json().get('predictions', [])
        person_count = len(predictions)
        
        # 2. 人数に応じてフォルダ名を決定 (変更なし)
        target_folder_name = ""
        if 3 <= person_count <= 5:
            target_folder_name = "3~5人"
        elif 6 <= person_count <= 10:
            target_folder_name = "6~10人"
        elif person_count >= 11:
            target_folder_name = "11人~"
        else:
            target_folder_name = "その他" 

        # 3. Google Driveサービスを準備し、保存先フォルダIDを決定 (変更なし)
        drive_service = get_drive_service()
        # ... (フォルダID決定ロジックは変更なし)
        
        # 4. ファイルをアップロード (変更なし)
        file_name = data['fileName']
        # ... (アップロードロジックは変更なし)
        
        return jsonify({ 
            "success": True, 
            # ... (変更なし)
            "message": f"「{final_folder_name}」に保存しました ({person_count}人検出)"
        })

    except Exception as e:
        app.logger.error(f"Upload and classify error: {e}")
        return jsonify({"error": f"サーバーエラー: {str(e)}"}), 500

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 8080))
    app.run(host='0.0.0.0', port=port)

