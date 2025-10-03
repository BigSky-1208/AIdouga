import os
import googleapiclient.discovery
import yt_dlp
import cv2

# --- 設定項目 ---
# APIキーはRenderの環境変数から読み込む（重要）
API_KEY = os.getenv("YOUTUBE_API_KEY", "デフォルトキー（もしあれば）") 
# --- その他の設定は前回と同じ ---
REGION_CODE = "JP"
MAX_RESULTS = 3
OUTPUT_DIR = "output"
CAPTURE_INTERVAL_SEC = 5
# --- 設定項目ここまで ---

# (前回と全く同じなので、関数の内容は省略)

def get_popular_video_urls():
    # ... (前回のコードをそのままコピー) ...

def download_video(url, output_path):
    # ... (前回のコードをそのままコピー) ...

def capture_frames(video_path, output_folder):
    # ... (前回のコードをそのままコピー) ...


if __name__ == "__main__":
    if not API_KEY or API_KEY == "デフォルトキー（もしあれば）":
        print("エラー: 環境変数 YOUTUBE_API_KEY が設定されていません。")
    else:
        # YouTube Data APIのクライアントをセットアップ
        youtube = googleapiclient.discovery.build(
            "youtube", "v3", developerKey=API_KEY)
        
        # ... (以降の処理は前回のコードをそのままコピー) ...
        # get_popular_video_urls() の定義はグローバルスコープに移動させるか、
        # youtubeオブジェクトを引数で渡すように変更する必要があります。
        # 以下は、youtubeオブジェクトをグローバル変数として使う簡単な例です。
        
        # 出力用フォルダがなければ作成
        os.makedirs(OUTPUT_DIR, exist_ok=True)

        # ステップ1を実行
        video_urls = get_popular_video_urls() # この関数内でグローバルなyoutube変数を使う

        # ステップ2を各動画に対して実行
        for i, url in enumerate(video_urls):
            video_filename = f"video_{i+1}.mp4"
            video_path = os.path.join(OUTPUT_DIR, video_filename)
            
            if download_video(url, video_path):
                frames_folder = os.path.join(OUTPUT_DIR, f"video_{i+1}_frames")
                capture_frames(video_path, frames_folder)

        print("\nすべての処理が完了しました。")
