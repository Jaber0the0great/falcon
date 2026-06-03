from cryptography.fernet import Fernet

# The same key used in the desktop app
CHAT_KEY = b'v-9_2fGzS_L0N8oX5x6y_Kz_jZ1M9Wv8m_U3k_QWzY8='
CIPHER = Fernet(CHAT_KEY)

def encrypt_text(text):
    if not text:
        return text
    try:
        return CIPHER.encrypt(text.encode()).decode()
    except:
        return text

def decrypt_text(encrypted_text):
    if not encrypted_text:
        return encrypted_text
    try:
        return CIPHER.decrypt(encrypted_text.encode()).decode()
    except:
        return encrypted_text
