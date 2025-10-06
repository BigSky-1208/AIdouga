import os
from flask import Flask, render_template, jsonify
import googleapiclient.discovery
import logging

# Set up basic logging
logging.basicConfig(level=logging.INFO)

app = Flask(__name__, template_folder='templates')

# Get API key from Render's environment variables
API_KEY = os.getenv("YOUTUBE_API_KEY")

@app.route('/')
def index():
    """Serves the main HTML page."""
    return render_template('index.html')

@app.route('/get-video-info/<video_id>')
def get_video_info(video_id):
    """Fetches video title and checks if it's embeddable using its ID."""
    if not API_KEY:
        app.logger.error("YOUTUBE_API_KEY is not set.")
        return jsonify({"error": "サーバー側でAPIキーが設定されていません。"}), 500

    try:
        youtube = googleapiclient.discovery.build("youtube", "v3", developerKey=API_KEY)

        request = youtube.videos().list(
            part="snippet,status",
            id=video_id
        )
        response = request.execute()
        
        items = response.get("items", [])
        if not items:
            return jsonify({"error": "動画が見つかりませんでした。"}), 404
            
        video_item = items[0]
        
        # Check if the video is embeddable
        if not video_item.get('status', {}).get('embeddable'):
            return jsonify({"error": "この動画は埋め込みが許可されていません。"}), 403

        title = video_item['snippet']['title']
        
        return jsonify({"id": video_id, "title": title})

    except Exception as e:
        app.logger.error(f"YouTube API access error: {e}")
        error_details = str(e)
        return jsonify({"error": f"サーバーエラー: {error_details}"}), 500

if __name__ == '__main__':
    # Render sets the PORT environment variable
    port = int(os.environ.get('PORT', 8080))
    app.run(host='0.0.0.0', port=port)

