"""
Insurance provider integration.

Currently uses a MOCK provider. When Thimble partnership is approved,
swap out the internals of `_issue_via_provider()` and `_cancel_with_provider()`
with real Thimble API calls. The rest of the app doesn't change.
"""
import json
import secrets
from datetime import datetime, timedelta
from flask import Blueprint, render_template, abort
from flask_login import login_required, current_user
from models import db, Job, JobSession, InsurancePolicy
from routes import role_required

insurance_bp = Blueprint('insurance', __name__)

MOCK_PROVIDER = 'mock'
DEFAULT_COVERAGE_AMOUNT = 10000.00  # $10,000 occupational accident coverage


# ============================================================
# PUBLIC API — called by other parts of the app.
# These function signatures stay stable when we swap to Thimble.
# ============================================================

def issue_policy(session):
    """
    Issue an insurance policy for a JobSession.
    Called when the work timer starts.

    Returns the InsurancePolicy object, or None if issuance failed.
    """
    job = session.job
    estimated_duration_hours = job.estimated_hours + 1  # buffer
    coverage_ends = datetime.utcnow() + timedelta(hours=estimated_duration_hours)

    # Allocate ~half of the platform fee to insurance premium (simulated)
    premium = round(job.platform_fee * 0.5, 2)

    provider_data = _issue_via_provider(
        job=job,
        session=session,
        coverage_amount=DEFAULT_COVERAGE_AMOUNT,
        coverage_starts=datetime.utcnow(),
        coverage_ends=coverage_ends,
        premium=premium,
    )

    policy = InsurancePolicy(
        job_id=job.id,
        session_id=session.id,
        provider=provider_data['provider'],
        certificate_id=provider_data['certificate_id'],
        coverage_type=provider_data['coverage_type'],
        coverage_amount=provider_data['coverage_amount'],
        premium_paid=premium,
        coverage_starts_at=provider_data['coverage_starts'],
        coverage_ends_at=provider_data['coverage_ends'],
        status='active',
        provider_response_json=json.dumps(provider_data),
    )
    db.session.add(policy)
    db.session.commit()
    return policy


def close_policy(policy, actual_end=None):
    """
    Mark a policy as expired (work completed normally).
    Called when the work timer ends.
    """
    if not policy:
        return
    policy.coverage_ends_at = actual_end or datetime.utcnow()
    policy.status = 'expired'
    _notify_provider_of_completion(policy)
    db.session.commit()


# ============================================================
# PROVIDER-SPECIFIC IMPLEMENTATION (mock for now)
# When we get Thimble API keys, replace these two functions.
# ============================================================

def _issue_via_provider(job, session, coverage_amount, coverage_starts, coverage_ends, premium):
    """
    MOCK: pretends to call an insurance API and returns a certificate.

    TODO(thimble): Replace with real Thimble API call, e.g.:
        response = requests.post(
            'https://api.thimble.com/v1/policies',
            headers={'Authorization': f'Bearer {THIMBLE_KEY}'},
            json={
                'coverage_type': 'occupational_accident',
                'coverage_amount': coverage_amount,
                'starts_at': coverage_starts.isoformat(),
                'ends_at': coverage_ends.isoformat(),
                'insured_name': job.assigned_teen.full_name,
                'location': job.homeowner.address,
                'job_description': job.title,
            },
        )
        data = response.json()
        return {
            'provider': 'thimble',
            'certificate_id': data['policy_number'],
            'coverage_type': data['coverage_type'],
            'coverage_amount': data['coverage_amount'],
            'coverage_starts': ...,
            'coverage_ends': ...,
            'certificate_url': data['certificate_pdf_url'],
        }
    """
    cert_id = f'TAW-MOCK-{secrets.token_hex(6).upper()}'
    return {
        'provider': MOCK_PROVIDER,
        'certificate_id': cert_id,
        'coverage_type': 'occupational_accident',
        'coverage_amount': coverage_amount,
        'coverage_starts': coverage_starts,
        'coverage_ends': coverage_ends,
        'premium': premium,
        'insured_name': job.assigned_teen.full_name if job.assigned_teen else 'Unknown',
        'job_title': job.title,
        'mock_note': 'This is a simulated certificate for development. Not legally binding.',
    }


def _notify_provider_of_completion(policy):
    """
    MOCK: would normally notify Thimble that the job is complete
    (which can affect billing for per-minute policies).

    TODO(thimble): POST to Thimble's policy-close endpoint.
    """
    pass


# ============================================================
# ROUTES
# ============================================================

@insurance_bp.route('/certificate/<certificate_id>')
@login_required
def view_certificate(certificate_id):
    """Display the insurance certificate. Visible to homeowner, assigned teen, and admin."""
    policy = InsurancePolicy.query.filter_by(certificate_id=certificate_id).first_or_404()
    job = policy.job

    if current_user.role != 'admin' and current_user.id not in (job.homeowner_id, job.assigned_teen_id):
        abort(403)

    return render_template('insurance/certificate.html', policy=policy, job=job)


@insurance_bp.route('/admin/policies')
@login_required
@role_required('admin')
def admin_list():
    """Admin view of all insurance policies."""
    policies = InsurancePolicy.query.order_by(InsurancePolicy.issued_at.desc()).all()
    return render_template('insurance/admin_list.html', policies=policies)
