import os
from datetime import datetime
import stripe
from flask import Blueprint, redirect, url_for, flash, request, render_template, current_app, jsonify, abort
from flask_login import login_required, current_user
from models import db, Job, JobInterest, Payment, Conversation, JobSession
from routes import role_required

payment_bp = Blueprint('payment', __name__)


def init_stripe():
    stripe.api_key = os.environ.get('STRIPE_SECRET_KEY', '')


@payment_bp.route('/jobs/<int:job_id>/checkout/<int:teen_id>', methods=['POST'])
@login_required
@role_required('homeowner')
def create_checkout(job_id, teen_id):
    """Homeowner clicks 'Accept & Pay' on an applicant — creates Stripe Checkout session."""
    init_stripe()
    job = Job.query.get_or_404(job_id)
    if job.homeowner_id != current_user.id:
        abort(403)
    if job.status != 'open':
        flash('This job is no longer open for payment.', 'warning')
        return redirect(url_for('homeowner.job_applicants', job_id=job_id))

    interest = JobInterest.query.filter_by(job_id=job_id, teen_id=teen_id).first_or_404()

    # Check if payment already exists and is paid
    existing_paid = Payment.query.filter_by(job_id=job_id, status='paid').first()
    if existing_paid:
        flash('A payment has already been completed for this job.', 'info')
        return redirect(url_for('homeowner.job_applicants', job_id=job_id))

    amount_job_cents = int(round(job.estimated_total * 100))
    amount_fee_cents = int(round(job.platform_fee * 100))
    amount_total_cents = amount_job_cents + amount_fee_cents

    try:
        session = stripe.checkout.Session.create(
            payment_method_types=['card'],
            mode='payment',
            line_items=[
                {
                    'price_data': {
                        'currency': 'usd',
                        'product_data': {
                            'name': f'Job: {job.title}',
                            'description': f'{job.category_display} — {job.estimated_hours} hrs @ ${job.hourly_rate}/hr',
                        },
                        'unit_amount': amount_job_cents,
                    },
                    'quantity': 1,
                },
                {
                    'price_data': {
                        'currency': 'usd',
                        'product_data': {
                            'name': 'Platform & Insurance Fee (10%)',
                        },
                        'unit_amount': amount_fee_cents,
                    },
                    'quantity': 1,
                },
            ],
            metadata={
                'job_id': str(job.id),
                'teen_id': str(teen_id),
                'homeowner_id': str(current_user.id),
            },
            success_url=url_for('payment.success', job_id=job.id, _external=True) + '?session_id={CHECKOUT_SESSION_ID}',
            cancel_url=url_for('payment.cancelled', job_id=job.id, _external=True),
        )
    except stripe.error.StripeError as e:
        flash(f'Payment setup failed: {str(e)}', 'danger')
        return redirect(url_for('homeowner.job_applicants', job_id=job_id))

    payment = Payment(
        job_id=job.id,
        homeowner_id=current_user.id,
        teen_id=teen_id,
        amount_total=amount_total_cents,
        amount_job=amount_job_cents,
        amount_fee=amount_fee_cents,
        stripe_checkout_session_id=session.id,
        status='pending',
    )
    db.session.add(payment)
    db.session.commit()

    return redirect(session.url, code=303)


@payment_bp.route('/jobs/<int:job_id>/success')
@login_required
def success(job_id):
    """Stripe redirects here after successful payment."""
    init_stripe()
    job = Job.query.get_or_404(job_id)
    session_id = request.args.get('session_id')

    if not session_id:
        flash('Missing session ID.', 'danger')
        return redirect(url_for('homeowner.my_jobs'))

    payment = Payment.query.filter_by(stripe_checkout_session_id=session_id).first()
    if not payment:
        flash('Payment record not found.', 'danger')
        return redirect(url_for('homeowner.my_jobs'))

    # Retrieve the Stripe session to confirm payment
    try:
        session = stripe.checkout.Session.retrieve(session_id)
    except stripe.error.StripeError as e:
        flash(f'Could not verify payment: {str(e)}', 'danger')
        return redirect(url_for('homeowner.my_jobs'))

    if session.payment_status == 'paid' and payment.status != 'paid':
        # Mark payment as paid
        payment.status = 'paid'
        payment.paid_at = datetime.utcnow()
        payment.stripe_payment_intent_id = session.payment_intent

        # Complete the teen acceptance
        _finalize_teen_acceptance(job, payment.teen_id)
        db.session.commit()

    return render_template('payment/success.html', job=job, payment=payment)


