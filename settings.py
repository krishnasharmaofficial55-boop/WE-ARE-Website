from flask import Blueprint, render_template, request, redirect, url_for, flash, current_app

from .db import get_db
from .security import current_user, login_required, csrf_protect, get_csrf_token
from .uploads import save_avatar, UploadError

bp = Blueprint("settings", __name__)

PROFILE_FIELDS = [
    ("bio", "Bio", 280),
    ("who_i_am", "Who I am", 200),
    ("what_i_care_about", "What I care about", 300),
    ("how_i_think", "How I think", 300),
    ("what_im_learning", "What I'm learning", 200),
    ("what_im_building", "What I'm building", 200),
    ("current_goals", "Current goals", 300),
    ("languages", "Languages", 150),
]


@bp.before_request
def _csrf():
    csrf_protect()


@bp.route("/settings", methods=["GET", "POST"])
@login_required
def profile_settings():
    user = current_user()
    db = get_db()

    if request.method == "POST":
        if "avatar" in request.files and request.files["avatar"].filename:
            try:
                url = save_avatar(request.files["avatar"])
                db.execute("UPDATE profiles SET avatar_url = ?, updated_at = datetime('now') WHERE user_id = ?",
                           (url, user["id"]))
                db.commit()
                flash("Profile photo updated.", "success")
            except UploadError as e:
                flash(str(e), "error")
            return redirect(url_for("settings.profile_settings"))

        values = {}
        for key, _, max_len in PROFILE_FIELDS:
            val = request.form.get(key, "").strip()[:max_len]
            values[key] = val

        show_real_name = 1 if request.form.get("show_real_name") == "on" else 0

        db.execute(
            """UPDATE profiles SET bio = ?, who_i_am = ?, what_i_care_about = ?, how_i_think = ?,
                                    what_im_learning = ?, what_im_building = ?, current_goals = ?,
                                    languages = ?, updated_at = datetime('now')
               WHERE user_id = ?""",
            (values["bio"], values["who_i_am"], values["what_i_care_about"], values["how_i_think"],
             values["what_im_learning"], values["what_im_building"], values["current_goals"],
             values["languages"], user["id"]),
        )
        db.execute("UPDATE users SET show_real_name = ? WHERE id = ?", (show_real_name, user["id"]))
        db.commit()
        flash("Profile updated.", "success")
        return redirect(url_for("settings.profile_settings"))

    profile = db.execute("SELECT * FROM profiles WHERE user_id = ?", (user["id"],)).fetchone()
    return render_template(
        "settings.html", user=user, profile=profile, fields=PROFILE_FIELDS, csrf_token=get_csrf_token(),
    )
