from flask import Flask
from blueprints.auth import auth_bp
from blueprints.main import main_bp

app = Flask(__name__)
app.secret_key = 'super_secret_key'  # Измените на реальный секретный ключ

# Регистрация blueprints
app.register_blueprint(auth_bp, url_prefix='/auth')
app.register_blueprint(main_bp)

if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=9000)