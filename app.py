import os
import threading
import time
from flask import Flask, render_template, jsonify
import googleapiclient.discovery
import yt_dlp
import cv2

# --- Flaskアプリケーションのセットアップ ---
app = Flask(__name__, static_folder='static', template_folder='templates')

# --- グローバル変数 (状態管理用) ---
process_thread = None
is_running = False
current_status = "待機中 (Idle)"
results = []

# --- APIと設定 ---
API_KEY = os.getenv("YOUTUBE_API_KEY")
REGION_CODE = "JP"
MAX_RESULTS = 5
CAPTURE_INTERVAL_SEC = 5

# --- メインの処理関数 (バックグラウンドで実行) ---
def process_videos_task():
    global is_running, current_status, results, process_thread

    is_running = True
    results = []
    
    try:
        if not API_KEY:
            current_status = "エラー: YOUTUBE_API_KEYが設定されていません。"
            is_running = False
            return

        youtube = googleapiclient.discovery.build("youtube", "v3", developerKey=API_KEY)

        current_status = "人気の動画URLを取得中..."
        request = youtube.videos().list(
            part="snippet", chart="mostPopular", regionCode=REGION_CODE, maxResults=MAX_RESULTS
        )
        response = request.execute()
        
        video_items = response.get("items", [])
        if not video_items:
            current_status = "人気の動画が見つかりませんでした。"
            is_running = False
            return

        video_urls = [f"https://www.youtube.com/watch?v={item['id']}" for item in video_items]
        
        for i, url in enumerate(video_urls):
            if not is_running:
                current_status = "ユーザーによって停止されました。"
                break
            
            video_title = video_items[i]["snippet"]["title"]
            current_status = f"動画 {i+1}/{len(video_urls)} を処理中: {video_title[:30]}..."

            # 2a. 動画のストリームURLを取得
            current_status = f"動画 {i+1} のストリーム情報を取得中..."
            ydl_opts = {
                'format': 'best[ext=mp4]/best',
                'quiet': True,
                # --- ▼▼▼ 追加点 ▼▼▼ ---
                # リクエストを通常のブラウザに見せかけるための設定
                'user_agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36',
            }
            stream_url = None
            try:
                with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                    info = ydl.extract_info(url, download=False)
                    stream_url = info.get('url')
            except Exception as e:
                print(f"yt-dlpでエラーが発生: {e}")
                # --- ▼▼▼ 変更点 ▼▼▼ ---
                # エラーの種類に応じて、ユーザーへの表示メッセージを分かりやすくする
                if 'Sign in to confirm' in str(e):
                    results.append(f"「{video_title[:20]}...」は保護されており処理できませんでした。")
                else:
                    results.append(f"「{video_title[:20]}...」の処理中にエラーが発生し、スキップします。")
                continue # 次の動画へ

            if not stream_url:
                results.append(f"「{video_title[:20]}...」のストリームURLが取得できませんでした。")
                continue

            # 2b. ストリームから直接静止画を撮影
            current_status = f"動画 {i+1} のストリームを解析中..."
            cap = cv2.VideoCapture(stream_url)
            if not cap.isOpened():
                results.append(f"「{video_title[:20]}...」のストリームを開けませんでした。")
                continue
            
            fps = cap.get(cv2.CAP_PROP_FPS)
            interval_frames = int(fps * CAPTURE_INTERVAL_SEC) if fps > 0 else 150
            frame_count = 0
            
            while cap.isOpened():
                if not is_running: break
                ret, frame = cap.read()
                if not ret: break
                
                if frame_count % interval_frames == 0:
                    results.append(f"「{video_title[:20]}...」の {int(frame_count/(fps if fps > 0 else 30))}秒 地点でシーンを発見！")
                    time.sleep(0.2) 

                frame_count += 1
            cap.release()

    except Exception as e:
        current_status = f"エラーが発生しました: {str(e)}"
    finally:
        is_running = False
        if "停止" not in current_status and "エラー" not in current_status:
            current_status = "処理が完了しました。"
        process_thread = None


# --- Flaskのルート定義 (APIエンドポイント) ---
@app.route('/')
def index():
    return render_template('index.html')

@app.route('/start', methods=['POST'])
def start_process():
    global process_thread
    if process_thread and process_thread.is_alive():
        return jsonify({"status": "既に処理が実行中です。"}), 400
    
    process_thread = threading.Thread(target=process_videos_task)
    process_thread.start()
    return jsonify({"status": "処理を開始しました。"})

@app.route('/stop', methods=['POST'])
def stop_process():
    global is_running
    if not is_running:
        return jsonify({"status": "処理は実行されていません。"}), 400
    
    is_running = False
    return jsonify({"status": "停止リクエストを受け付けました。"})

@app.route('/status', methods=['GET'])
def get_status():
    return jsonify({
        "is_running": is_running,
        "status": current_status,
        "results": results
    })

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=int(os.environ.get('PORT', 8080)))

