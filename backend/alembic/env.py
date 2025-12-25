from logging.config import fileConfig
import sys
import os
from sqlalchemy import engine_from_config
from sqlalchemy import pool
from sqlmodel import SQLModel
from alembic import context
from alembic.ddl.impl import DefaultImpl
from sqlalchemy.ext.compiler import compiles
from sqlalchemy import Integer

class DuckDBImpl(DefaultImpl):
    __dialect__ = 'duckdb'

@compiles(Integer, "duckdb")
def compile_integer(element, compiler, **kw):
    return "INTEGER"

# Add the backend directory to sys.path
sys.path.append(os.getcwd())

# Import models
from models import * # noqa
from infra.database.connection import DATABASE_URL

config = context.config
config.set_main_option("sqlalchemy.url", DATABASE_URL)

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = SQLModel.metadata

def run_migrations_offline() -> None:
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()

def run_migrations_online() -> None:
    """
    オンラインマイグレーションの実行。
    テスト環境から connection が渡されている場合は、新しくエンジンを作らずに再利用します。
    """
    # テスト用コネクションが注入されているか確認
    connectable = context.config.attributes.get("connection", None)

    if connectable is None:
        # 通常起動時：設定ファイルからエンジンを作成
        connectable = engine_from_config(
            config.get_section(config.config_ini_section, {}),
            prefix="sqlalchemy.",
            poolclass=pool.NullPool,
        )
        
        with connectable.connect() as connection:
            context.configure(
                connection=connection, 
                target_metadata=target_metadata
            )
            with context.begin_transaction():
                context.run_migrations()
    else:
        # テスト実行時：渡されたコネクションをそのまま使用（DuckDBのロック回避）
        context.configure(
            connection=connectable, 
            target_metadata=target_metadata
        )
        with context.begin_transaction():
            context.run_migrations()

if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()