from flask import Blueprint, render_template, redirect, url_for, flash, request
from flask_login import login_required, current_user
from models import db, Job, JobInterest, Conversation, JOB_CATEGORIES
from routes import role_required

homeowner_bp = Blueprint('homeowner', __name__)


@homeowner_bp.route('/dashboard')
@login_required
@role_required('homeowner')
def dashboard():
    my_jobs = Job.query.filter_by(homeowner_id=current_user.id).all()
    open_jobs = [j for j in my_jobs if j.status == 'open']
    assigned_jobs = [j for j in my_jobs if j.status == 'assigned']
    pending_interests = JobInterest.query.join(Job).filter(
        Job.homeowner_id == current_user.id,
        JobInterest.status == 'pending'
    ).count()
    return render_template('homeowner/dashboard.html',
                           open_jobs=len(open_jobs),
                           assigned_jobs=len(assigned_jobs),
                           pending_interests=pending_interests,
                           recent_jobs=my_jobs[:5])


@homeowner_bp.route('/jobs')
@login_required
@role_required('homeowner')
def my_jobs():
    jobs = Job.query.filter_by(homeowner_id=current_user.id).order_by(Job.created_at.desc()).all()
    return render_template('homeowner/my_jobs.html', jobs=jobs)


@homeowner_bp.route('/jobs/new', methods=['GET', 'POST'])
@login_required
@role_required('homeowner')
def create_job():
    if request.method == 'POST':
        title = request.form.get('title', '').strip()
        category = request.form.get('category', '')
        description = request.form.get('description', '').strip()
        hourly_rate = request.form.get('hourly_rate', '')
        estimated_hours = request.form.get('estimated_hours', '')

        if not all([title, category, description, hourly_rate, estimated_hours]):
            flash('Please fill in all fields.', 'danger')
            return render_template('homeowner/create_job.html', categories=JOB_CATEGORIES)

        try:
            hourly_rate = float(hourly_rate)
            estimated_hours = float(estimated_hours)
        except ValueError:
            flash('Invalid rate or hours value.', 'danger')
            return render_template('homeowner/create_job.html', categories=JOB_CATEGORIES)

        if hourly_rate < 1 or estimated_hours < 0.5:
            flash('Hourly rate must be at least $1 and hours at least 0.5.', 'danger')
            return render_template('homeowner/create_job.html', categories=JOB_CATEGORIES)

        job = Job(
            homeowner_id=current_user.id,
            title=title,
            category=category,
            description=description,
            hourly_rate=hourly_rate,
            estimated_hours=estimated_hours,
        )
        db.session.add(job)
        db.session.commit()
        flash('Job posted successfully!', 'success')
        return redirect(url_for('homeowner.my_jobs'))

    return render_template('homeowner/create_job.html', categories=JOB_CATEGORIES)


@homeowner_bp.route('/jobs/<int:job_id>/edit', methods=['GET', 'POST'])
@login_required
@role_required('homeowner')
def edit_job(job_id):
    job = Job.query.get_or_404(job_id)
    if job.homeowner_id != current_user.id:
        flash('Access denied.', 'danger')
        return redirect(url_for('homeowner.my_jobs'))

    if request.method == 'POST':
        job.title = request.form.get('title', '').strip()
        job.category = request.form.get('category', '')
        job.description = request.form.get('description', '').strip()
        try:
            job.hourly_rate = float(request.form.get('hourly_rate', 0))
            job.estimated_hours = float(request.form.get('estimated_hours', 0))
        except ValueError:
            flash('Invalid rate or hours value.', 'danger')
            return render_template('homeowner/edit_job.html', job=job, categories=JOB_CATEGORIES)

        db.session.commit()
        flash('Job updated successfully!', 'success')
        return redirect(url_for('homeowner.my_jobs'))

    return render_template('homeowner/edit_job.html', job=job, categories=JOB_CATEGORIES)


@homeowner_bp.route('/jobs/<int:job_id>/cancel', methods=['POST'])
@login_required
@role_required('homeowner')
def cancel_job(job_id):
    job = Job.query.get_or_404(job_id)
    if job.homeowner_id != current_user.id:
        flash('Access denied.', 'danger')
        return redirect(url_for('homeowner.my_jobs'))
    job.status = 'cancelled'
    db.session.commit()
    flash('Job cancelled.', 'info')
    return redirect(url_for('homeowner.my_jobs'))


@homeowner_bp.route('/jobs/<int:job_id>/complete', methods=['POST'])
@login_required
@role_required('homeowner')
def complete_job(job_id):
    job = Job.query.get_or_404(job_id)
    if job.homeowner_id != current_user.id:
        flash('Access denied.', 'danger')
        return redirect(url_for('homeowner.my_jobs'))
    job.status = 'completed'
    db.session.commit()
    flash('Job marked as completed!', 'success')
    return redirect(url_for('homeowner.my_jobs'))


@homeowner_bp.route('/jobs/<int:job_id>/applicants')
@login_required
@role_required('homeowner')
def job_applicants(job_id):
    job = Job.query.get_or_404(job_id)
    if job.homeowner_id != current_user.id:
        flash('Access denied.', 'danger')
        return redirect(url_for('homeowner.my_jobs'))
    interests = JobInterest.query.filter_by(job_id=job.id).order_by(JobInterest.created_at.desc()).all()
    return render_template('homeowner/job_applicants.html', job=job, interests=interests)


@homeowner_bp.route('/jobs/<int:job_id>/accept/<int:teen_id>', methods=['POST'])
@login_required
@role_required('homeowner')
def accept_teen(job_id, teen_id):
    job = Job.query.get_or_404(job_id)
    if job.homeowner_id != current_user.id:
        flash('Access denied.', 'danger')
        return redirect(url_for('homeowner.my_jobs'))

    interest = JobInterest.query.filter_by(job_id=job_id, teen_id=teen_id).first_or_404()
    interest.status = 'accepted'
    job.status = 'assigned'
    job.assigned_teen_id = teen_id
    db.session.commit()

    # Create conversation if it doesn't exist
    conv = Conversation.query.filter_by(
        homeowner_id=current_user.id, teen_id=teen_id, job_id=job_id
    ).first()
    if not conv:
        conv = Conversation(
            homeowner_id=current_user.id,
            teen_id=teen_id,
            job_id=job_id,
        )
        db.session.add(conv)
        db.session.commit()

    flash(f'Teen accepted for "{job.title}"! You can now chat with them.', 'success')
    return redirect(url_for('homeowner.job_applicants', job_id=job_id))


@homeowner_bp.route('/jobs/<int:job_id>/reject/<int:teen_id>', methods=['POST'])
@login_required
@role_required('homeowner')
def reject_teen(job_id, teen_id):
    job = Job.query.get_or_404(job_id)
    if job.homeowner_id != current_user.id:
        flash('Access denied.', 'danger')
        return redirect(url_for('homeowner.my_jobs'))

    interest = JobInterest.query.filter_by(job_id=job_id, teen_id=teen_id).first_or_404()
    interest.status = 'rejected'
    db.session.commit()
    flash('Interest rejected.', 'info')
    return redirect(url_for('homeowner.job_applicants', job_id=job_id))
