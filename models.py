import secrets
from datetime import datetime
from flask_sqlalchemy import SQLAlchemy
from flask_login import UserMixin

db = SQLAlchemy()

JOB_CATEGORIES = [
    ('grass_cutting', 'Grass Cutting'),
    ('snow_removal', 'Snow Removal'),
    ('pet_care', 'Pet Care'),
    ('babysitting', 'Babysitting'),
    ('mulching', 'Mulching'),
    ('gardening', 'Gardening'),
    ('car_washing', 'Car Washing'),
    ('house_cleaning', 'House Cleaning'),
    ('other', 'Other'),
]


class User(db.Model, UserMixin):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=False)
    password_hash = db.Column(db.String(256), nullable=True)  # nullable for Google OAuth users
    role = db.Column(db.String(20), nullable=True)  # 'homeowner', 'teen', 'admin' — null until profile completed
    google_id = db.Column(db.String(256), unique=True, nullable=True)
    is_approved = db.Column(db.Boolean, default=False)
    is_rejected = db.Column(db.Boolean, default=False)
    background_check_status = db.Column(db.String(20), nullable=True)  # none, pending, clear, consider, suspended
    full_name = db.Column(db.String(120), nullable=False)
    phone = db.Column(db.String(20), nullable=True)
    address = db.Column(db.String(200), nullable=True)  # homeowners
    age = db.Column(db.Integer, nullable=True)  # teens (13-19)
    parent_name = db.Column(db.String(120), nullable=True)  # teens
    parent_phone = db.Column(db.String(20), nullable=True)  # teens
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    jobs = db.relationship('Job', backref='homeowner', lazy=True,
                           foreign_keys='Job.homeowner_id')
    interests = db.relationship('JobInterest', backref='teen', lazy=True,
                                foreign_keys='JobInterest.teen_id')


class BackgroundCheck(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)

    # Provider info
    provider = db.Column(db.String(20), default='mock')  # 'mock' or 'checkr'
    provider_candidate_id = db.Column(db.String(200), nullable=True)  # Checkr candidate ID
    provider_report_id = db.Column(db.String(200), nullable=True)  # Checkr report ID
    provider_invitation_id = db.Column(db.String(200), nullable=True)  # Checkr invitation ID

    # What was checked
    check_type = db.Column(db.String(50), default='criminal')  # criminal, identity, sex_offender
    package = db.Column(db.String(50), default='tasker_standard')  # Checkr package name

    # Results
    status = db.Column(db.String(20), default='pending')  # pending, complete, error
    result = db.Column(db.String(20), nullable=True)  # clear, consider, suspended
    result_details = db.Column(db.Text, nullable=True)  # JSON of detailed findings

    # Payment for the check
    stripe_payment_intent_id = db.Column(db.String(200), nullable=True)
    amount_paid = db.Column(db.Integer, default=0)  # cents

    # Timestamps
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    completed_at = db.Column(db.DateTime, nullable=True)

    user = db.relationship('User', backref='background_checks')


class Job(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    homeowner_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    title = db.Column(db.String(200), nullable=False)
    category = db.Column(db.String(50), nullable=False)
    description = db.Column(db.Text, nullable=False)
    hourly_rate = db.Column(db.Float, nullable=False)
    estimated_hours = db.Column(db.Float, nullable=False)
    status = db.Column(db.String(20), default='open')  # open, assigned, completed, cancelled
    assigned_teen_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=True)
    scheduled_start = db.Column(db.DateTime, nullable=True)  # when the job is scheduled to begin
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    cancelled_at = db.Column(db.DateTime, nullable=True)
    cancellation_reason = db.Column(db.String(200), nullable=True)
    cancellation_fee = db.Column(db.Float, nullable=True)  # 10% of total if within 24hr, else 0
    refund_amount = db.Column(db.Float, nullable=True)  # amount refunded to homeowner (simulated)

    assigned_teen = db.relationship('User', foreign_keys=[assigned_teen_id])
    interests = db.relationship('JobInterest', backref='job', lazy=True)

    @property
    def estimated_total(self):
        return self.hourly_rate * self.estimated_hours

    @property
    def platform_fee(self):
        return self.estimated_total * 0.10  # 10% platform/insurance fee

    @property
    def total_with_fee(self):
        return self.estimated_total + self.platform_fee

    @property
    def hours_until_start(self):
        if not self.scheduled_start:
            return None
        delta = self.scheduled_start - datetime.utcnow()
        return delta.total_seconds() / 3600

    @property
    def can_cancel_free(self):
        hours = self.hours_until_start
        return hours is not None and hours > 24

    @property
    def category_display(self):
        for value, label in JOB_CATEGORIES:
            if value == self.category:
                return label
        return self.category