@payment_bp.route('/jobs/<int:job_id>/cancelled')
@login_required
def cancelled(job_id):
    """Homeowner abandoned Stripe checkout."""
    job = Job.query.get_or_404(job_id)
    # Remove pending payment record
    pending = Payment.query.filter_by(job_id=job_id, status='pending',
                                       homeowner_id=current_user.id).first()
    if pending:
        db.session.delete(pending)
        db.session.commit()
    flash('Payment cancelled. No charges were made.', 'info')
    return redirect(url_for('homeowner.job_applicants', job_id=job_id))


@payment_bp.route('/webhook/stripe', methods=['POST'])
def stripe_webhook():
    """Stripe webhook for checkout.session.completed and charge events."""
    init_stripe()
    payload = request.data
    sig_header = request.headers.get('Stripe-Signature', '')
    webhook_secret = os.environ.get('STRIPE_WEBHOOK_SECRET', '')

    try:
        if webhook_secret:
            event = stripe.Webhook.construct_event(payload, sig_header, webhook_secret)
        else:
            # No secret configured yet — parse without verification (dev only)
            event = stripe.Event.construct_from(
                request.get_json(force=True), stripe.api_key
            )
    except Exception as e:
        return jsonify({'error': str(e)}), 400

    if event['type'] == 'checkout.session.completed':
        session = event['data']['object']
        payment = Payment.query.filter_by(stripe_checkout_session_id=session['id']).first()
        if payment and payment.status != 'paid':
            payment.status = 'paid'
            payment.paid_at = datetime.utcnow()
            payment.stripe_payment_intent_id = session.get('payment_intent')
            job = Job.query.get(payment.job_id)
            if job and job.status == 'open':
                _finalize_teen_acceptance(job, payment.teen_id)
            db.session.commit()

    return jsonify({'received': True}), 200


def _finalize_teen_acceptance(job, teen_id):
    """Once payment is confirmed, mark the teen as accepted and create the conversation."""
    interest = JobInterest.query.filter_by(job_id=job.id, teen_id=teen_id).first()
    if interest:
        interest.status = 'accepted'
    job.status = 'assigned'
    job.assigned_teen_id = teen_id

    conv = Conversation.query.filter_by(
        homeowner_id=job.homeowner_id, teen_id=teen_id, job_id=job.id
    ).first()
    if not conv:
        conv = Conversation(
            homeowner_id=job.homeowner_id,
            teen_id=teen_id,
            job_id=job.id,
        )
        db.session.add(conv)

    # Create a JobSession (with unique QR token) for this job
    session = JobSession.query.filter_by(job_id=job.id).first()
    if not session:
        session = JobSession(job_id=job.id, status='pending')
        db.session.add(session)


def issue_refund(payment, refund_cents, reason=None):
    """Issue a refund via Stripe. Returns (success, message)."""
    init_stripe()
    if not payment.stripe_payment_intent_id:
        return False, 'No payment intent to refund.'
    if refund_cents <= 0:
        return True, 'No refund needed.'

    try:
        refund = stripe.Refund.create(
            payment_intent=payment.stripe_payment_intent_id,
            amount=refund_cents,
            reason='requested_by_customer',
            metadata={'cancellation_reason': reason or ''},
        )
        payment.stripe_refund_id = refund.id
        payment.amount_refunded = (payment.amount_refunded or 0) + refund_cents
        payment.refunded_at = datetime.utcnow()
        if payment.amount_refunded >= payment.amount_total:
            payment.status = 'refunded'
        else:
            payment.status = 'partial_refund'
        return True, 'Refund issued.'
    except stripe.error.StripeError as e:
        return False, str(e)
