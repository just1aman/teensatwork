from flask import Blueprint, render_template, redirect, url_for, flash, request, session, current_app
from flask_login import login_user, logout_user, login_required, current_user
from werkzeug.security import generate_password_hash, check_password_hash
from models import db, User

auth_bp = Blueprint('auth', __name__)


@auth_bp.route('/')
def index():
    if current_user.is_authenticated:
        if not current_user.role:
            return redirect(url_for('auth.complete_profile'))
        if not current_user.is_approved and current_user.role != 'admin':
            return redirect(url_for('auth.pending'))
        if current_user.role == 'homeowner':
            return redirect(url_for('homeowner.dashboard'))
        elif current_user.role == 'teen':
            return redirect(url_for('teen.dashboard'))
        elif current_user.role == 'admin':
            return redirect(url_for('admin.dashboard'))
    return render_template('home.html')


@auth_bp.route('/register', methods=['GET', 'POST'])
def register():
    if current_user.is_authenticated:
        return redirect(url_for('auth.index'))

    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        email = request.form.get('email', '').strip()
        password = request.form.get('password', '')
        confirm_password = request.form.get('confirm_password', '')
        role = request.form.get('role', '')
        full_name = request.form.get('full_name', '').strip()
        phone = request.form.get('phone', '').strip()

        if not all([username, email, password, role, full_name]):
            flash('Please fill in all required fields.', 'danger')
            return render_template('auth/register.html')

        if password != confirm_password:
            flash('Passwords do not match.', 'danger')
            return render_template('auth/register.html')

        if len(password) < 6:
            flash('Password must be at least 6 characters.', 'danger')
            return render_template('auth/register.html')

        if role not in ('homeowner', 'teen'):
            flash('Invalid role selected.', 'danger')
            return render_template('auth/register.html')

        if User.query.filter_by(username=username).first():
            flash('Username already taken.', 'danger')
            return render_template('auth/register.html')

        if User.query.filter_by(email=email).first():
            flash('Email already registered.', 'danger')
            return render_template('auth/register.html')

        user = User(
            username=username,
            email=email,
            password_hash=generate_password_hash(password, method='pbkdf2:sha256'),
            role=role,
            full_name=full_name,
            phone=phone or None,
        )

        if role == 'homeowner':
            user.address = request.form.get('address', '').strip() or None
        elif role == 'teen':
            age = request.form.get('age', '')
            if not age or not age.isdigit() or not (13 <= int(age) <= 19):
                flash('Teen age must be between 13 and 19.', 'danger')
                return render_template('auth/register.html')
            user.age = int(age)
            user.parent_name = request.form.get('parent_name', '').strip() or None
            user.parent_phone = request.form.get('parent_phone', '').strip() or None

        db.session.add(user)
        db.session.commit()

        login_user(user)
        flash('Registration successful! Your account is pending admin approval.', 'info')
        return redirect(url_for('auth.pending'))

    return render_template('auth/register.html')


@auth_bp.route('/login', methods=['GET', 'POST'])
def login():
    if current_user.is_authenticated:
        return redirect(url_for('auth.index'))

    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        password = request.form.get('password', '')

        user = User.query.filter_by(username=username).first()

        if not user or not user.password_hash or not check_password_hash(user.password_hash, password):
            flash('Invalid username or password.', 'danger')
            return render_template('auth/login.html')

        if user.is_rejected:
            flash('Your account has been rejected. Please contact support.', 'danger')
            return render_template('auth/login.html')

        login_user(user)

        if not user.role:
            return redirect(url_for('auth.complete_profile'))

        if not user.is_approved and user.role != 'admin':
            return redirect(url_for('auth.pending'))

        if user.role == 'homeowner':
            return redirect(url_for('homeowner.dashboard'))
        elif user.role == 'teen':
            return redirect(url_for('teen.dashboard'))
        elif user.role == 'admin':
            return redirect(url_for('admin.dashboard'))

    return render_template('auth/login.html')


@auth_bp.route('/logout')
@login_required
def logout():
    logout_user()
    flash('You have been logged out.', 'info')
    return redirect(url_for('auth.login'))


