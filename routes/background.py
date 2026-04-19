"""
Background check integration.

Currently uses a MOCK provider that auto-clears after a simulated delay.
When Checkr staging/production keys are available, swap _run_via_provider()
and _handle_webhook_event() with real Checkr API calls.

Checkr API reference:
  - Staging: https://api.checkr-staging.com/v1
  - Production: https://api.checkr.com/v1
  - Auth: HTTP Basic (API key as username, empty password)
"""
import os
import json
import secrets
from datetime import datetime
import stripe
from flask import Blueprint, render_template, redirect, url_for, flash, request, jsonify, abort
from flask_login import login_required, current_user
from models import db, User, BackgroundCheck
from routes import role_required

background_bp = Blueprint('background', __name__)

BACKGROUND_CHECK_FEE_CENTS = 3000  # $30.00


# ============================================================
# PUBLIC API — called by other parts of the app
# ============================================================

def initiate_background_check(user):
    """
    Start a background check for a homeowner.
    Returns (BackgroundCheck, error_message).
    """
    # Don't double-check
    existing = BackgroundCheck.query.filter_by(user_id=user.id).filter(
        BackgroundCheck.status.in_(['pending', 'complete'])
    ).first()
    if existing:
        return existing, 'Background check already initiated.'

    check = BackgroundCheck(
        user_id=user.id,
        status='pending',
    )
    db.session.add(check)

    result = _run_via_provider(user, check)
    if result.get('error'):
        check.status = 'error'
        check.result_details = json.dumps(result)
        db.session.commit()
        return check, result['error']

    check.provider_candidate_id = result.get('candidate_id')
    check.provider_report_id = result.get('report_id')
    check.provider = result.get('provider', 'mock')
    check.result_details = json.dumps(result)

    # Mock provider returns immediate results
    if result.get('immediate_result'):
        check.status = 'complete'
        check.result = result['immediate_result']
        check.completed_at = datetime.utcnow()
        user.background_check_status = result['immediate_result']

    db.session.commit()
    return check, None


# ============================================================
# PROVIDER IMPLEMENTATION (mock — swap for Checkr later)
# ============================================================

def _run_via_provider(user, check):
    """
    MOCK: Simulates a background check that instantly clears.

    TODO(checkr): Replace with real Checkr API calls:
        import requests
        CHECKR_KEY = os.environ.get('CHECKR_API_KEY', '')
        BASE_URL = os.environ.get('CHECKR_BASE_URL', 'https://api.checkr-staging.com/v1')

        # 1. Create candidate
        resp = requests.post(f'{BASE_URL}/candidates', auth=(CHECKR_KEY, ''), json={
            'first_name': user.full_name.split()[0],
            'last_name': ' '.join(user.full_name.split()[1:]) or user.full_name,
            'email': user.email,
            'phone': user.phone,
        })
        candidate = resp.json()

        # 2. Create invitation (triggers Checkr-hosted flow)
        resp = requests.post(f'{BASE_URL}/invitations', auth=(CHECKR_KEY, ''), json={
            'candidate_id': candidate['id'],
            'package': 'tasker_standard',
            'work_locations': [{'state': 'US', 'country': 'US'}],
        })
        invitation = resp.json()

        return {
            'provider': 'checkr',
            'candidate_id': candidate['id'],
            'report_id': None,  # comes later via webhook
            'invitation_id': invitation['id'],
        }
    """
    mock_id = f'mock-{secrets.token_hex(8)}'
    return {
        'provider': 'mock',
        'candidate_id': mock_id,
        'report_id': f'report-{mock_id}',
        'immediate_result': 'clear',  # mock always clears
        'checks_run': ['criminal_national', 'sex_offender_registry', 'identity_verification'],
        'mock_note': 'Simulated background check. Not a real screening.',
    }


# ============================================================
# ROUTES
# ============================================================

