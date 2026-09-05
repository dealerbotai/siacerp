-- Migracion 006: RPC de SUBIDA por uuid (fase 2 de RD-9)
-- ============================================================================
-- Objetivo: que la subida del escritorio NO se resuelva por la PK (id,
-- empresa_id) sino por la identidad global `uuid`. Dos terminales offline
-- que crean "el mismo" id numerico (filas logicas distintas, uuid distintos)
-- antes se pisoteaban con el merge-duplicates de la PK; con este RPC:
--
--   1. uuid existente  -> UPDATE de la fila remota (conserva su id: las FKs
--                        que apuntan a esa fila no se rompen).
--   2. uuid inexistente e id libre -> INSERT normal con el id local.
--   3. uuid inexistente pero el id YA lo ocupa otra fila (uuid distinto):
--        a. la fila remota no tiene uuid (legada) -> mismo registro: se
--           ADOPTA el uuid entrante y se fusiona.
--        b. tiene uuid distinto y la "huella" (datos de negocio) coincide
--           (fila pre-RD-9 backfilleada por separado en cada terminal) ->
--           CONVERGE: adopta el uuid entrante (regla conmutable).
--        c. uuid y huella distintos -> fila genuinamente distinta: se
--           REUBICA en espacio de id NEGATIVO (nunca colisiona con ids
--           positivos que generen secuencias, triggers o el movil).
--
-- El escritorio llama a este RPC SOLO cuando tiene la bandera
-- [sync] subir_por_uuid=1 en config.ini; el camino REST anterior queda
-- intacto como respaldo. Aplicar DESPUES de 005_agregar_uuid_identidad.sql
-- (este script ademas refuerza la columna uuid por si acaso).

-- ---------------------------------------------------------------------------
-- 0) Garantizar columna uuid + indice unico + default (idempotente)
-- ---------------------------------------------------------------------------
DO $$
DECLARE
    t TEXT;
    tablas TEXT[] := ARRAY[
        'insumos_movil', 'modelos_movil', 'variantes_movil',
        'proveedores_movil', 'clientes_movil', 'ordenes_compra_movil',
        'detalle_orden_compra_movil', 'ordenes_produccion_movil',
        'seguimiento_produccion_movil', 'pedidos_cliente_movil',
        'programacion_semana_movil', 'programacion_lineas_movil',
        'programacion_linea_tallas_movil'
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
        EXECUTE format(
            'CREATE UNIQUE INDEX IF NOT EXISTS %I ON %I (empresa_id, uuid)',
            'idx_' || t || '_uuid', t);
        -- Clientes viejos (movil sin fase 1) insertan sin uuid: que el
        -- servidor genere uno por ellos.
        EXECUTE format(
            'ALTER TABLE %I ALTER COLUMN uuid SET DEFAULT gen_random_uuid()', t);
    END LOOP;
END $$;

-- 0b) Garantizar updated_at donde el trigger de timestamp lo exija
-- (ver migracion 004 y el bloque 1b de 005). Los UPDATE del RPC sobre
-- programacion_linea_tallas_movil fallarian con 42703 sin la columna.
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

-- ---------------------------------------------------------------------------
-- 1) Funcion de subida por uuid (una sola, generica con lista blanca)
-- ---------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION public.subir_registro_sync(
    p_tabla TEXT,
    p_datos JSONB,
    p_converger BOOLEAN DEFAULT TRUE
)
RETURNS JSONB
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public
AS $_$
DECLARE
    v_tablas_permitidas TEXT[] := ARRAY[
        'insumos_movil', 'modelos_movil', 'variantes_movil',
        'proveedores_movil', 'clientes_movil', 'ordenes_compra_movil',
        'detalle_orden_compra_movil', 'ordenes_produccion_movil',
        'seguimiento_produccion_movil', 'pedidos_cliente_movil',
        'programacion_semana_movil', 'programacion_lineas_movil',
        'programacion_linea_tallas_movil'
    ];
    v_empresa UUID;
    v_uuid TEXT;
    v_id BIGINT;
    v_id_existente BIGINT;
    v_cols TEXT[] := '{}';
    v_col TEXT;
    v_col_list TEXT := '';   -- lista para INSERT:  "c1", "c2"
    v_rec_list TEXT := '';   -- lista para INSERT:  (j)."c1", (j)."c2"
    v_upd_list TEXT := '';   -- lista para UPDATE:  "c1" = (j)."c1", ...
    v_sql TEXT;
    v_existente JSONB;
    v_huella_igual BOOLEAN := TRUE;
    v_nuevo_id BIGINT;
