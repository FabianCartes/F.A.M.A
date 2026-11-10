"""Esquema congelado de las revisiones 0001/0002. No importar modelos del ORM."""
import sqlalchemy as sa

metadata = sa.MetaData()

sa.Table('conjunto_datos', metadata,
    sa.Column('id_conjunto_datos', sa.Integer(), nullable=False, primary_key=True, autoincrement=True),
    sa.Column('nombre', sa.String(length=100), nullable=False),
    sa.Column('ruta_gcp', sa.String(length=500), nullable=False),
    sa.Column('estado', sa.String(length=50), nullable=False),
    sa.Column('id_usuario_carga', sa.Integer(), nullable=True),
    sa.Column('fecha_carga', sa.DateTime(timezone=True), nullable=False),
    sa.Column('tamano_total_bytes', sa.BigInteger(), nullable=False),
    sa.Column('cantidad_audios', sa.Integer(), nullable=False),
    sa.Column('finalidad', sa.Text(), nullable=False),
    sa.Column('base_licitud', sa.String(length=50), nullable=False),
)
sa.Index('ix_conjunto_datos_id_conjunto_datos', metadata.tables['conjunto_datos'].c['id_conjunto_datos'], unique=False)
sa.Index('ix_conjunto_datos_nombre', metadata.tables['conjunto_datos'].c['nombre'], unique=True)

sa.Table('control_cuentas', metadata,
    sa.Column('id', sa.Integer(), nullable=False, primary_key=True),
    sa.CheckConstraint('id = 1', name='chk_control_cuentas_unico'),
)

sa.Table('cuota_acceso', metadata,
    sa.Column('clave_hash', sa.String(length=64), nullable=False, primary_key=True),
    sa.Column('intentos', sa.Integer(), nullable=False),
    sa.Column('expira_en', sa.BigInteger(), nullable=False),
    sa.CheckConstraint('intentos > 0', name='chk_cuota_intentos_positivos'),
)
sa.Index('ix_cuota_acceso_expira_en', metadata.tables['cuota_acceso'].c['expira_en'], unique=False)

sa.Table('evento_seguridad', metadata,
    sa.Column('id', sa.BigInteger().with_variant(sa.Integer(), 'sqlite'), nullable=False, primary_key=True, autoincrement=True),
    sa.Column('occurred_at', sa.BigInteger(), nullable=False),
    sa.Column('action', sa.String(length=48), nullable=False),
    sa.Column('outcome', sa.String(length=12), nullable=False),
    sa.Column('actor_id', sa.Integer(), nullable=True),
    sa.Column('subject_user_id', sa.Integer(), nullable=True),
    sa.Column('dataset_id', sa.Integer(), nullable=True),
    sa.CheckConstraint("outcome IN ('success', 'denied')", name='chk_evento_resultado'),
    sqlite_autoincrement=True,
)
sa.Index('ix_evento_retencion', metadata.tables['evento_seguridad'].c['occurred_at'], metadata.tables['evento_seguridad'].c['id'], unique=False)

sa.Table('prediccion', metadata,
    sa.Column('id_prediccion', sa.Integer(), nullable=False, primary_key=True, autoincrement=True),
    sa.Column('ruta_audio_prueba', sa.String(length=255), nullable=False),
    sa.Column('etiqueta_predicha', sa.String(length=100), nullable=False),
    sa.Column('confianza', sa.Float(), nullable=False),
    sa.Column('modelo_id', sa.String(length=100), nullable=True),
    sa.Column('dataset_name', sa.String(length=100), nullable=True),
    sa.Column('nombre_original', sa.String(length=255), nullable=True),
    sa.Column('fecha_carga', sa.DateTime(timezone=True), nullable=True),
    sa.Column('fecha_prediccion', sa.DateTime(timezone=True), nullable=False),
)
sa.Index('ix_prediccion_id_prediccion', metadata.tables['prediccion'].c['id_prediccion'], unique=False)

sa.Table('usuario', metadata,
    sa.Column('id_usuario', sa.Integer(), nullable=False, primary_key=True, autoincrement=True),
    sa.Column('correo_electronico', sa.String(length=150), nullable=False),
    sa.Column('hash_contrasena', sa.String(length=255), nullable=False),
    sa.Column('rol', sa.String(length=50), nullable=False),
    sa.Column('nombre_completo', sa.String(length=150), nullable=False),
    sa.Column('activo', sa.Boolean(), nullable=False),
    sa.Column('fecha_creacion', sa.DateTime(timezone=True), nullable=False),
    sa.Column('ultimo_acceso', sa.DateTime(timezone=True), nullable=True),
    sa.CheckConstraint("rol IN ('administrador', 'investigador')", name='chk_usuario_rol'),
)
sa.Index('ix_usuario_correo_electronico', metadata.tables['usuario'].c['correo_electronico'], unique=True)
sa.Index('ix_usuario_id_usuario', metadata.tables['usuario'].c['id_usuario'], unique=False)

