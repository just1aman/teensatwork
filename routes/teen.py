from flask import Blueprint, render_template, redirect, url_for, flash, request
from flask_login import login_required, current_user
from models import db, Job, JobInterest, JOB_CATEGORIES
from routes import role_required

teen_bp = Blueprint('teen', __name__)


@teen_bp.route('/dashboard')
@login_required
@role_required('teen')
def dashboard():
    my_interests = JobInterest.query.filter_by(teen_id=current_user.id).all()
    pending = [i for i in my_interests if i.status == 'pending']
    accepted = [i for i in my_interests if i.status == 'accepted']
    return render_template('teen/dashboard.html',
                           pending_count=len(pending),
                           accepted_count=len(accepted),
                           recent_interests=my_interests[:5])


@teen_bp.route('/jobs')
@login_required
@role_required('teen')
def browse_jobs():
    category_filter = request.args.get('category', '')
    search = request.args.get('search', '').strip()
    page = request.args.get('page', 1, type=int)

    query = Job.query.filter_by(status='open')
    if category_filter:
        query = query.filter_by(category=category_filter)
    if search:
        query = query.filter(Job.title.ilike(f'%{search}%') | Job.description.ilike(f'%{search}%'))

    jobs = query.order_by(Job.created_at.desc()).paginate(page=page, per_page=10, error_out=False)

    # Get job IDs this teen already expressed interest in
    my_interest_job_ids = {i.job_id for i in JobInterest.query.filter_by(teen_id=current_user.id).all()}

    return render_template('teen/browse_jobs.html',
                           jobs=jobs,
                           categories=JOB_CATEGORIES,
                           category_filter=category_filter,
                           search=search,
                           my_interest_job_ids=my_interest_job_ids)


@teen_bp.route('/jobs/<int:job_id>')
@login_required
@role_required('teen')
def job_detail(job_id):
    job = Job.query.get_or_404(job_id)
    existing_interest = JobInterest.query.filter_by(job_id=job_id, teen_id=current_user.id).first()
    return render_template('teen/job_detail.html', job=job, existing_interest=existing_interest)


@teen_bp.route('/jobs/<int:job_id>/interest', methods=['POST'])
@login_required
@role_required('teen')
def show_interest(job_id):
    job = Job.query.get_or_404(job_id)
    if job.status != 'open':
        flash('This job is no longer open.', 'warning')
        return redirect(url_for('teen.browse_jobs'))

    existing = JobInterest.query.filter_by(job_id=job_id, teen_id=current_user.id).first()
    if existing:
        flash('You have already expressed interest in this job.', 'info')
        return redirect(url_for('teen.job_detail', job_id=job_id))

    message = request.form.get('message', '').strip() or None
    interest = JobInterest(
        job_id=job_id,
        teen_id=current_user.id,
        message=message,
    )
    db.session.add(interest)
    db.session.commit()
    flash('Interest submitted! The homeowner will review your application.', 'success')
    return redirect(url_for('teen.job_detail', job_id=job_id))
