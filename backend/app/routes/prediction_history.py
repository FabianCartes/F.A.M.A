"""Read-only history of dataset-authorized predictions."""
from datetime import datetime, timezone
from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session
from app.database import get_db
from app.models.prediction import Prediccion
from app.models.prediction_access import AccesoPrediccion
from app.models.training import Modelo
from app.services.registry import get_model_registry
from app.services.access import ResourceAccess, resource_access
from app.services.triad_compositions import composition_query, parse_triad_key, triad_model_key
from app.routes.auth import WebAuthRoute
from app.services.local_prediction_audio import LocalPredictionAudio

router = APIRouter(prefix='/api/inference', tags=['Predicciones'], route_class=WebAuthRoute)


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
    summary='Consultar el historial del modelo seleccionado',
    description='Solo predicciones del dataset asignado; sin audio ni rutas. '
                'Hasta 20 registros por página, orden de creación descendente. '
                'El cursor continúa el recorrido incluso si una página no contiene registros visibles.')
def prediction_history(request: Request, response: Response,
        model_id: str = Query(min_length=1, max_length=100),
        limit: int = Query(default=20, ge=1, le=20),
        cursor: int | None = Query(default=None, gt=0),
        db: Session = Depends(get_db),
        access: ResourceAccess = Depends(resource_access),
        registry=Depends(get_model_registry)):
    response.headers['Cache-Control'] = 'no-store'
    prefix = 'fama_trained_model_'
    numeric = model_id[len(prefix):] if model_id.startswith(prefix) else model_id
    canonical = model_id
    if model_id.startswith(prefix) or numeric.isascii() and numeric.isdecimal():
        if (not numeric.isascii() or not numeric.isdecimal() or len(numeric) > 10
                or not 1 <= int(numeric) <= 2 ** 31 - 1):
            raise HTTPException(404, 'Modelo no disponible.')
        model = access.query(Modelo).filter_by(id_modelo=int(numeric)).first()
        if model is None or model.conjunto_datos is None:
            raise HTTPException(404, 'Modelo no disponible.')
        canonical = f'fama_trained_model_{model.id_modelo}'
    from app.models.dataset import ConjuntoDatos
    triad_id = parse_triad_key(model_id)
    if triad_id is not None:
        # Every stored version keeps its own history, even when it is no longer published.
        composition = composition_query(access).filter_by(id=triad_id).first()
        dataset = db.get(ConjuntoDatos, composition.dataset_id) if composition is not None else None
        if dataset is None:
            raise HTTPException(404, 'Modelo no disponible.')
        canonical = triad_model_key(triad_id)
    else:
        metadata = next((item for item in registry.list_models() if item.id == canonical), None)
        if metadata is None or not metadata.dataset_name or not access.model_allowed(canonical, metadata.dataset_name):
            raise HTTPException(404, 'Modelo no disponible.')
        dataset = db.query(ConjuntoDatos).filter_by(nombre=metadata.dataset_name).first()
        if dataset is None or dataset.nombre != metadata.dataset_name:
            raise HTTPException(404, 'Modelo no disponible.')
    query = (access.query(Prediccion)
             .join(AccesoPrediccion, AccesoPrediccion.id_prediccion == Prediccion.id_prediccion)
             .add_entity(AccesoPrediccion)
             .filter(Prediccion.modelo_id == canonical,
                     Prediccion.dataset_name == dataset.nombre,
                     AccesoPrediccion.id_conjunto_datos == dataset.id_conjunto_datos))
    if cursor is not None:
        query = query.filter(Prediccion.id_prediccion < cursor)
    # Bound metadata work. Invalid legacy references never exhaust memory or cause
    # audio I/O; the raw scan cursor allows the client to pass a sparse window.
    rows = query.order_by(Prediccion.id_prediccion.desc()).limit(200).all()
    items = []
    for row, origin in rows:
        try:
            # The persisted origin identifies the writer; access is dataset-scoped.
            if row.ruta_audio_prueba.startswith('local_predictions/'):
                LocalPredictionAudio._identity(origin.id_usuario, row.ruta_audio_prueba)
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
    return HistoryPage(items=items, next_cursor=rows[-1][0].id_prediccion if len(rows) == 200 else None)