BEGIN
    -- Lista blanca: nunca se ejecuta SQL dinamico sobre tablas arbitrarias.
    IF p_tabla IS NULL OR NOT (p_tabla = ANY(v_tablas_permitidas)) THEN
        RAISE EXCEPTION 'subir_registro_sync: tabla no permitida (%)', p_tabla;
    END IF;

    -- La tabla debe existir en el remoto (modelos/variantes/proveedores
    -- _movil aun no estan desplegados en algunos proyectos).
    IF to_regclass(format('public.%I', p_tabla)) IS NULL THEN
        RAISE EXCEPTION 'subir_registro_sync: la tabla % no existe en el remoto',
                        p_tabla;
    END IF;

    v_empresa := (p_datos->>'empresa_id')::UUID;
    v_uuid    := p_datos->>'uuid';
    v_id      := (p_datos->>'id')::BIGINT;

    IF v_empresa IS NULL THEN
        RAISE EXCEPTION 'subir_registro_sync: falta empresa_id';
    END IF;
    IF v_uuid IS NULL OR v_uuid = '' THEN
        RAISE EXCEPTION 'subir_registro_sync: falta uuid en el payload '
                        '(aplica 005/006 y usa una terminal con fase 1)';
    END IF;

    -- Columnas de negocio a escribir: las del payload que existen en la
    -- tabla remota, excluyendo identidad y sellos de tiempo.
    FOR v_col IN
        SELECT c.column_name
        FROM information_schema.columns c
        WHERE c.table_schema = 'public'
          AND c.table_name = p_tabla
          AND c.column_name NOT IN
              ('id', 'empresa_id', 'uuid', 'created_at', 'updated_at')
          AND p_datos ? c.column_name
        ORDER BY c.column_name
    LOOP
        v_cols := v_cols || v_col;
        v_col_list := v_col_list || ', ' || quote_ident(v_col);
        v_rec_list := v_rec_list || ', (j).' || quote_ident(v_col);
        v_upd_list := v_upd_list || ', ' || quote_ident(v_col)
                      || ' = (j).' || quote_ident(v_col);
    END LOOP;

    v_id_existente := NULL;

    -- 1) Si ya existe una fila remota con este uuid: fusionar (UPDATE),
    --    conservando SIEMPRE el id remoto (las FKs no se rompen).
    EXECUTE format(
        'SELECT id FROM %I WHERE empresa_id = $1 AND uuid = $2',
        p_tabla) INTO v_id_existente USING v_empresa, v_uuid;

    IF v_id_existente IS NOT NULL THEN
        IF v_upd_list <> '' THEN
            v_sql := format(
                'UPDATE %I t SET %s '
                'FROM (SELECT jsonb_populate_record(NULL::%I, $1) AS j) s '
                'WHERE t.id = $2 AND t.empresa_id = $3',
                p_tabla, ltrim(v_upd_list, ', '), p_tabla);
            EXECUTE v_sql USING p_datos, v_id_existente, v_empresa;
        END IF;
        RETURN jsonb_build_object('ok', TRUE, 'accion', 'actualizado',
                                  'id', v_id_existente);
    END IF;

    -- 2) No existe el uuid: insertar. Sin ON CONFLICT (ver 3 y 4).
    BEGIN
        v_sql := format(
            'INSERT INTO %I (id, empresa_id, uuid%s) '
            'SELECT (j).id, (j).empresa_id, (j).uuid%s '
            'FROM (SELECT jsonb_populate_record(NULL::%I, $1) AS j) s '
            'RETURNING id',
            p_tabla, v_col_list, v_rec_list, p_tabla);
        EXECUTE v_sql INTO v_id_existente USING p_datos;
        RETURN jsonb_build_object('ok', TRUE, 'accion', 'insertado',
                                  'id', v_id_existente);

    EXCEPTION WHEN unique_violation THEN
        -- 3) Otro terminal inserto este uuid entre nuestro SELECT y el
        --    INSERT (carrera): simplemente fusionar contra esa fila.
        v_id_existente := NULL;
        EXECUTE format(
            'SELECT id FROM %I WHERE empresa_id = $1 AND uuid = $2',
            p_tabla) INTO v_id_existente USING v_empresa, v_uuid;
        IF v_id_existente IS NOT NULL THEN
            IF v_upd_list <> '' THEN
                EXECUTE format(
                    'UPDATE %I t SET %s '
                    'FROM (SELECT jsonb_populate_record(NULL::%I, $1) AS j) s '
                    'WHERE t.id = $2 AND t.empresa_id = $3',
                    p_tabla, ltrim(v_upd_list, ', '), p_tabla)
                USING p_datos, v_id_existente, v_empresa;
            END IF;
            RETURN jsonb_build_object('ok', TRUE, 'accion', 'actualizado',
                                      'id', v_id_existente);
        END IF;

        -- 4) Colision de PK (id, empresa_id): el id local ya lo ocupa otra
        --    fila. Averiguar si es el mismo registro logico o uno distinto.
        EXECUTE format(
            'SELECT to_jsonb(t) FROM %I t '
            'WHERE t.empresa_id = $1 AND t.id = $2',
            p_tabla) INTO v_existente USING v_empresa, v_id;

        IF v_existente IS NULL THEN
            RAISE EXCEPTION 'subir_registro_sync: conflicto inesperado '
                            'en % (id %)', p_tabla, v_id;
        END IF;

        -- 4a) Fila remota legada SIN uuid: es el mismo registro (nacio antes
        --     de RD-9 y cada terminal backfilleo por separado). Adoptar.
        IF (v_existente->>'uuid') IS NULL OR (v_existente->>'uuid') = '' THEN
            IF v_upd_list <> '' THEN
                v_sql := format(
                    'UPDATE %I t SET uuid = $1, %s '
                    'FROM (SELECT jsonb_populate_record(NULL::%I, $2) AS j) s '
                    'WHERE t.id = $3 AND t.empresa_id = $4',
                    p_tabla, ltrim(v_upd_list, ', '), p_tabla);
                EXECUTE v_sql USING v_uuid, p_datos, v_id, v_empresa;
            ELSE
                EXECUTE format(
                    'UPDATE %I SET uuid = $1 '
                    'WHERE id = $2 AND empresa_id = $3',
                    p_tabla) USING v_uuid, v_id, v_empresa;
            END IF;
            RETURN jsonb_build_object('ok', TRUE, 'accion', 'adoptado',
                                      'id', v_id);
        END IF;

        -- 4b) Regla de convergencia (conmutable): misma huella de negocio =
        --     fila pre-RD-9 duplicada por el backfill de cada terminal.
        IF p_converger THEN
            v_huella_igual := TRUE;
            IF v_cols IS NOT NULL AND array_length(v_cols, 1) > 0 THEN
                FOREACH v_col IN ARRAY v_cols LOOP
                    IF (p_datos -> v_col) IS DISTINCT FROM
                       (v_existente -> v_col) THEN
                        v_huella_igual := FALSE;
                        EXIT;
                    END IF;
                END LOOP;
            END IF;

            IF v_huella_igual THEN
                IF v_upd_list <> '' THEN
                    v_sql := format(
                        'UPDATE %I t SET uuid = $1, %s '
                        'FROM (SELECT jsonb_populate_record(NULL::%I, $2) '
                        'AS j) s WHERE t.id = $3 AND t.empresa_id = $4',
                        p_tabla, ltrim(v_upd_list, ', '), p_tabla);
                    EXECUTE v_sql USING v_uuid, p_datos, v_id, v_empresa;
                ELSE
                    EXECUTE format(
                        'UPDATE %I SET uuid = $1 '
                        'WHERE id = $2 AND empresa_id = $3',
                        p_tabla) USING v_uuid, v_id, v_empresa;
                END IF;
                RETURN jsonb_build_object('ok', TRUE, 'accion', 'convergido',
                                          'id', v_id);
            END IF;
        END IF;

        -- 4c) Fila genuinamente distinta con el mismo id local: reubicar en
        --     espacio NEGATIVO. Los ids positivos (secuencias, triggers,
        --     movil) jamas colisionan con este rango. Sin bloqueos ni
        --     secuencias compartidas.
        EXECUTE format(
            'SELECT COALESCE(MIN(id), 0) - 1 FROM %I WHERE id < 0',
            p_tabla) INTO v_nuevo_id;

        v_sql := format(
            'INSERT INTO %I (id, empresa_id, uuid%s) '
            'SELECT %L, (j).empresa_id, (j).uuid%s '
            'FROM (SELECT jsonb_populate_record(NULL::%I, $1) AS j) s '
            'RETURNING id',
            p_tabla, v_col_list, v_nuevo_id, v_rec_list, p_tabla);
        EXECUTE v_sql INTO v_id_existente USING p_datos;
        RETURN jsonb_build_object('ok', TRUE, 'accion', 'reubicado',
                                  'id', v_id_existente);
    END;
END;
$_$;

-- Verificacion
SELECT proname
FROM pg_proc WHERE proname = 'subir_registro_sync';
