from datetime import datetime
from flask import Blueprint, render_template, redirect, url_for, flash, request
from flask_login import login_required, current_user
from models import db, Job, JobInterest, Conversation, Payment, JOB_CATEGORIES
from routes import role_required
from routes.payment import issue_refund

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
        scheduled_start_str = request.form.get('scheduled_start', '').strip()

        if not all([title, category, description, hourly_rate, estimated_hours, scheduled_start_str]):
            flash('Please fill in all fields including scheduled start date/time.', 'danger')
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

        try:
            scheduled_start = datetime.strptime(scheduled_start_str, '%Y-%m-%dT%H:%M')
        except ValueError:
            flash('Invalid date/time format for scheduled start.', 'danger')
            return render_template('homeowner/create_job.html', categories=JOB_CATEGORIES)

        if scheduled_start <= datetime.utcnow():
            flash('Scheduled start must be in the future.', 'danger')
            return render_template('homeowner/create_job.html', categories=JOB_CATEGORIES)

        job = Job(
            homeowner_id=current_user.id,
            title=title,
            category=category,
            description=description,
            hourly_rate=hourly_rate,
            estimated_hours=estimated_hours,
            scheduled_start=scheduled_start,
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

        scheduled_start_str = request.form.get('scheduled_start', '').strip()
        if scheduled_start_str:
            try:
                new_start = datetime.strptime(scheduled_start_str, '%Y-%m-%dT%H:%M')
                if new_start <= datetime.utcnow():
                    flash('Scheduled start must be in the future.', 'danger')
                    return render_template('homeowner/edit_job.html', job=job, categories=JOB_CATEGORIES)
                job.scheduled_start = new_start
            except ValueError:
                flash('Invalid date/time format for scheduled start.', 'danger')
                return render_template('homeowner/edit_job.html', job=job, categories=JOB_CATEGORIES)

        db.session.commit()
        flash('Job updated successfully!', 'success')
        return redirect(url_for('homeowner.my_jobs'))

    return render_template('homeowner/edit_job.html', job=job, categories=JOB_CATEGORIES)


@homeowner_bp.route('/jobs/<int:job_id>/cancel', methods=['GET', 'POST'])
@login_required
@role_required('homeowner')
def cancel_job(job_id):
    job = Job.query.get_or_404(job_id)
    if job.homeowner_id != current_user.id:
        flash('Access denied.', 'danger')
        return redirect(url_for('homeowner.my_jobs'))

    if job.status in ('cancelled', 'completed'):
        flash('This job cannot be cancelled.', 'warning')
        return redirect(url_for('homeowner.my_jobs'))

    # GET: show confirmation page with fee breakdown
    if request.method == 'GET':
        return render_template('homeowner/cancel_job.html', job=job)

    # POST: actually cancel
    reason = request.form.get('reason', '').strip()
    total = job.estimated_total

    # Find the paid payment for this job, if any
    payment = Payment.query.filter_by(job_id=job.id, status='paid').first()

    if job.can_cancel_free:
        # More than 24 hours before start — full refund, no fee
        job.cancellation_fee = 0.0
        job.refund_amount = job.total_with_fee
        refund_cents = payment.amount_total if payment else 0
        cancel_msg = 'Job cancelled with full refund. No cancellation fee.'
    else:
        # Within 24 hours of start — 10% fee goes to assigned teen
        job.cancellation_fee = total * 0.10
        job.refund_amount = job.total_with_fee - job.cancellation_fee
        refund_cents = int(round(job.refund_amount * 100)) if payment else 0
        if payment:
            # Record the cancellation fee as a payout owed to the teen (simulated in Phase B)
            payment.amount_payout = int(round(job.cancellation_fee * 100))
        cancel_msg = (f'Job cancelled. Cancellation fee: ${job.cancellation_fee:.2f} owed to teen. '
                      f'Refund: ${job.refund_amount:.2f}.')

    if payment and refund_cents > 0:
        ok, msg = issue_refund(payment, refund_cents, reason=reason)
        if not ok:
            flash(f'Cancellation recorded, but refund failed: {msg}. Contact support.', 'danger')
        else:
            flash(cancel_msg + ' Refund is processing via Stripe.', 'success' if job.can_cancel_free else 'warning')
    else:
        flash(cancel_msg, 'success' if job.can_cancel_free else 'warning')

    job.status = 'cancelled'
    job.cancelled_at = datetime.utcnow()
    job.cancellation_reason = reason or None
    db.session.commit()
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
    """Accept a teen — redirects to payment checkout. Actual acceptance happens after payment succeeds."""
    job = Job.query.get_or_404(job_id)
    if job.homeowner_id != current_user.id:
        flash('Access denied.', 'danger')
        return redirect(url_for('homeowner.my_jobs'))

    if job.status != 'open':
        flash('This job is no longer open.', 'warning')
        return redirect(url_for('homeowner.job_applicants', job_id=job_id))

    # Redirect to payment checkout
    return redirect(url_for('payment.create_checkout', job_id=job_id, teen_id=teen_id), code=307)


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
