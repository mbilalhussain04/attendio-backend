import pyotp
import secrets
from sqlalchemy.orm import Session
from app.models.user import User
from app.core.exceptions import bad_request
from app.core.security import token_hash


def generate_setup(db: Session, user: User):
    secret = pyotp.random_base32()
    user.mfa_secret = secret
    db.add(user)
    db.commit()
    provisioning_uri = pyotp.TOTP(secret).provisioning_uri(name=user.email, issuer_name='Attendio')
    return {'secret': secret, 'provisioning_uri': provisioning_uri}


def verify_setup(db: Session, user: User, token: str):
    if not user.mfa_secret:
        bad_request('MFA setup not started')
    ok = pyotp.TOTP(user.mfa_secret).verify(token, valid_window=1)
    if not ok:
        bad_request('Invalid MFA token')
    user.mfa_enabled = True
    codes = generate_recovery_codes()
    metadata = dict(user.metadata_json or {})
    metadata['mfa_recovery_code_hashes'] = [token_hash(code) for code in codes]
    user.metadata_json = metadata
    db.add(user)
    db.commit()
    return codes


def generate_recovery_codes() -> list[str]:
    alphabet = 'ABCDEFGHJKLMNPQRSTUVWXYZ23456789'
    return [''.join(secrets.choice(alphabet) for _ in range(4)) + '-' + ''.join(secrets.choice(alphabet) for _ in range(4)) for _ in range(10)]


def regenerate_recovery_codes(db: Session, user: User, token: str) -> list[str]:
    verify_login(db, user, token)
    codes = generate_recovery_codes()
    metadata = dict(user.metadata_json or {})
    metadata['mfa_recovery_code_hashes'] = [token_hash(code) for code in codes]
    user.metadata_json = metadata
    db.add(user)
    db.commit()
    return codes


def disable(db: Session, user: User):
    user.mfa_enabled = False
    user.mfa_secret = None
    metadata = dict(user.metadata_json or {})
    metadata.pop('mfa_recovery_code_hashes', None)
    user.metadata_json = metadata
    db.add(user)
    db.commit()


def verify_login(db: Session, user: User, token: str):
    if not user.mfa_secret:
        bad_request('MFA not configured')
    ok = pyotp.TOTP(user.mfa_secret).verify(token, valid_window=1)
    if ok:
        return True
    metadata = dict(user.metadata_json or {})
    hashes = list(metadata.get('mfa_recovery_code_hashes') or [])
    candidate = token_hash(token.strip().upper())
    if candidate in hashes:
        hashes.remove(candidate)
        metadata['mfa_recovery_code_hashes'] = hashes
        user.metadata_json = metadata
        db.add(user)
        db.commit()
        return True
    bad_request('Invalid MFA token')
