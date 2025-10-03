import os
from flask import Flask, render_template, jsonify
import googleapiclient.discovery

# --- Flaskアプリケーションのセットアップ  ---
app = Flask(__name__, template_folder='templates')

# --- APIと設定 ---
# APIキーはRenderの環境変数から読み込む
API_KEY = os.getenv("YOUTUBE_API_KEY")
REGION_CODE = "JP"
MAX_RESULTS = 20 # 取得するランダム動画の候補数

@app.route('/')
def index():
    """ユーザーインターフェースとなるHTMLページを表示する。"""
    return render_template('index.html')

@app.route('/get-videos')
def get_videos():
    """YouTube Data APIを使って人気の動画IDリストを取得するAPIエンドポイント"""
    if not API_KEY:
        return jsonify({"error": "YOUTUBE_API_KEYが設定されていません。"}), 500
    
    try:
        # YouTube Data APIのクライアントをセットアップ
        youtube = googleapiclient.discovery.build("youtube", "v3", developerKey=API_KEY)

        request = youtube.videos().list(
            part="id", # IDだけ取得すれば良い
            chart="mostPopular",
            regionCode=REGION_CODE,
            maxResults=MAX_RESULTS
        )
        response = request.execute()
        
        video_ids = [item['id'] for item in response.get("items", [])]
        return jsonify(video_ids)

    except Exception as e:
        return jsonify({"error": f"APIエラー: {str(e)}"}), 500


if __name__ == '__main__':
    # Render.comではGunicornが使われるため、この部分はローカルテスト用
    app.run(host='0.0.0.0', port=8080)

