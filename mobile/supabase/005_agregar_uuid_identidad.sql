-- Migracion 005: Identidad global por registro (columna uuid) en tablas _movil
-- ============================================================================
-- Objetivo (decision RD-9 del AGENTS.md):
--   El escritorio inserta con id INTEGER local (AUTOINCREMENT) y dos
--   terminales de la MISMA empresa pueden generar el mismo id sin conexion,
--   pisoteandose entre si al hacer merge en Supabase.
--
--   Solucion: columna `uuid` (TEXT/UUID v4) generada por cada terminal al
--   crear el registro. Es la clave estable de merge entre terminales,
--   complementaria al PK compuesto (id, empresa_id).
--
--   IMPORTANTE: aplica este script ANTES de desplegar una version de
--   escritorio que incluya la migracion local _migrar_uuids (sus payloads
--   de sync ya viajan con uuid; sin esta columna el INSERT remoto fallaria).
--
-- Alcance: tablas _movil que el escritorio sube/baja (SyncService) y que
-- existen en el esquema remoto. Es idempotente: si la columna ya existe,
-- no hace nada.

-- 1) Agregar la columna uuid si no existe en cada tabla
DO $$
DECLARE
    t TEXT;
    tablas TEXT[] := ARRAY[
        'insumos_movil',
        'modelos_movil',
        'variantes_movil',
        'proveedores_movil',
        'clientes_movil',
        'ordenes_compra_movil',
        'detalle_orden_compra_movil',
        'ordenes_produccion_movil',
        'seguimiento_produccion_movil',
        'pedidos_cliente_movil',
        'programacion_semana_movil',
        'programacion_lineas_movil',
        'programacion_linea_tallas_movil',
        'tallas_catalogo_movil'
    ];
BEGIN
    FOREACH t IN ARRAY tablas LOOP
        IF to_regclass(format('public.%I', t)) IS NULL THEN
            -- La tabla aun no existe en este proyecto (p. ej. modelos_movil):
            -- se omite sin error para que la migracion sea portable.
            CONTINUE;
        END IF;
        IF NOT EXISTS (
            SELECT 1 FROM information_schema.columns
            WHERE table_name = t AND column_name = 'uuid'
        ) THEN
            EXECUTE format('ALTER TABLE %I ADD COLUMN uuid TEXT', t);
            RAISE NOTICE 'uuid agregada a %', t;
        END IF;
    END LOOP;
END $$;

-- 1b) Garantizar updated_at donde el trigger de timestamp lo exija.
-- programacion_linea_tallas_movil tiene un trigger BEFORE UPDATE que hace
-- NEW.updated_at = now(), pero algunos proyectos nunca aplicaron la
-- migracion 004 y la columna no existe: cualquier UPDATE (el backfill o
-- los merges de sync) fallaria con 42703. Idempotente.
DO $$
BEGIN
    IF to_regclass('public.programacion_linea_tallas_movil') IS NOT NULL
       AND NOT EXISTS (
            SELECT 1 FROM information_schema.columns
            WHERE table_name = 'programacion_linea_tallas_movil'
              AND column_name = 'updated_at'
       ) THEN
        ALTER TABLE programacion_linea_tallas_movil
            ADD COLUMN updated_at TIMESTAMPTZ NOT NULL DEFAULT now();
        RAISE NOTICE 'updated_at agregada a programacion_linea_tallas_movil';
    END IF;
END $$;

-- 2) Backfill: asignar uuid v4 a filas existentes sin uuid
DO $$
DECLARE
    t TEXT;
    tablas TEXT[] := ARRAY[
        'insumos_movil',
        'modelos_movil',
        'variantes_movil',
        'proveedores_movil',
        'clientes_movil',
        'ordenes_compra_movil',
        'detalle_orden_compra_movil',
        'ordenes_produccion_movil',
        'seguimiento_produccion_movil',
        'pedidos_cliente_movil',
        'programacion_semana_movil',
        'programacion_lineas_movil',
        'programacion_linea_tallas_movil',
        'tallas_catalogo_movil'
    ];
BEGIN
    FOREACH t IN ARRAY tablas LOOP
        IF to_regclass(format('public.%I', t)) IS NULL THEN
            -- La tabla aun no existe en este proyecto (p. ej. modelos_movil):
            -- se omite sin error para que la migracion sea portable.
            CONTINUE;
        END IF;
        IF EXISTS (
            SELECT 1 FROM information_schema.columns
            WHERE table_name = t AND column_name = 'uuid'
        ) THEN
            BEGIN
                EXECUTE format(
                    'UPDATE %I SET uuid = gen_random_uuid() '
                    'WHERE uuid IS NULL OR uuid = ''''', t);
            EXCEPTION WHEN OTHERS THEN
                -- No abortar toda la migracion por una tabla con triggers
                -- rotos o permisos faltantes: se reporta y se continua.
                RAISE NOTICE 'Backfill omitido en %: %', t, SQLERRM;
            END;
        END IF;
    END LOOP;
END $$;

-- 3) Indice unico por empresa: clave de merge del escritorio
--    (uuid es estable entre terminales; (empresa_id, uuid) identifica la
--    fila logica sin depender del id numerico local).
DO $$
DECLARE
    t TEXT;
    tablas TEXT[] := ARRAY[
        'insumos_movil',
        'modelos_movil',
        'variantes_movil',
        'proveedores_movil',
        'clientes_movil',
        'ordenes_compra_movil',
        'detalle_orden_compra_movil',
        'ordenes_produccion_movil',
        'seguimiento_produccion_movil',
        'pedidos_cliente_movil',
        'programacion_semana_movil',
        'programacion_lineas_movil',
        'programacion_linea_tallas_movil',
        'tallas_catalogo_movil'
    ];
BEGIN
    FOREACH t IN ARRAY tablas LOOP
        IF to_regclass(format('public.%I', t)) IS NULL THEN
            -- La tabla aun no existe en este proyecto (p. ej. modelos_movil):
            -- se omite sin error para que la migracion sea portable.
            CONTINUE;
        END IF;
        IF EXISTS (
            SELECT 1 FROM information_schema.columns
            WHERE table_name = t AND column_name = 'uuid'
        ) THEN
            EXECUTE format(
                'CREATE UNIQUE INDEX IF NOT EXISTS %I '
                'ON %I (empresa_id, uuid)',
                'idx_' || t || '_uuid', t);
        END IF;
    END LOOP;
END $$;

-- 4) Verificacion
SELECT table_name, column_name, data_type
FROM information_schema.columns
WHERE table_name LIKE '%_movil' AND column_name = 'uuid'
ORDER BY table_name;
