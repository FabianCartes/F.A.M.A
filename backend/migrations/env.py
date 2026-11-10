from alembic import context

connection = context.config.attributes.get("connection")
if connection is None:
    raise RuntimeError("Usar python -m app.schema con un destino explícito")
context.configure(connection=connection, transactional_ddl=True)
with context.begin_transaction():
    context.run_migrations()
