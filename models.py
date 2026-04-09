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
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    assigned_teen = db.relationship('User', foreign_keys=[assigned_teen_id])
    interests = db.relationship('JobInterest', backref='job', lazy=True)

    @property
    def estimated_total(self):
        return self.hourly_rate * self.estimated_hours

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


class Message(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    conversation_id = db.Column(db.Integer, db.ForeignKey('conversation.id'), nullable=False)
    sender_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    body = db.Column(db.Text, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    sender = db.relationship('User', foreign_keys=[sender_id])
