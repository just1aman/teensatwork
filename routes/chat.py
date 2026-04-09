from flask import Blueprint, render_template, abort, request, jsonify
from flask_login import login_required, current_user
from flask_socketio import emit, join_room
from models import db, Conversation, Message
from routes import role_required

chat_bp = Blueprint('chat', __name__)


def register_socketio_events(socketio):
    @socketio.on('join')
    def handle_join(data):
        conversation_id = data.get('conversation_id')
        conv = Conversation.query.get(conversation_id)
        if not conv:
            return
        if current_user.id not in (conv.homeowner_id, conv.teen_id) and current_user.role != 'admin':
            return
        room = f'conversation_{conversation_id}'
        join_room(room)

    @socketio.on('send_message')
    def handle_send_message(data):
        conversation_id = data.get('conversation_id')
        body = data.get('body', '').strip()
        if not body or not conversation_id:
            return

        conv = Conversation.query.get(conversation_id)
        if not conv:
            return
        if current_user.id not in (conv.homeowner_id, conv.teen_id):
            return

        msg = Message(
            conversation_id=conversation_id,
            sender_id=current_user.id,
            body=body,
        )
        db.session.add(msg)
        db.session.commit()

        room = f'conversation_{conversation_id}'
        emit('new_message', {
            'id': msg.id,
            'sender_id': msg.sender_id,
            'sender_name': current_user.full_name,
            'body': msg.body,
            'created_at': msg.created_at.strftime('%I:%M %p'),
            'is_mine': False,
        }, room=room, include_self=False)

        # Send back to sender with is_mine=True
        emit('new_message', {
            'id': msg.id,
            'sender_id': msg.sender_id,
            'sender_name': current_user.full_name,
            'body': msg.body,
            'created_at': msg.created_at.strftime('%I:%M %p'),
            'is_mine': True,
        })


@chat_bp.route('/conversations')
@login_required
def conversations():
    if current_user.role == 'homeowner':
        convs = Conversation.query.filter_by(homeowner_id=current_user.id).order_by(
            Conversation.created_at.desc()).all()
    elif current_user.role == 'teen':
        convs = Conversation.query.filter_by(teen_id=current_user.id).order_by(
            Conversation.created_at.desc()).all()
    elif current_user.role == 'admin':
        convs = Conversation.query.order_by(Conversation.created_at.desc()).all()
    else:
        convs = []
    return render_template('chat/conversations.html', conversations=convs)


@chat_bp.route('/<int:conversation_id>')
@login_required
def conversation(conversation_id):
    conv = Conversation.query.get_or_404(conversation_id)
    if current_user.id not in (conv.homeowner_id, conv.teen_id) and current_user.role != 'admin':
        abort(403)

    messages = Message.query.filter_by(conversation_id=conversation_id).order_by(
        Message.created_at.asc()).all()
    return render_template('chat/conversation.html', conversation=conv, messages=messages)
