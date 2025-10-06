import os
from flask import Flask, render_template

# YouTube APIへの依存がなくなり、非常にシンプルなサーバーになります
app = Flask(__name__, template_folder='templates')

@app.route('/')
def index():
    """ユーザーに操作画面(index.html)を返します。"""
    return render_template('index.html')

if __name__ == '__main__':
    # RenderがPORT環境変数を設定します
    port = int(os.environ.get('PORT', 8080))
    app.run(host='0.0.0.0', port=port)

