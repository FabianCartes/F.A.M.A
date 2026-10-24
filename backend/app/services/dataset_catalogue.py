"""Metadata discovery and transactional requests; never opens files or cloud clients."""
import time
from fastapi import HTTPException
from sqlalchemy import and_
from app.models.dataset import ConjuntoDatos
from app.models.dataset_access import AsignacionDataset
from app.models.dataset_request import SolicitudDataset
from app.models.user import Usuario
from app.services.security_audit import record_event


def catalogue(db, user, limit, offset):
    rows = (db.query(ConjuntoDatos, AsignacionDataset.id_usuario, SolicitudDataset.status)
            .outerjoin(AsignacionDataset, and_(AsignacionDataset.id_conjunto_datos == ConjuntoDatos.id_conjunto_datos,
                                              AsignacionDataset.id_usuario == user.id))
            .outerjoin(SolicitudDataset, and_(SolicitudDataset.id_conjunto_datos == ConjuntoDatos.id_conjunto_datos,
                                             SolicitudDataset.id_usuario == user.id))
            .order_by(ConjuntoDatos.id_conjunto_datos).offset(offset).limit(limit).all())
    return dict(datasets=[dict(dataset_id=ds.id_conjunto_datos, name=ds.nombre,
                               audio_count=ds.cantidad_audios, size_bytes=ds.tamano_total_bytes,
                               purpose=ds.finalidad, assigned=user.rol == "administrador" or granted is not None,
                               request_status=request_status) for ds, granted, request_status in rows],
                total=db.query(ConjuntoDatos).count(), limit=limit, offset=offset)


def request_access(db, user, dataset_id):
    if db.get(ConjuntoDatos, dataset_id) is None:
        raise HTTPException(404, "Dataset no encontrado.")
    if user.rol == "administrador" or db.get(AsignacionDataset, (user.id, dataset_id)):
        raise HTTPException(409, "Ya tienes acceso a este dataset.")
    row = db.get(SolicitudDataset, (user.id, dataset_id))
    if row is None:
        row = SolicitudDataset(id_usuario=user.id, id_conjunto_datos=dataset_id)
        db.add(row)
    if row.status != "pending":
        row.status = "pending"
        row.requested_at = int(time.time())
        row.decided_at = row.decided_by = None
        record_event(db, "dataset.requested", "success", actor_id=user.id, dataset_id=dataset_id)
    db.commit()
    return dict(user_id=user.id, dataset_id=dataset_id, status=row.status)


def requests_inbox(db, limit, offset, state):
    query = db.query(SolicitudDataset, Usuario.nombre_completo, ConjuntoDatos.nombre).join(
        Usuario, Usuario.id == SolicitudDataset.id_usuario).join(
        ConjuntoDatos, ConjuntoDatos.id_conjunto_datos == SolicitudDataset.id_conjunto_datos)
    if state != "all":
        query = query.filter(SolicitudDataset.status == state)
    total = query.count()
    rows = query.order_by(SolicitudDataset.requested_at, SolicitudDataset.id_usuario,
                          SolicitudDataset.id_conjunto_datos).offset(offset).limit(limit).all()
    return dict(requests=[dict(user_id=r.id_usuario, dataset_id=r.id_conjunto_datos,
                               user_name=user_name, dataset_name=dataset_name, status=r.status,
                               requested_at=r.requested_at, decided_at=r.decided_at,
                               decided_by=r.decided_by) for r, user_name, dataset_name in rows],
                total=total, limit=limit, offset=offset)


def decide_request(db, actor, user_id, dataset_id, decision):
    row = db.get(SolicitudDataset, (user_id, dataset_id))
    if row is None:
        raise HTTPException(404, "Solicitud no encontrada.")
    target = "approved" if decision == "approve" else "rejected"
    if row.status != "pending":
        if row.status != target:
            raise HTTPException(409, "Esta solicitud ya tiene otra decisión. Actualiza la bandeja.")
        return dict(user_id=user_id, dataset_id=dataset_id, status=row.status,
                    assigned=db.get(AsignacionDataset, (user_id, dataset_id)) is not None)
    user = db.get(Usuario, user_id)
    if decision == "approve":
        if user is None or not user.activo:
            raise HTTPException(409, "La cuenta debe estar activa para conceder acceso.")
        if db.get(AsignacionDataset, (user_id, dataset_id)) is None:
            db.add(AsignacionDataset(id_usuario=user_id, id_conjunto_datos=dataset_id))
            record_event(db, "assignment.granted", "success", actor_id=actor.id,
                         subject_user_id=user_id, dataset_id=dataset_id)
    row.status, row.decided_at, row.decided_by = target, int(time.time()), actor.id
    record_event(db, "dataset.request_approved" if decision == "approve" else "dataset.request_rejected",
                 "success", actor_id=actor.id, subject_user_id=user_id, dataset_id=dataset_id)
    db.commit()
    return dict(user_id=user_id, dataset_id=dataset_id, status=row.status,
                assigned=db.get(AsignacionDataset, (user_id, dataset_id)) is not None)
