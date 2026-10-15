from flask import Flask
from app.routes.auth_routes import auth


def create_app():

    app = Flask(__name__)

    app.secret_key = "elms-secret-key"

    app.register_blueprint(auth)

    @app.route("/employee/dashboard")
    def employee_dashboard():
        return "Welcome to Employee Dashboard!"

    @app.route("/manager/dashboard")
    def manager_dashboard():
        return "Welcome to Manager Dashboard!"

    @app.route("/hr/dashboard")
    def hr_dashboard():
        return "Welcome to HR Dashboard!"

    @app.route("/admin/dashboard")
    def admin_dashboard():
        return "Welcome to Admin Dashboard!"

    return app