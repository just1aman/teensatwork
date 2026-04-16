import io
from datetime import datetime
import qrcode
from flask import Blueprint, render_template, redirect, url_for, flash, request, abort, send_file, jsonify
from flask_login import login_required, current_user
from models import db, Job, JobSession
from routes import role_required
from routes.insurance import issue_policy, close_policy

session_bp = Blueprint('session', __name__)


@session_bp.route('/job/<int:job_id>/qr')
@login_required
def teen_qr(job_id):
    """Teen's page: displays the QR code for the homeowner to scan."""
    job = Job.query.get_or_404(job_id)
    if current_user.id != job.assigned_teen_id:
        abort(403)

    session = JobSession.query.filter_by(job_id=job_id).first()
    if not session:
        flash('No session found for this job.', 'danger')
        return redirect(url_for('teen.dashboard'))

    return render_template('session/teen_qr.html', job=job, session=session)


@session_bp.route('/qr-image/<token>.png')
@login_required
def qr_image(token):
    """Renders the QR code as a PNG. Token is in the URL so img src works."""
    sess = JobSession.query.filter_by(token=token).first_or_404()
    # Authorize: only the assigned teen or the homeowner of this job
    if current_user.id not in (sess.job.assigned_teen_id, sess.job.homeowner_id):
        abort(403)

    # The QR encodes a URL that triggers the scan action on the homeowner's phone
    scan_url = url_for('session.scan_action', token=token, _external=True)
    img = qrcode.make(scan_url, box_size=10, border=2)
    buf = io.BytesIO()
    img.save(buf, format='PNG')
    buf.seek(0)
    return send_file(buf, mimetype='image/png')


@session_bp.route('/scan/<token>')
@login_required
def scan_action(token):
    """Homeowner lands here after scanning the QR. Shows start or end job screen."""
    sess = JobSession.query.filter_by(token=token).first_or_404()
    job = sess.job

    if current_user.id != job.homeowner_id:
        flash('Only the homeowner can scan this code.', 'danger')
        return redirect(url_for('auth.index'))

    if sess.status == 'pending':
        return render_template('session/confirm_start.html', job=job, session=sess)
    elif sess.status == 'in_progress':
        return render_template('session/confirm_end.html', job=job, session=sess)
    else:
        flash('This job has already been completed.', 'info')
        return redirect(url_for('session.view', job_id=job.id))


@session_bp.route('/start/<token>', methods=['POST'])
@login_required
@role_required('homeowner')
def start_session(token):
    """Homeowner confirms starting the work timer."""
    sess = JobSession.query.filter_by(token=token).first_or_404()
    job = sess.job

    if current_user.id != job.homeowner_id:
        abort(403)
    if sess.status != 'pending':
        flash('Session already started or completed.', 'warning')
        return redirect(url_for('session.view', job_id=job.id))

    sess.started_at = datetime.utcnow()
    sess.start_scan_by_id = current_user.id
    sess.status = 'in_progress'
    job.status = 'in_progress'
    db.session.commit()

    # Auto-issue insurance policy when work begins
    try:
        policy = issue_policy(sess)
        flash(f'Work timer started! Insurance certificate #{policy.certificate_id} active.', 'success')
    except Exception as e:
        flash(f'Work timer started (warning: insurance issuance failed: {e}).', 'warning')

    return redirect(url_for('session.view', job_id=job.id))


@session_bp.route('/end/<token>', methods=['POST'])
@login_required
@role_required('homeowner')
def end_session(token):
    """Homeowner confirms ending the work timer."""
    sess = JobSession.query.filter_by(token=token).first_or_404()
    job = sess.job

    if current_user.id != job.homeowner_id:
        abort(403)
    if sess.status != 'in_progress':
        flash('Session is not in progress.', 'warning')
        return redirect(url_for('session.view', job_id=job.id))

    sess.ended_at = datetime.utcnow()
    sess.end_scan_by_id = current_user.id
    sess.actual_hours = round(sess.elapsed_hours, 2)
    sess.final_amount = round(sess.actual_hours * job.hourly_rate, 2)
    sess.status = 'completed'
    job.status = 'completed'
    db.session.commit()

    # Close any active insurance policies for this session
    from models import InsurancePolicy
    active_policies = InsurancePolicy.query.filter_by(session_id=sess.id, status='active').all()
    for policy in active_policies:
        close_policy(policy, actual_end=sess.ended_at)

    flash(f'Job completed! Actual hours: {sess.actual_hours}, final amount: ${sess.final_amount}.', 'success')
    return redirect(url_for('session.view', job_id=job.id))


@session_bp.route('/job/<int:job_id>')
@login_required
def view(job_id):
    """Live timer view — visible to both homeowner and teen."""
    job = Job.query.get_or_404(job_id)
    if current_user.id not in (job.homeowner_id, job.assigned_teen_id):
        abort(403)

    sess = JobSession.query.filter_by(job_id=job_id).first()
    if not sess:
        flash('No session for this job.', 'danger')
        return redirect(url_for('auth.index'))

    return render_template('session/view.html', job=job, session=sess)


@session_bp.route('/job/<int:job_id>/elapsed')
@login_required
def elapsed_json(job_id):
    """AJAX endpoint for live-updating timer."""
    job = Job.query.get_or_404(job_id)
    if current_user.id not in (job.homeowner_id, job.assigned_teen_id):
        abort(403)

    sess = JobSession.query.filter_by(job_id=job_id).first()
    if not sess:
        return jsonify({'error': 'no session'}), 404

    return jsonify({
        'status': sess.status,
        'elapsed_seconds': sess.elapsed_seconds,
        'elapsed_hours': sess.elapsed_hours,
        'final_amount': sess.final_amount,
        'actual_hours': sess.actual_hours,
    })


@session_bp.route('/scanner')
@login_required
@role_required('homeowner')
def scanner():
    """Homeowner's camera-based QR scanner page."""
    return render_template('session/scanner.html')