@background_bp.route('/homeowner/verify', methods=['GET'])
@login_required
@role_required('homeowner')
def verify_page():
    """Shows the background check status page to homeowners."""
    existing = BackgroundCheck.query.filter_by(user_id=current_user.id).order_by(
        BackgroundCheck.created_at.desc()).first()
    return render_template('background/verify.html', check=existing,
                           fee_dollars=BACKGROUND_CHECK_FEE_CENTS / 100)


@background_bp.route('/homeowner/verify/start', methods=['POST'])
@login_required
@role_required('homeowner')
def start_check():
    """Homeowner clicks 'Start Background Check' — charges $30 and runs the check."""
    stripe.api_key = os.environ.get('STRIPE_SECRET_KEY', '')

    # Check if already done
    existing = BackgroundCheck.query.filter_by(user_id=current_user.id).filter(
        BackgroundCheck.result == 'clear'
    ).first()
    if existing:
        flash('Your background check is already complete.', 'info')
        return redirect(url_for('background.verify_page'))

    # Charge the $30 fee via Stripe
    try:
        payment_intent = stripe.PaymentIntent.create(
            amount=BACKGROUND_CHECK_FEE_CENTS,
            currency='usd',
            payment_method_types=['card'],
            description=f'Background Check Fee — {current_user.full_name}',
            metadata={
                'user_id': str(current_user.id),
                'type': 'background_check',
            },
            confirm=False,
        )
    except stripe.error.StripeError as e:
        flash(f'Payment setup failed: {str(e)}', 'danger')
        return redirect(url_for('background.verify_page'))

    # For simplicity in mock mode, skip actual card collection and auto-confirm
    # In production, you'd redirect to a Stripe checkout or use Elements
    check, error = initiate_background_check(current_user)
    if error and 'already' not in error:
        flash(f'Background check failed: {error}', 'danger')
        return redirect(url_for('background.verify_page'))

    if check:
        check.stripe_payment_intent_id = payment_intent.id
        check.amount_paid = BACKGROUND_CHECK_FEE_CENTS
        db.session.commit()

    if check and check.result == 'clear':
        flash('Background check complete — you are verified!', 'success')
    elif check and check.status == 'pending':
        flash('Background check initiated. You will be notified when results are ready.', 'info')
    else:
        flash('Background check submitted.', 'info')

    return redirect(url_for('background.verify_page'))


@background_bp.route('/homeowner/verify/status')
@login_required
@role_required('homeowner')
def check_status_json():
    """AJAX endpoint for polling background check status."""
    check = BackgroundCheck.query.filter_by(user_id=current_user.id).order_by(
        BackgroundCheck.created_at.desc()).first()
    if not check:
        return jsonify({'status': 'none'})
    return jsonify({
        'status': check.status,
        'result': check.result,
        'provider': check.provider,
        'completed_at': check.completed_at.isoformat() if check.completed_at else None,
    })


@background_bp.route('/webhook/checkr', methods=['POST'])
def checkr_webhook():
    """
    Webhook endpoint for Checkr to send report results.

    TODO(checkr): Verify webhook signature, parse event, update BackgroundCheck.

    Expected events:
      - report.completed: check.status = 'complete', check.result = data['result']
      - report.updated: status changes during processing
    """
    data = request.get_json(force=True)
    event_type = data.get('type', '')

    if event_type == 'report.completed':
        report_id = data.get('data', {}).get('object', {}).get('id')
        result = data.get('data', {}).get('object', {}).get('result', 'consider')

        check = BackgroundCheck.query.filter_by(provider_report_id=report_id).first()
        if check:
            check.status = 'complete'
            check.result = result
            check.completed_at = datetime.utcnow()
            check.result_details = json.dumps(data)

            user = check.user
            user.background_check_status = result
            db.session.commit()

    return jsonify({'received': True}), 200


# ============================================================
# ADMIN ROUTES
# ============================================================

@background_bp.route('/admin/checks')
@login_required
@role_required('admin')
def admin_list():
    """Admin view of all background checks."""
    checks = BackgroundCheck.query.order_by(BackgroundCheck.created_at.desc()).all()
    return render_template('background/admin_list.html', checks=checks)
