import os
from dotenv import load_dotenv
from flask import Flask, render_template
from flask_login import LoginManager
from flask_socketio import SocketIO
from authlib.integrations.flask_client import OAuth
from models import db, User

load_dotenv()

login_manager = LoginManager()
socketio = SocketIO()


def create_app():
    app = Flask(__name__)
    app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'change-this-to-a-real-secret-key')
    app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///teensatwork.db'
    app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

    db.init_app(app)
    login_manager.init_app(app)
    login_manager.login_view = 'auth.login'
    login_manager.login_message_category = 'warning'
    socketio.init_app(app)

    # Google OAuth — create and register directly on the app
    oauth = OAuth(app)
    oauth.register(
        name='google',
        client_id=os.environ.get('GOOGLE_CLIENT_ID', ''),
        client_secret=os.environ.get('GOOGLE_CLIENT_SECRET', ''),
        server_metadata_url='https://accounts.google.com/.well-known/openid-configuration',
        client_kwargs={'scope': 'openid email profile'},
    )
    app.oauth = oauth  # store on app so routes can access it

    @login_manager.user_loader
    def load_user(user_id):
        return User.query.get(int(user_id))

    from routes.auth import auth_bp
    from routes.homeowner import homeowner_bp
    from routes.teen import teen_bp
    from routes.admin import admin_bp
    from routes.chat import chat_bp, register_socketio_events
    from routes.payment import payment_bp
    from routes.session import session_bp
    from routes.insurance import insurance_bp
    from routes.background import background_bp

    app.register_blueprint(auth_bp)
    app.register_blueprint(homeowner_bp, url_prefix='/homeowner')
    app.register_blueprint(teen_bp, url_prefix='/teen')
    app.register_blueprint(admin_bp, url_prefix='/admin')
    app.register_blueprint(chat_bp, url_prefix='/chat')
    app.register_blueprint(payment_bp, url_prefix='/payment')
    app.register_blueprint(session_bp, url_prefix='/session')
    app.register_blueprint(insurance_bp, url_prefix='/insurance')
    app.register_blueprint(background_bp)

    register_socketio_events(socketio)

    @app.errorhandler(403)
    def forbidden(e):
        return render_template('errors/403.html'), 403

    @app.errorhandler(404)
    def not_found(e):
        return render_template('errors/404.html'), 404

    @app.errorhandler(500)
    def server_error(e):
        return render_template('errors/500.html'), 500

    with app.app_context():
        db.create_all()

    return app


if __name__ == '__main__':
    app = create_app()
    socketio.run(app, debug=True)
