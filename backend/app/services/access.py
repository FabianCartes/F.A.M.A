"""One request's verified resource grants; absent association never means access."""
from fastapi import Depends, HTTPException
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.dataset import ConjuntoDatos
from app.models.dataset_access import AsignacionDataset
from app.models.user import Usuario
from app.models.dataset import Audio
from app.models.training import Modelo
from app.models.prediction import Prediccion
from app.models.prediction_access import AccesoPrediccion
from app.models.feedback import Retroalimentacion
from app.services.web_sessions import current_web_user


class ResourceAccess:
    def __init__(self, db: Session, user: Usuario):
        self.db = db
        self.user = user
        self.administrator = user.rol == "administrador"
        self.datasets = None if self.administrator else (
            db.query(ConjuntoDatos).join(AsignacionDataset,
                AsignacionDataset.id_conjunto_datos == ConjuntoDatos.id_conjunto_datos)
            .filter(AsignacionDataset.id_usuario == user.id).all())

    @property
    def names(self):
        return None if self.datasets is None else {row.nombre for row in self.datasets}

    @property
    def ids(self):
        return None if self.datasets is None else {row.id_conjunto_datos for row in self.datasets}

    def require_dataset(self, name):
        if not self.administrator and (name is None or name not in self.names):
            raise HTTPException(404, "Recurso no encontrado o no asignado.")

    def require_administrator(self):
        if not self.administrator:
            raise HTTPException(403, "Se requiere un administrador.")

    def model_allowed(self, model_id, dataset_name):
        if self.administrator:
            return True
        if dataset_name not in self.names:
            return False
        prefix = "fama_trained_model_"
        if model_id.startswith(prefix):
            identifier = model_id[len(prefix):]
            if (not identifier.isascii() or not identifier.isdecimal() or len(identifier) > 10
                    or not 1 <= int(identifier) <= 2 ** 31 - 1):
                return False
            row = self.query(Modelo).filter_by(id_modelo=int(identifier)).first()
            return row is not None and row.conjunto_datos.nombre == dataset_name
        return True  # Explicitly registered adapters declare their canonical dataset.

    def query(self, model):
        query = self.db.query(model)
        if self.administrator:
            return query
        if model is ConjuntoDatos:
            return query.filter(ConjuntoDatos.id_conjunto_datos.in_(self.ids))
        if model in (Audio, Modelo):
            return query.filter(model.id_conjunto_datos.in_(self.ids))
        if model is Prediccion:
            return query.filter(Prediccion.id_prediccion.in_(self.prediction_ids()))
        if model is Retroalimentacion:
            return query.filter(Retroalimentacion.id_prediccion.in_(self.prediction_ids()))
        raise ValueError("Unsupported resource query")

    def prediction_ids(self):
        return self.db.query(AccesoPrediccion.id_prediccion).filter(
            AccesoPrediccion.id_conjunto_datos.in_(self.ids or set()))

    def require_prediction(self, prediction_id):
        # Serialize feedback admission on the prediction, including the first feedback.
        row = self.query(Prediccion).filter_by(id_prediccion=prediction_id).with_for_update().first()
        if row is None:
            raise HTTPException(404, "Recurso no encontrado o no asignado.")
        return row

    def require_feedback(self, feedback_id):
        row = self.query(Retroalimentacion).filter_by(id_retroalimentacion=feedback_id).first()
        if row is None:
            raise HTTPException(404, "Recurso no encontrado o no asignado.")
        return row

    def record_prediction_origin(self, prediction):
        matches = self.db.query(ConjuntoDatos).filter_by(nombre=prediction.dataset_name).all()
        matches = [row for row in matches if row.nombre == prediction.dataset_name]
        if len(matches) == 1:
            self.db.flush()
            self.db.add(AccesoPrediccion(id_prediccion=prediction.id_prediccion,
                                        id_conjunto_datos=matches[0].id_conjunto_datos,
                                        id_usuario=self.user.id))


def resource_access(db: Session = Depends(get_db), user: Usuario = Depends(current_web_user)):
    return ResourceAccess(db, user)