sa.Table('acceso_prediccion', metadata,
    sa.Column('id_prediccion', sa.Integer(), nullable=False, primary_key=True),
    sa.Column('id_conjunto_datos', sa.Integer(), nullable=False),
    sa.Column('id_usuario', sa.Integer(), nullable=False),
    sa.ForeignKeyConstraint(['id_usuario'], ['usuario.id_usuario'], name=None, ondelete=None),
    sa.ForeignKeyConstraint(['id_conjunto_datos'], ['conjunto_datos.id_conjunto_datos'], name=None, ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['id_prediccion'], ['prediccion.id_prediccion'], name=None, ondelete='CASCADE'),
)
sa.Index('ix_acceso_prediccion_id_conjunto_datos', metadata.tables['acceso_prediccion'].c['id_conjunto_datos'], unique=False)

sa.Table('asignacion_dataset', metadata,
    sa.Column('id_usuario', sa.Integer(), nullable=False, primary_key=True),
    sa.Column('id_conjunto_datos', sa.Integer(), nullable=False, primary_key=True),
    sa.ForeignKeyConstraint(['id_usuario'], ['usuario.id_usuario'], name=None, ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['id_conjunto_datos'], ['conjunto_datos.id_conjunto_datos'], name=None, ondelete='CASCADE'),
)
sa.Index('ix_asignacion_dataset_id_conjunto_datos', metadata.tables['asignacion_dataset'].c['id_conjunto_datos'], unique=False)

sa.Table('audio', metadata,
    sa.Column('id_audio', sa.Integer(), nullable=False, primary_key=True, autoincrement=True),
    sa.Column('id_conjunto_datos', sa.Integer(), nullable=False),
    sa.Column('nombre_archivo', sa.String(length=255), nullable=False),
    sa.Column('ruta_gcp', sa.String(length=500), nullable=False),
    sa.Column('clase', sa.String(length=100), nullable=False),
    sa.Column('frecuencia_muestreo', sa.Integer(), nullable=True),
    sa.Column('duracion_segundos', sa.Float(), nullable=True),
    sa.Column('tamano_bytes', sa.BigInteger(), nullable=False),
    sa.Column('hash_archivo', sa.String(length=64), nullable=True),
    sa.Column('fecha_subida', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['id_conjunto_datos'], ['conjunto_datos.id_conjunto_datos'], name=None, ondelete='CASCADE'),
)
sa.Index('ix_audio_clase', metadata.tables['audio'].c['clase'], unique=False)
sa.Index('ix_audio_id_audio', metadata.tables['audio'].c['id_audio'], unique=False)
sa.Index('ix_audio_id_conjunto_datos', metadata.tables['audio'].c['id_conjunto_datos'], unique=False)

sa.Table('modelo', metadata,
    sa.Column('id_modelo', sa.Integer(), nullable=False, primary_key=True, autoincrement=True),
    sa.Column('id_usuario', sa.Integer(), nullable=True),
    sa.Column('id_conjunto_datos', sa.Integer(), nullable=True),
    sa.Column('clase_objetivo', sa.String(length=100), nullable=False),
    sa.Column('actualizacion_de', sa.Integer(), nullable=True),
    sa.Column('arquitectura', sa.String(length=255), nullable=False),
    sa.Column('epocas', sa.Integer(), nullable=False),
    sa.Column('tasa_aprendizaje', sa.Float(), nullable=False),
    sa.Column('tamano_lote', sa.Integer(), nullable=False),
    sa.Column('precision', sa.Float(), nullable=True),
    sa.Column('perdida', sa.Float(), nullable=True),
    sa.Column('ruta_binario_gcp', sa.String(length=500), nullable=False),
    sa.Column('tamano_bytes', sa.BigInteger(), nullable=False),
    sa.Column('hash_binario', sa.String(length=64), nullable=True),
    sa.Column('activo', sa.Boolean(), nullable=False),
    sa.Column('estado', sa.String(length=50), nullable=False),
    sa.Column('fecha_entrenamiento', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['actualizacion_de'], ['modelo.id_modelo'], name=None, ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['id_conjunto_datos'], ['conjunto_datos.id_conjunto_datos'], name=None, ondelete='SET NULL'),
)
sa.Index('ix_modelo_id_conjunto_datos', metadata.tables['modelo'].c['id_conjunto_datos'], unique=False)
sa.Index('ix_modelo_id_modelo', metadata.tables['modelo'].c['id_modelo'], unique=False)

