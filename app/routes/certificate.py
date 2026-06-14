import os
from io import BytesIO

from flask import (
    Blueprint,
    current_app,
    flash,
    jsonify,
    redirect,
    render_template,
    send_file,
    url_for,
)
from flask_login import current_user

from app.models import Certificate
from app.services import certificate_generator
from app.services.audio_storage import read_binary
from app.utils.helpers import get_sidebar_context
from app.utils.decorators import login_required


certificate_bp = Blueprint("certificate", __name__, url_prefix="/")


def _sidebar_payload(user_id):
    sidebar_context = get_sidebar_context(user_id)
    return {
        "pgi_summary": {
            "current_pgi": sidebar_context.get("current_pgi"),
            "pgi_direction": sidebar_context.get("pgi_direction"),
        },
        "subscription_info": {
            "subscription_tier": sidebar_context.get("subscription_tier"),
            "trial_days_remaining": sidebar_context.get("trial_days_remaining"),
        },
    }


@certificate_bp.get("/certificate")
@login_required
def index():
    eligibility_data = certificate_generator.check_eligibility(current_user.id)
    preview_data = None
    if eligibility_data.get("eligible"):
        preview_data = certificate_generator.get_certificate_preview_data(current_user.id)

    existing_certificate = Certificate.query.filter_by(user_id=current_user.id).first()

    return render_template(
        "certificate/index.html",
        title="Pressure Certificate - PressureProof",
        eligibility_data=eligibility_data,
        preview_data=preview_data,
        existing_certificate=existing_certificate,
        **_sidebar_payload(current_user.id),
    )


@certificate_bp.post("/certificate/generate")
@login_required
def generate_certificate_api():
    eligibility_data = certificate_generator.check_eligibility(current_user.id)
    if not eligibility_data.get("eligible"):
        return jsonify({"error": "Not eligible", "details": eligibility_data}), 403

    certificate = certificate_generator.generate_certificate(current_user.id)
    return jsonify(
        {
            "status": "generated",
            "certificate_id": certificate.id,
            "download_url": url_for("certificate.download"),
            "share_url": certificate.share_url,
        }
    )


@certificate_bp.get("/certificate/download")
@login_required
def download():
    certificate = Certificate.query.filter_by(user_id=current_user.id).first()
    if certificate is None or not certificate.pdf_path:
        flash("Generate your certificate first.", "warning")
        return redirect(url_for("certificate.index"))

    file_name = f"PressureProof_Certificate_{(current_user.display_name or 'User').replace(' ', '_')}.pdf"
    normalized_path = certificate.pdf_path.replace("\\", "/")

    if normalized_path.startswith("uploads/"):
        local_path = os.path.join(current_app.root_path, normalized_path)
        if not os.path.exists(local_path):
            flash("The certificate file could not be found. Please regenerate it.", "error")
            return redirect(url_for("certificate.index"))
        return send_file(
            local_path,
            as_attachment=True,
            download_name=file_name,
            mimetype="application/pdf",
        )

    binary_content = read_binary(normalized_path)
    if binary_content is None:
        flash("The certificate file could not be loaded. Please regenerate it.", "error")
        return redirect(url_for("certificate.index"))

    return send_file(
        BytesIO(binary_content),
        as_attachment=True,
        download_name=file_name,
        mimetype="application/pdf",
    )


@certificate_bp.get("/certificate/share/<token>")
def public_share(token):
    certificate = Certificate.query.filter_by(linkedin_share_token=token).first()
    if certificate is None or not certificate.is_public:
        return (
            render_template(
                "certificate/public_share.html",
                certificate=None,
                share_unavailable=True,
                title="Certificate Not Available - PressureProof",
            ),
            404,
        )

    return render_template(
        "certificate/public_share.html",
        certificate=certificate,
        certificate_user=certificate.user,
        share_unavailable=False,
        title=f"{(certificate.user.display_name or 'User')}'s PressureProof Certificate",
    )
