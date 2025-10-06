import os
from flask import Flask, render_template, jsonify, session, redirect, url_for
import googleapiclient.discovery
import logging
from authlib.integrations.flask_client import OAuth
from urllib.parse import urlencode

# Set up basic logging
logging.basicConfig(level=logging.INFO)

app = Flask(__name__, template_folder='templates')

# ★追加: Flaskのセッションを安全に保つための秘密鍵
# Renderの環境変数から読み込みます
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
    client_kwargs={
        'scope': 'openid profile email',
    },
)

# --- YouTube API Setup ---
API_KEY = os.getenv("YOUTUBE_API_KEY")

# --- Routes ---
@app.route('/')
def index():
    """
    ユーザーがログインしていればメインページを、
    していなければログインページを表示します。
    """
    return render_template('index.html', session=session.get('user'))

@app.route('/login')
def login():
    """Auth0のログインページにリダイレクトします。"""
    return auth0.authorize_redirect(redirect_uri=url_for("callback", _external=True))

@app.route("/callback")
def callback():
    """Auth0からのコールバックを処理し、セッションにユーザー情報を保存します。"""
    token = auth0.authorize_access_token()
    session["user"] = token["userinfo"]
    return redirect("/")

@app.route("/logout")
def logout():
    """セッションをクリアし、Auth0からログアウトさせます。"""
    session.clear()
    params = {
        "returnTo": url_for("index", _external=True),
        "client_id": os.getenv("AUTH0_CLIENT_ID"),
    }
    return redirect(auth0.api_base_url + "/v2/logout?" + urlencode(params))


@app.route('/get-video-info/<video_id>')
def get_video_info(video_id):
    """
    動画情報を取得するAPI。
    ★変更点: ログインしていない場合はアクセスを拒否します。
    """
    if 'user' not in session:
        return jsonify({"error": "認証が必要です。"}), 401
        
    if not API_KEY:
        app.logger.error("YOUTUBE_API_KEY is not set.")
        return jsonify({"error": "サーバー側でAPIキーが設定されていません。"}), 500

    try:
        youtube = googleapiclient.discovery.build("youtube", "v3", developerKey=API_KEY)
        request = youtube.videos().list(part="snippet,status", id=video_id)
        response = request.execute()
        
        items = response.get("items", [])
        if not items:
            return jsonify({"error": "動画が見つかりませんでした。"}), 404
            
        video_item = items[0]
        if not video_item.get('status', {}).get('embeddable'):
            return jsonify({"error": "この動画は埋め込みが許可されていません。"}), 403

        title = video_item['snippet']['title']
        return jsonify({"id": video_id, "title": title})

    except Exception as e:
        app.logger.error(f"YouTube API access error: {e}")
        return jsonify({"error": f"サーバーエラー: {str(e)}"}), 500

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 8080))
    app.run(host='0.0.0.0', port=port)

