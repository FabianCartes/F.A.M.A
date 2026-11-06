"""Read-only history of attributable local predictions for private imported models."""
from datetime import datetime, timezone
from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from pydantic import BaseModel, Field
from sqlalchemy import inspect
from sqlalchemy.orm import Session
from app.database import get_db
from app.models.dataset_import import ImportedDataset
from app.models.imported_training_source import ImportedModelSource
from app.models.prediction import Prediccion
from app.services.auth import security_bearer
from app.services.imported_identity import imported_user
from app.services.imported_feedback import imported_model_id
from app.services.local_prediction_audio import LocalPredictionAudio

router = APIRouter(prefix='/api/inference', tags=['Predicciones'])


class HistoryItem(BaseModel):
    id: int
    filename: str
    timestamp: datetime
    clase: str
    confianza: float = Field(ge=0, le=1)
    modelo_id: str


class HistoryPage(BaseModel):
    items: list[HistoryItem]
    next_cursor: int | None


@router.get('/history', response_model=HistoryPage,
    summary='Consultar el historial privado del modelo importado seleccionado',
    description='Solo referencias locales atribuibles a la sesión; sin audio ni rutas. '
                'Hasta 20 registros por página, orden de creación descendente. '
                'El cursor continúa el recorrido incluso si una página no contiene registros visibles.')
def prediction_history(request: Request, response: Response,
        model_id: str = Query(min_length=1, max_length=100),
        limit: int = Query(default=20, ge=1, le=20),
        cursor: int | None = Query(default=None, gt=0),
        credentials=Depends(security_bearer), db: Session = Depends(get_db)):
    user = imported_user(request, response, credentials, db)
    response.headers['Cache-Control'] = 'no-store'
    numeric = imported_model_id(model_id)
    source = (db.get(ImportedModelSource, numeric) if numeric
              and inspect(db.get_bind()).has_table('imported_model_source') else None)
    dataset = db.get(ImportedDataset, source.dataset_id) if source else None
    if (source is None or source.owner_id != user.id or dataset is None
            or dataset.owner_id != user.id):
        raise HTTPException(404, 'Modelo no disponible.')
    canonical = f'fama_trained_model_{numeric}'
    query = db.query(Prediccion).filter(
        Prediccion.modelo_id.in_([str(numeric), canonical]),
        Prediccion.dataset_name == 'imported:' + source.dataset_id,
        Prediccion.ruta_audio_prueba.startswith(f'local_predictions/{user.id}/'))
    if cursor is not None:
        query = query.filter(Prediccion.id_prediccion < cursor)
    # Bound metadata work. Invalid legacy references never exhaust memory or cause
    # audio I/O; the raw scan cursor allows the client to pass a sparse window.
    rows = query.order_by(Prediccion.id_prediccion.desc()).limit(200).all()
    items = []
    for row in rows:
        try:
            # This is the exact identity grammar used by the authenticated writer,
            # not a prefix/filename ownership heuristic. History does not read audio.
            LocalPredictionAudio._identity(user.id, row.ruta_audio_prueba)
        except ValueError:
            continue
        if len(items) == limit:
            return HistoryPage(items=items, next_cursor=items[-1].id)
        timestamp = row.fecha_prediccion
        if timestamp.tzinfo is None:
            timestamp = timestamp.replace(tzinfo=timezone.utc)
        items.append(HistoryItem(id=row.id_prediccion,
            filename=row.nombre_original or 'Archivo sin nombre', timestamp=timestamp,
            clase=row.etiqueta_predicha, confianza=row.confianza, modelo_id=canonical))
    return HistoryPage(items=items, next_cursor=rows[-1].id_prediccion if len(rows) == 200 else None)
