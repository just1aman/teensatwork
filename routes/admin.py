from flask import Blueprint, render_template, redirect, url_for, flash
from flask_login import login_required
from models import db, User, Job, Conversation, Message
from routes import role_required

admin_bp = Blueprint('admin', __name__)


@admin_bp.route('/dashboard')
@login_required
@role_required('admin')
def dashboard():
    pending_count = User.query.filter_by(is_approved=False, is_rejected=False).filter(User.role != 'admin').count()
    total_users = User.query.filter(User.role != 'admin').count()
    active_jobs = Job.query.filter_by(status='open').count()
    total_conversations = Conversation.query.count()
    return render_template('admin/dashboard.html',
                           pending_count=pending_count,
                           total_users=total_users,
                           active_jobs=active_jobs,
                           total_conversations=total_conversations)


@admin_bp.route('/users/pending')
@login_required
@role_required('admin')
def pending_users():
    users = User.query.filter_by(is_approved=False, is_rejected=False).filter(
        User.role != 'admin').order_by(User.created_at.desc()).all()
    return render_template('admin/pending_users.html', users=users)


@admin_bp.route('/users/<int:user_id>/approve', methods=['POST'])
@login_required
@role_required('admin')
def approve_user(user_id):
    user = User.query.get_or_404(user_id)
    user.is_approved = True
    user.is_rejected = False
    db.session.commit()
    flash(f'{user.full_name} has been approved.', 'success')
    return redirect(url_for('admin.pending_users'))


@admin_bp.route('/users/<int:user_id>/reject', methods=['POST'])
@login_required
@role_required('admin')
def reject_user(user_id):
    user = User.query.get_or_404(user_id)
    user.is_rejected = True
    user.is_approved = False
    db.session.commit()
    flash(f'{user.full_name} has been rejected.', 'warning')
    return redirect(url_for('admin.pending_users'))


@admin_bp.route('/users')
@login_required
@role_required('admin')
def all_users():
    role_filter = __import__('flask').request.args.get('role', '')
    query = User.query.filter(User.role != 'admin')
    if role_filter in ('homeowner', 'teen'):
        query = query.filter_by(role=role_filter)
    users = query.order_by(User.created_at.desc()).all()
    return render_template('admin/all_users.html', users=users, role_filter=role_filter)


@admin_bp.route('/users/<int:user_id>/toggle', methods=['POST'])
@login_required
@role_required('admin')
def toggle_user(user_id):
    user = User.query.get_or_404(user_id)
    if user.is_approved:
        user.is_approved = False
        flash(f'{user.full_name} has been suspended.', 'warning')
    else:
        user.is_approved = True
        user.is_rejected = False
        flash(f'{user.full_name} has been activated.', 'success')
    db.session.commit()
    return redirect(url_for('admin.all_users'))


@admin_bp.route('/jobs')
@login_required
@role_required('admin')
def all_jobs():
    status_filter = __import__('flask').request.args.get('status', '')
    query = Job.query
    if status_filter in ('open', 'assigned', 'completed', 'cancelled'):
        query = query.filter_by(status=status_filter)
    jobs = query.order_by(Job.created_at.desc()).all()
    return render_template('admin/all_jobs.html', jobs=jobs, status_filter=status_filter)


@admin_bp.route('/chats')
@login_required
@role_required('admin')
def all_chats():
    conversations = Conversation.query.order_by(Conversation.created_at.desc()).all()
    return render_template('admin/view_chats.html', conversations=conversations)


@admin_bp.route('/chats/<int:conversation_id>')
@login_required
@role_required('admin')
def view_chat(conversation_id):
    conversation = Conversation.query.get_or_404(conversation_id)
    messages = Message.query.filter_by(conversation_id=conversation_id).order_by(Message.created_at.asc()).all()
    return render_template('admin/chat_detail.html', conversation=conversation, messages=messages)