@auth_bp.route('/pending')
@login_required
def pending():
    if current_user.is_approved or current_user.role == 'admin':
        return redirect(url_for('auth.index'))
    return render_template('auth/pending_approval.html')


# --- Google OAuth ---

@auth_bp.route('/login/google')
def google_login():
    oauth = current_app.oauth
    redirect_uri = url_for('auth.google_callback', _external=True)
    return oauth.google.authorize_redirect(redirect_uri)


@auth_bp.route('/login/google/callback')
def google_callback():
    oauth = current_app.oauth
    token = oauth.google.authorize_access_token()
    userinfo = token.get('userinfo')
    if not userinfo:
        flash('Failed to get user info from Google.', 'danger')
        return redirect(url_for('auth.login'))

    google_id = userinfo['sub']
    email = userinfo.get('email', '')
    full_name = userinfo.get('name', '')

    # Check if user already linked by google_id
    user = User.query.filter_by(google_id=google_id).first()

    if not user:
        # Check if user exists with same email (link accounts)
        user = User.query.filter_by(email=email).first()
        if user:
            user.google_id = google_id
            db.session.commit()
        else:
            # New user — create with minimal info, they'll complete profile next
            user = User(
                username=email.split('@')[0],
                email=email,
                full_name=full_name,
                google_id=google_id,
                role=None,  # will be set during profile completion
            )
            # Handle username collision
            base_username = user.username
            counter = 1
            while User.query.filter_by(username=user.username).first():
                user.username = f'{base_username}{counter}'
                counter += 1

            db.session.add(user)
            db.session.commit()

    if user.is_rejected:
        flash('Your account has been rejected. Please contact support.', 'danger')
        return redirect(url_for('auth.login'))

    login_user(user)

    # If user hasn't completed their profile yet (no role set)
    if not user.role:
        flash('Welcome! Please complete your profile to get started.', 'info')
        return redirect(url_for('auth.complete_profile'))

    if not user.is_approved and user.role != 'admin':
        return redirect(url_for('auth.pending'))

    flash(f'Welcome back, {user.full_name}!', 'success')
    if user.role == 'homeowner':
        return redirect(url_for('homeowner.dashboard'))
    elif user.role == 'teen':
        return redirect(url_for('teen.dashboard'))
    elif user.role == 'admin':
        return redirect(url_for('admin.dashboard'))
    return redirect(url_for('auth.index'))


@auth_bp.route('/complete-profile', methods=['GET', 'POST'])
@login_required
def complete_profile():
    if current_user.role:
        return redirect(url_for('auth.index'))

    if request.method == 'POST':
        role = request.form.get('role', '')
        full_name = request.form.get('full_name', '').strip()
        phone = request.form.get('phone', '').strip()
        username = request.form.get('username', '').strip()

        if not all([role, full_name, username]):
            flash('Please fill in all required fields.', 'danger')
            return render_template('auth/complete_profile.html')

        if role not in ('homeowner', 'teen'):
            flash('Invalid role selected.', 'danger')
            return render_template('auth/complete_profile.html')

        # Check username uniqueness (if changed)
        if username != current_user.username:
            if User.query.filter_by(username=username).first():
                flash('Username already taken.', 'danger')
                return render_template('auth/complete_profile.html')

        current_user.role = role
        current_user.full_name = full_name
        current_user.phone = phone or None
        current_user.username = username

        if role == 'homeowner':
            current_user.address = request.form.get('address', '').strip() or None
        elif role == 'teen':
            age = request.form.get('age', '')
            if not age or not age.isdigit() or not (13 <= int(age) <= 19):
                flash('Teen age must be between 13 and 19.', 'danger')
                return render_template('auth/complete_profile.html')
            current_user.age = int(age)
            current_user.parent_name = request.form.get('parent_name', '').strip() or None
            current_user.parent_phone = request.form.get('parent_phone', '').strip() or None

        db.session.commit()
        flash('Profile completed! Your account is pending admin approval.', 'info')
        return redirect(url_for('auth.pending'))

    return render_template('auth/complete_profile.html')
