"""Local operator recovery of an existing administrator; never a web endpoint."""
from contextlib import contextmanager

from sqlalchemy import text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import ArgumentError

from app.database_connection import database_engine


class OperatorRecoveryError(ValueError):
    """A closed, sanitized operator result."""


@contextmanager
def _database(configuration):
    if configuration.installation_status != 'completed':
        raise OperatorRecoveryError('administrator_recovery_installation_not_completed')
    try:
        address = make_url(configuration.database_url)
        if (address.get_backend_name() != 'postgresql' or not address.database
                or set(address.query) - {'sslmode'}):
            raise ValueError
    except (ArgumentError, ValueError, TypeError):
        raise OperatorRecoveryError('administrator_recovery_configuration_invalid') from None
    from app.schema import check_schema
    if check_schema(configuration.database_url).code != 'schema_current':
        raise OperatorRecoveryError('administrator_recovery_schema_not_current')
    engine = database_engine(configuration.database_url)
    try:
        yield engine, address.database
    finally:
        engine.dispose()


def _user(connection, user_id):
    if type(user_id) is not int or not 1 <= user_id <= 2**31-1:
        raise OperatorRecoveryError('administrator_recovery_user_invalid')
    row = connection.execute(text('SELECT id_usuario,correo_electronico,rol,activo FROM usuario WHERE id_usuario=:id'),
                             {'id':user_id}).mappings().first()
    if row is None:
        raise OperatorRecoveryError('administrator_recovery_target_not_found')
    if row['rol'] != 'administrador':
        raise OperatorRecoveryError('administrator_recovery_administrator_required')
    return {'id':row['id_usuario'],'email':row['correo_electronico'],'rol':row['rol'],'activo':row['activo']}


def inspect_administrator(configuration, user_id=None, *, email=None):
    with _database(configuration) as (engine, name), engine.connect() as connection:
        connection.exec_driver_sql('SET TRANSACTION READ ONLY')
        if connection.scalar(text('SELECT current_database()')) != name:
            raise OperatorRecoveryError('administrator_recovery_configuration_invalid')
        if email is not None:
            normalized = email.strip().lower()
            if not normalized or len(normalized) > 150:
                raise OperatorRecoveryError('administrator_recovery_identity_invalid')
            identifiers = connection.execute(text('SELECT id_usuario FROM usuario '
                'WHERE lower(trim(correo_electronico))=:email LIMIT 2'),{'email':normalized}).scalars().all()
            if len(identifiers) > 1:
                raise OperatorRecoveryError('administrator_recovery_identity_ambiguous')
            if not identifiers:
                raise OperatorRecoveryError('administrator_recovery_target_not_found')
            user_id = identifiers[0]
        user = _user(connection, user_id)
        return {'code':'administrator_recovery_ready','database':name,'user':user,
                'reactivation_required':not user['activo']}


def recover_administrator(configuration, user_id, *, database, email, password, reactivate=False):
    if not isinstance(password, str) or not 12 <= len(password) <= 1024 or not password.strip():
        raise OperatorRecoveryError('administrator_recovery_password_invalid')
    password.encode('utf-8')
    from app.passwords import hash_password
    from sqlalchemy.orm import Session
    from app.services.accounts import lock_accounts, revoke_credentials
    from app.services.security_audit import record_event
    derived = hash_password(password)
    with _database(configuration) as (engine, name):
        if database != name:
            raise OperatorRecoveryError('administrator_recovery_database_confirmation_required')
        with Session(engine) as session, session.begin():
            if session.scalar(text('SELECT current_database()')) != name:
                raise OperatorRecoveryError('administrator_recovery_configuration_invalid')
            lock_accounts(session)
            user = _user(session, user_id)
            if not isinstance(email, str) or email.strip().lower() != user['email'].strip().lower():
                raise OperatorRecoveryError('administrator_recovery_identity_mismatch')
            if not user['activo'] and not reactivate:
                raise OperatorRecoveryError('administrator_recovery_reactivation_required')
            session.execute(text('UPDATE usuario SET hash_contrasena=:password,activo=true WHERE id_usuario=:id'),
                            {'password':derived,'id':user_id})
            revoke_credentials(session, user_id)
            if not user['activo']:
                record_event(session,'account.reactivated','success',subject_user_id=user_id)
            record_event(session,'account.operator_recovered','success',subject_user_id=user_id)
        return {'code':'administrator_recovered','database':name,'user_id':user_id,'reactivated':not user['activo']}