sa.Table('recuperacion_cuenta', metadata,
    sa.Column('id_usuario', sa.Integer(), nullable=False, primary_key=True),
    sa.Column('token_hash', sa.String(length=64), nullable=False),
    sa.Column('expira_en', sa.BigInteger(), nullable=False),
    sa.ForeignKeyConstraint(['id_usuario'], ['usuario.id_usuario'], name=None, ondelete='CASCADE'),
    sa.UniqueConstraint('token_hash', name=None),
)
sa.Index('ix_recuperacion_cuenta_expira_en', metadata.tables['recuperacion_cuenta'].c['expira_en'], unique=False)

sa.Table('retroalimentacion', metadata,
    sa.Column('id_retroalimentacion', sa.Integer(), nullable=False, primary_key=True, autoincrement=True),
    sa.Column('id_prediccion', sa.Integer(), nullable=False),
    sa.Column('id_usuario', sa.Integer(), nullable=False),
    sa.Column('etiqueta_corregida', sa.String(length=100), nullable=True),
    sa.Column('fue_correcta', sa.Boolean(), nullable=False),
    sa.Column('procesado', sa.Boolean(), nullable=False),
    sa.Column('fecha_retroalimentacion', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['id_prediccion'], ['prediccion.id_prediccion'], name=None, ondelete='RESTRICT'),
)
sa.Index('ix_retroalimentacion_id_prediccion', metadata.tables['retroalimentacion'].c['id_prediccion'], unique=True)
sa.Index('ix_retroalimentacion_id_retroalimentacion', metadata.tables['retroalimentacion'].c['id_retroalimentacion'], unique=False)

sa.Table('sesion_web', metadata,
    sa.Column('token_hash', sa.String(length=64), nullable=False, primary_key=True),
    sa.Column('id_usuario', sa.Integer(), nullable=False),
    sa.Column('expira_en', sa.BigInteger(), nullable=False),
    sa.Column('inactiva_en', sa.BigInteger(), nullable=False),
    sa.ForeignKeyConstraint(['id_usuario'], ['usuario.id_usuario'], name=None, ondelete='CASCADE'),
)
sa.Index('ix_sesion_web_expira_en', metadata.tables['sesion_web'].c['expira_en'], unique=False)
sa.Index('ix_sesion_web_id_usuario', metadata.tables['sesion_web'].c['id_usuario'], unique=False)
sa.Index('ix_sesion_web_inactiva_en', metadata.tables['sesion_web'].c['inactiva_en'], unique=False)

sa.Table('feedback_sync', metadata,
    sa.Column('id_retroalimentacion', sa.Integer(), nullable=False, primary_key=True),
    sa.Column('dataset_name', sa.String(length=100), nullable=False),
    sa.Column('storage_class', sa.String(length=100), nullable=False),
    sa.Column('class_label', sa.String(length=100), nullable=False),
    sa.Column('object_key', sa.String(length=255), nullable=False),
    sa.Column('local_relative_path', sa.String(length=255), nullable=False),
    sa.Column('sha256', sa.String(length=64), nullable=False),
    sa.Column('status', sa.String(length=10), nullable=False),
    sa.Column('attempts', sa.Integer(), nullable=False),
    sa.Column('error_code', sa.String(length=32), nullable=True),
    sa.UniqueConstraint('object_key', name=None),
    sa.ForeignKeyConstraint(['id_retroalimentacion'], ['retroalimentacion.id_retroalimentacion'], name=None, ondelete='RESTRICT'),
    sa.UniqueConstraint('local_relative_path', name=None),
    sa.CheckConstraint('attempts >= 0', name='feedback_sync_attempts'),
    sa.CheckConstraint("status IN ('pending', 'synced')", name='feedback_sync_status'),
)

sa.Table('metrica_entrenamiento', metadata,
    sa.Column('id_metrica', sa.Integer(), nullable=False, primary_key=True, autoincrement=True),
    sa.Column('id_modelo', sa.Integer(), nullable=False),
    sa.Column('epoca', sa.Integer(), nullable=False),
    sa.Column('precision', sa.Float(), nullable=False),
    sa.Column('perdida', sa.Float(), nullable=False),
    sa.Column('puntuacion_validacion', sa.Float(), nullable=True),
    sa.Column('tiempo_epoca', sa.Float(), nullable=True),
    sa.ForeignKeyConstraint(['id_modelo'], ['modelo.id_modelo'], name=None, ondelete='CASCADE'),
)
sa.Index('ix_metrica_entrenamiento_id_metrica', metadata.tables['metrica_entrenamiento'].c['id_metrica'], unique=False)
sa.Index('ix_metrica_entrenamiento_id_modelo', metadata.tables['metrica_entrenamiento'].c['id_modelo'], unique=False)

CORE_TABLES = ('conjunto_datos', 'prediccion', 'usuario', 'audio', 'modelo', 'retroalimentacion', 'feedback_sync', 'metrica_entrenamiento')
ACCESS_TABLES = tuple(name for name in metadata.tables if name not in CORE_TABLES)
