from logging.config import fileConfig

from alembic import context

from fooddb.db import engine, metadata

if context.config.config_file_name:
    fileConfig(context.config.config_file_name)

with engine().connect() as connection:
    context.configure(
        connection=connection,
        target_metadata=metadata,
        version_table=context.config.get_main_option("version_table"),
    )
    with context.begin_transaction():
        context.run_migrations()
