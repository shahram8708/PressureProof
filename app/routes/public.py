import os

from flask import Blueprint, current_app, render_template, send_file, send_from_directory


public_bp = Blueprint("public", __name__, url_prefix="/")


@public_bp.get("/")
def index():
    return render_template(
        "public/index.html",
        no_sidebar=True,
        hide_sidebar=True,
        title="PressureProof - Train Your English for High-Stakes Moments",
    )


@public_bp.get("/about")
def about():
    return render_template("public/about.html", title="About PressureProof")


@public_bp.get("/privacy")
def privacy():
    return render_template("public/privacy.html", title="Privacy Policy")


@public_bp.get("/terms")
def terms():
    return render_template("public/terms.html", title="Terms of Service")


@public_bp.get("/offline")
def offline():
    return render_template(
        "public/offline.html",
        title="Offline - PressureProof",
        hide_header=True,
        hide_footer=True,
        no_sidebar=True,
        hide_sidebar=True,
        no_sw_check=True,
    )


@public_bp.get("/manifest.json")
def manifest():
    return send_from_directory(current_app.static_folder, "manifest.json", mimetype="application/manifest+json")


@public_bp.get("/sw.js")
def service_worker():
    sw_path = os.path.join(current_app.static_folder, "sw.js")
    return send_file(sw_path, mimetype="application/javascript", conditional=True, max_age=0)
