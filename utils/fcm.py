import os
import logging
from firebase_admin import credentials, messaging, initialize_app, get_app, exceptions

logger = logging.getLogger(__name__)

# Initialize Firebase App
firebase_initialized = False

def init_firebase():
    global firebase_initialized
    if firebase_initialized:
        return True
    try:
        # Check if service account key exists in database or config
        base_dir = os.path.abspath(os.path.dirname(os.path.dirname(__file__)))
        cred_path = os.path.join(base_dir, 'database', 'firebase_credentials.json')
        if os.path.exists(cred_path):
            cred = credentials.Certificate(cred_path)
            initialize_app(cred)
            firebase_initialized = True
            logger.info("Firebase Admin initialized successfully with credentials.")
        else:
            # Fallback to mock mode if credentials not found
            # This allows the server to run without crash even if the user hasn't set up Firebase credentials yet!
            logger.warning(f"Firebase credentials not found at {cred_path}. Push notifications will be skipped.")
    except Exception as e:
        logger.exception("Failed to initialize Firebase Admin: %s", e)
    return firebase_initialized

def send_fcm_message(token, sender, title, content, is_group=False, target_name="", msg_id="", msg_type="text",
                     duration=None, file_name=None, reply_to=None, reply_content=None):
    """
    Sends a data-only FCM push notification to wake up the Android client.
    """
    if not init_firebase():
        return False
        
    try:
        fcm_data = {
            "sender": sender,
            "title": title,
            "content": content,
            "is_group": "true" if is_group else "false",
            "target_name": target_name,
            "msg_id": msg_id,
            "type": msg_type
        }
        if duration is not None:
            fcm_data["duration"] = str(duration)
        if file_name is not None:
            fcm_data["file_name"] = str(file_name)
        if reply_to is not None:
            fcm_data["reply_to"] = str(reply_to)
        if reply_content is not None:
            fcm_data["reply_content"] = str(reply_content)

        message = messaging.Message(
            data=fcm_data,
            token=token
        )
        response = messaging.send(message)
        logger.info(f"FCM message sent successfully: {response}")
        return True
    except exceptions.NotFoundError:
        logger.info(f"FCM token {token} is unregistered/expired. Clearing from database.")
        try:
            from models.models import db, User
            user = User.query.filter_by(fcm_token=token).first()
            if user:
                user.fcm_token = None
                db.session.commit()
        except Exception as db_err:
            logger.error(f"Failed to clear unregistered FCM token from DB: {db_err}")
        return False
    except Exception as e:
        logger.error(f"FCM sending failed for token {token}: {e}")
        return False
