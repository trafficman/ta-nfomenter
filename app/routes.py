from flask import Blueprint, jsonify, request
from .utils import get_settings, save_settings

main_bp = Blueprint('main', __name__)

@main_bp.route('/api/settings', methods=['GET'])
def get_app_settings():
    return jsonify(get_settings())

@main_bp.route('/api/settings', methods=['POST'])
def update_app_settings():
    data = request.json
    # In the future, we can add validation here
    save_settings(data)
    return jsonify({"status": "success"})