class JobInterest(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    job_id = db.Column(db.Integer, db.ForeignKey('job.id'), nullable=False)
    teen_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    message = db.Column(db.Text, nullable=True)
    status = db.Column(db.String(20), default='pending')  # pending, accepted, rejected
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    __table_args__ = (db.UniqueConstraint('job_id', 'teen_id'),)


class Conversation(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    homeowner_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    teen_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    job_id = db.Column(db.Integer, db.ForeignKey('job.id'), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    homeowner = db.relationship('User', foreign_keys=[homeowner_id])
    teen = db.relationship('User', foreign_keys=[teen_id])
    job = db.relationship('Job')
    messages = db.relationship('Message', backref='conversation', lazy=True,
                               order_by='Message.created_at')


class JobSession(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    job_id = db.Column(db.Integer, db.ForeignKey('job.id'), nullable=False, unique=True)
    token = db.Column(db.String(64), unique=True, nullable=False,
                      default=lambda: secrets.token_urlsafe(32))

    # Timestamps
    started_at = db.Column(db.DateTime, nullable=True)
    ended_at = db.Column(db.DateTime, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    # Scan verification (homeowner scans QR shown by teen)
    start_scan_by_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=True)
    end_scan_by_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=True)

    # Final reconciliation
    actual_hours = db.Column(db.Float, nullable=True)
    final_amount = db.Column(db.Float, nullable=True)  # actual_hours * hourly_rate

    status = db.Column(db.String(20), default='pending')  # pending, in_progress, completed

    job = db.relationship('Job', backref=db.backref('session', uselist=False))

    @property
    def elapsed_seconds(self):
        if not self.started_at:
            return 0
        end = self.ended_at or datetime.utcnow()
        return (end - self.started_at).total_seconds()

    @property
    def elapsed_hours(self):
        return self.elapsed_seconds / 3600


class InsurancePolicy(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    job_id = db.Column(db.Integer, db.ForeignKey('job.id'), nullable=False)
    session_id = db.Column(db.Integer, db.ForeignKey('job_session.id'), nullable=False)

    # Provider info — in production, this would be Thimble data
    provider = db.Column(db.String(50), default='mock')  # 'mock' now, 'thimble' later
    certificate_id = db.Column(db.String(100), unique=True, nullable=False)

    # Coverage
    coverage_type = db.Column(db.String(50), default='occupational_accident')
    coverage_amount = db.Column(db.Float, default=10000.00)  # $10k default
    premium_paid = db.Column(db.Float, default=0.0)  # portion of 10% fee allocated to insurance

    # Lifecycle
    issued_at = db.Column(db.DateTime, default=datetime.utcnow)
    coverage_starts_at = db.Column(db.DateTime, nullable=False)
    coverage_ends_at = db.Column(db.DateTime, nullable=True)

    # Status: active, expired, cancelled, claim_filed
    status = db.Column(db.String(20), default='active')

    # Raw response for debugging / audit (in production: real Thimble response)
    provider_response_json = db.Column(db.Text, nullable=True)

    job = db.relationship('Job', backref='insurance_policies')
    session = db.relationship('JobSession', backref='insurance_policies')


class Payment(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    job_id = db.Column(db.Integer, db.ForeignKey('job.id'), nullable=False)
    homeowner_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    teen_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=True)

    # Amounts in cents (Stripe convention)
    amount_total = db.Column(db.Integer, nullable=False)  # job cost + 10% fee
    amount_job = db.Column(db.Integer, nullable=False)    # base job cost
    amount_fee = db.Column(db.Integer, nullable=False)    # 10% platform/insurance fee
    amount_refunded = db.Column(db.Integer, default=0)    # cumulative refunded
    amount_payout = db.Column(db.Integer, default=0)      # paid out to teen (simulated in Phase B)

    # Stripe IDs
    stripe_checkout_session_id = db.Column(db.String(200), nullable=True)
    stripe_payment_intent_id = db.Column(db.String(200), nullable=True)
    stripe_charge_id = db.Column(db.String(200), nullable=True)
    stripe_refund_id = db.Column(db.String(200), nullable=True)

    # Status: pending (checkout created), paid (captured), refunded, partial_refund, failed
    status = db.Column(db.String(30), default='pending')

    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    paid_at = db.Column(db.DateTime, nullable=True)
    refunded_at = db.Column(db.DateTime, nullable=True)

    job = db.relationship('Job', backref='payments')
    homeowner = db.relationship('User', foreign_keys=[homeowner_id])
    teen = db.relationship('User', foreign_keys=[teen_id])


class Message(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    conversation_id = db.Column(db.Integer, db.ForeignKey('conversation.id'), nullable=False)
    sender_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    body = db.Column(db.Text, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    sender = db.relationship('User', foreign_keys=[sender_id])
