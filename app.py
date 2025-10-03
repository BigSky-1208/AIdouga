import os
from flask import Flask, render_template, jsonify
import googleapiclient.discovery
import logging

logging.basicConfig(level=logging.INFO)

app = Flask(__name__, template_folder='templates')

API_KEY = os.getenv("YOUTUBE_API_KEY")
REGION_CODE = "JP"
MAX_RESULTS = 50 # 少し多めに取得してフィルタリングする

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/get-videos')
def get_videos():
    if not API_KEY:
        app.logger.error("YOUTUBE_API_KEY is not set.")
        return jsonify({"error": "サーバー側でAPIキーが設定されていません。"}), 500
    
    try:
        youtube = googleapiclient.discovery.build("youtube", "v3", developerKey=API_KEY)

        # ★変更点1: partに'status'を追加して、動画の状態(埋め込み可否など)も取得する
        request = youtube.videos().list(
            part="id,status",
            chart="mostPopular",
            regionCode=REGION_CODE,
            maxResults=MAX_RESULTS
            # ★変更点2: エラーの原因となっていた video_embeddable パラメータを削除
        )
        response = request.execute()
        
        # ★変更点3: 取得した動画の中から、埋め込みが許可されている(embeddable: True)ものだけを抽出する
        video_ids = [
            item['id']
            for item in response.get("items", [])
            if item.get('status', {}).get('embeddable')
        ]
        
        return jsonify(video_ids)

    except Exception as e:
        app.logger.error(f"YouTube APIへのアクセス中にエラーが発生しました: {e}")
        return jsonify({"error": f"サーバーエラー: {str(e)}"}), 500


if __name__ == '__main__':
    app.run(host='0.0.0.0', port=8080)

