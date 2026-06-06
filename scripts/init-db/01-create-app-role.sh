#!/bin/bash
# Dijalankan otomatis oleh PostgreSQL docker-entrypoint saat inisialisasi pertama.
# Membuat role ojsdef_app sebelum Alembic migration berjalan.
set -e

psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" <<-EOSQL
    DO \$\$
    BEGIN
        IF NOT EXISTS (
            SELECT FROM pg_catalog.pg_roles WHERE rolname = 'ojsdef_app'
        ) THEN
            CREATE ROLE ojsdef_app WITH LOGIN PASSWORD '${POSTGRES_APP_PASSWORD}';
        END IF;
    END
    \$\$;
    GRANT USAGE ON SCHEMA public TO ojsdef_app;
EOSQL
