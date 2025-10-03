from flask import Flask, render_template

app = Flask(__name__, template_folder='templates')

@app.route('/')
def index():
    """
    ユーザーインターフェースとなるHTMLページを表示する。
    """
    return render_template('index.html')

if __name__ == '__main__':
    # Render.comではGunicornが使われるため、この部分はローカルテスト用
    app.run(host='0.0.0.0', port=8080)

