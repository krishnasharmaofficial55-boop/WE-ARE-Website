import os
from flask import Flask

from .config import Config
from .db import init_db
from .security import get_csrf_token, current_user


def create_app(config_object=Config):
    app = Flask(__name__)
    app.config.from_object(config_object)

    if app.config["ENV"] == "production" and app.config["SECRET_KEY"] == "dev-only-change-me":
        raise RuntimeError(
            "Refusing to start in production with the default SECRET_KEY. "
            "Set the SECRET_KEY environment variable."
        )

    init_db(app)

    from . import auth, main
    app.register_blueprint(auth.bp)
    app.register_blueprint(main.bp)

    @app.context_processor
    def inject_globals():
        # Named distinctly from the per-page `csrf_token` string some views
        # pass into render_template — Jinja would otherwise let one shadow
        # the other depending on render order.
        return {"nav_csrf_token": get_csrf_token(), "current_user": current_user()}

    @app.after_request
    def set_security_headers(response):
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        return response

    return app
