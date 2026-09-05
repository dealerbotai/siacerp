import { supabase } from '../lib/supabase';
import { generarUuid } from '../lib/uuid';
import { obtenerEmpresaId } from './auth';
import type {
  PedidoClienteMovil,
  DetallePedidoMovil,
  ClienteMovil,
} from '../tipos';

/** Talla del catalogo movil */
export interface TallaMovil {
  id: number;
  talla: string;
  activo: boolean;
}

/**
 * Lista pedidos de clientes de la empresa.
 */
export async function listarPedidos(filtro?: string): Promise<{
  ok: boolean;
  datos: PedidoClienteMovil[];
  error?: string;
}> {
  const empresaId = obtenerEmpresaId();
  if (!empresaId || !supabase) {
    return { ok: false, datos: [], error: supabase ? 'No hay sesión activa' : 'Supabase no configurado' };
  }

  let query = supabase
    .from('pedidos_cliente_movil')
    .select('*')
    .eq('empresa_id', empresaId)
    .order('id', { ascending: false });

  if (filtro && filtro !== 'todos') {
    query = query.eq('estatus', filtro);
  }

  const { data, error } = await query;

  if (error) {
    return { ok: false, datos: [], error: error.message };
  }

  return { ok: true, datos: data || [] };
}

/**
 * Busca pedidos por folio, cliente o modelo.
 */
export async function buscarPedidos(termino: string): Promise<{
  ok: boolean;
  datos: PedidoClienteMovil[];
  error?: string;
}> {
  const empresaId = obtenerEmpresaId();
  if (!empresaId || !supabase) {
    return { ok: false, datos: [], error: supabase ? 'No hay sesión activa' : 'Supabase no configurado' };
  }

  const { data, error } = await supabase
    .from('pedidos_cliente_movil')
    .select('*')
    .eq('empresa_id', empresaId)
    .or(
      `folio.ilike.%${termino}%,cliente_nombre.ilike.%${termino}%,folio_pedido.ilike.%${termino}%`,
    )
    .order('id', { ascending: false });

  if (error) {
    return { ok: false, datos: [], error: error.message };
  }

  return { ok: true, datos: data || [] };
}

/**
 * Obtiene un pedido específico.
 */
export async function obtenerPedido(
  id: number,
): Promise<{
  ok: boolean;
  datos: PedidoClienteMovil | null;
  error?: string;
}> {
  const empresaId = obtenerEmpresaId();
  if (!empresaId || !supabase) {
    return { ok: false, datos: null, error: supabase ? 'No hay sesión activa' : 'Supabase no configurado' };
  }

  const { data, error } = await supabase
    .from('pedidos_cliente_movil')
    .select('*')
    .eq('id', id)
    .eq('empresa_id', empresaId)
    .single();

  if (error) {
    return { ok: false, datos: null, error: error.message };
  }

  return { ok: true, datos: data };
}

/**
 * Obtiene el detalle de un pedido con puntos/tallas.
 */
export async function obtenerDetallePedido(
  pedidoId: number,
): Promise<{
  ok: boolean;
  datos: DetallePedidoMovil[];
  error?: string;
}> {
  const empresaId = obtenerEmpresaId();
  if (!empresaId || !supabase) {
    return { ok: false, datos: [], error: supabase ? 'No hay sesión activa' : 'Supabase no configurado' };
  }

  const { data: detalle, error: detError } = await supabase
    .from('detalle_pedido_cliente_movil')
    .select('*')
    .eq('pedido_id', pedidoId)
    .eq('empresa_id', empresaId)
    .order('id');

  if (detError) {
    return { ok: false, datos: [], error: detError.message };
  }

  if (!detalle || detalle.length === 0) {
    return { ok: true, datos: [] };
  }

  // Cargar puntos/tallas para cada detalle
  const detalleConPuntos: DetallePedidoMovil[] = [];
  for (const d of detalle) {
    const { data: puntos } = await supabase
      .from('detalle_pedido_puntos_movil')
      .select('talla_id, talla, pares')
      .eq('detalle_id', d.id)
      .eq('empresa_id', empresaId)
      .order('talla');

    detalleConPuntos.push({
      ...d,
      puntos: puntos || [],
    });
  }

  return { ok: true, datos: detalleConPuntos };
}

/**
 * Cambia el estatus de un pedido.
 */
export async function cambiarEstatusPedido(
  pedidoId: number,
  nuevoEstatus: string,
): Promise<{ ok: boolean; error?: string }> {
  const empresaId = obtenerEmpresaId();
  if (!empresaId || !supabase) {
    return { ok: false, error: supabase ? 'No hay sesión activa' : 'Supabase no configurado' };
  }

  const { error } = await supabase
    .from('pedidos_cliente_movil')
    .update({
      estatus: nuevoEstatus,
      updated_at: new Date().toISOString(),
    })
    .eq('id', pedidoId)
    .eq('empresa_id', empresaId);

  if (error) {
    return { ok: false, error: error.message };
  }

  return { ok: true };
}

/**
 * Programa un pedido en una semana de programación.
 * Crea las lineas de programacion y sus tallas en Supabase.
 */
export async function programarPedido(
  pedidoId: number,
  semanaId: number,
  detalles: {
    detalle_id: number;
    modelo: string;
    piel: string;
    color: string;
    tallas: { talla: string; pares: number }[];
  }[],
): Promise<{ ok: boolean; folios?: string[]; error?: string }> {
  const empresaId = obtenerEmpresaId();
  if (!empresaId || !supabase) {
    return { ok: false, error: !supabase ? 'Supabase no configurado' : 'No hay sesion activa' };
  }

  // Obtener el pedido para el folio y cliente
  const { data: pedido } = await supabase
    .from('pedidos_cliente_movil')
    .select('folio, cliente_nombre, total_pares')
    .eq('id', pedidoId)
    .eq('empresa_id', empresaId)
    .single();

  if (!pedido) {
    return { ok: false, error: 'Pedido no encontrado' };
  }

  const folios: string[] = [];
  // Obtener siguiente folio de programacion
  const { data: ultimas } = await supabase
    .from('programacion_lineas_movil')
    .select('folio_prog')
    .eq('empresa_id', empresaId)
    .order('id', { ascending: false })
    .limit(1);

  let siguienteFolio = 1001;
  if (ultimas && ultimas.length > 0 && ultimas[0].folio_prog) {
    const num = parseInt(ultimas[0].folio_prog, 10);
    if (!isNaN(num)) siguienteFolio = num + 1;
  }

  // Obtener la maxima orden de la semana
  const { data: existentes } = await supabase
    .from('programacion_lineas_movil')
    .select('orden')
    .eq('empresa_id', empresaId)
    .eq('semana_id', semanaId)
    .order('orden', { ascending: false })
    .limit(1);

  let ordenMax = 0;
  if (existentes && existentes.length > 0 && existentes[0].orden) {
    ordenMax = existentes[0].orden;
  }

  for (const det of detalles) {
    // Filtrar tallas con pares > 0
    const tallasConPares = det.tallas.filter((t) => t.pares > 0);
    if (tallasConPares.length === 0) continue;

    const totalPares = tallasConPares.reduce((s, t) => s + t.pares, 0);
    const folio = String(siguienteFolio++);
    ordenMax++;
    const fechaProg = new Date().toISOString().slice(0, 10);

    // Insertar linea de programacion
    const { data: linea, error: lineaError } = await supabase
      .from('programacion_lineas_movil')
      .insert({
        empresa_id: empresaId,
        uuid: generarUuid(),
        semana_id: semanaId,
        orden: ordenMax,
        folio_prog: folio,
        folio_pedido: pedido.folio,
        cliente: pedido.cliente_nombre,
        modelo: det.modelo,
        piel: det.piel,
        color: det.color,
        fecha_prog: fechaProg,
        total_pares: totalPares,
        estatus: 'programacion_incompleta',
        pedido_id: pedidoId,
        detalle_pedido_id: det.detalle_id,
      })
      .select('id')
      .single();

    if (lineaError || !linea) {
      console.error('Error creando linea:', lineaError?.message);
      continue;
    }

    // Insertar tallas
    for (const t of tallasConPares) {
      await supabase.from('programacion_linea_tallas_movil').insert({
        empresa_id: empresaId,
        uuid: generarUuid(),
        linea_id: linea.id,
        talla: t.talla,
        orden: parseFloat(t.talla),
        pares: t.pares,
      });
    }

    folios.push(folio);
  }

  // Actualizar estatus del pedido a programado
  if (folios.length > 0) {
    await supabase
      .from('pedidos_cliente_movil')
      .update({ estatus: 'programado', updated_at: new Date().toISOString() })
      .eq('id', pedidoId)
      .eq('empresa_id', empresaId);
  }

  return { ok: true, folios };
}

// ─── Capturar pedido nuevo ─────────────────────────────────

/** Lista clientes activos de la empresa. */
export async function listarClientes(): Promise<{
  ok: boolean;
  datos: ClienteMovil[];
  error?: string;
}> {
  const empresaId = obtenerEmpresaId();
  if (!empresaId || !supabase) {
    return { ok: false, datos: [], error: supabase ? 'No hay sesion activa' : 'Supabase no configurado' };
  }

  const { data, error } = await supabase
    .from('clientes_movil')
    .select('*')
    .eq('empresa_id', empresaId)
    .eq('activo', true)
    .order('nombre');

  if (error) {
    return { ok: false, datos: [], error: error.message };
  }

  return { ok: true, datos: data || [] };
}

/** Lista tallas activas del catalogo. */
export async function listarTallas(): Promise<{
  ok: boolean;
  datos: TallaMovil[];
  error?: string;
}> {
  const empresaId = obtenerEmpresaId();
  if (!empresaId || !supabase) {
    return { ok: false, datos: [], error: supabase ? 'No hay sesion activa' : 'Supabase no configurado' };
  }

  const { data, error } = await supabase
    .from('tallas_catalogo_movil')
    .select('*')
    .eq('empresa_id', empresaId)
    .eq('activo', true)
    .order('talla');

  if (error) {
    return { ok: false, datos: [], error: error.message };
  }

  return { ok: true, datos: data || [] };
}

/** Crea un pedido nuevo con sus detalles y puntos/tallas. */
export async function crearPedido(params: {
  cliente_id: number;
  cliente_nombre: string;
  folio_pedido?: string;
  suela?: string;
  horma?: string;
  observaciones?: string;
  lineas: {
    modelo: string;
    piel: string;
    color: string;
    tallas: { talla_id: number; talla: string; pares: number }[];
  }[];
}): Promise<{ ok: boolean; pedidoId?: number; folio?: string; error?: string }> {
  const empresaId = obtenerEmpresaId();
  if (!empresaId || !supabase) {
    return { ok: false, error: !supabase ? 'Supabase no configurado' : 'No hay sesion activa' };
  }

  // Calcular total de pares
  const totalPares = params.lineas.reduce(
    (sum, l) => sum + l.tallas.reduce((s, t) => s + t.pares, 0),
    0,
  );

  if (totalPares === 0) {
    return { ok: false, error: 'Agrega al menos una talla con pares > 0' };
  }

  // Obtener siguiente folio
  const { data: ultimos } = await supabase
    .from('pedidos_cliente_movil')
    .select('folio')
    .eq('empresa_id', empresaId)
    .order('id', { ascending: false })
    .limit(1);

  let siguienteFolio = 1;
  if (ultimos && ultimos.length > 0 && ultimos[0].folio) {
    const num = parseInt(ultimos[0].folio.replace(/\D/g, ''), 10);
    if (!isNaN(num)) siguienteFolio = num + 1;
  }

  const folio = `PD-${String(siguienteFolio).padStart(4, '0')}`;
  const hoy = new Date().toISOString().slice(0, 10);

  // Insertar pedido
  const { data: pedido, error: pedidoError } = await supabase
    .from('pedidos_cliente_movil')
    .insert({
      empresa_id: empresaId,
      uuid: generarUuid(),
      folio,
      folio_pedido: params.folio_pedido || null,
      cliente_id: params.cliente_id,
      cliente_nombre: params.cliente_nombre,
      fecha_pedido: hoy,
      total_pares: totalPares,
      estatus: 'pendiente',
      suela: params.suela || null,
      horma: params.horma || null,
      observaciones: params.observaciones || null,
    })
    .select('id')
    .single();

  if (pedidoError || !pedido) {
    return { ok: false, error: pedidoError?.message || 'Error creando pedido' };
  }

  // Insertar detalles y puntos
  for (const linea of params.lineas) {
    const tallasConPares = linea.tallas.filter((t) => t.pares > 0);
    if (tallasConPares.length === 0) continue;

    const { data: detalle, error: detErr } = await supabase
      .from('detalle_pedido_cliente_movil')
      .insert({
        empresa_id: empresaId,
        uuid: generarUuid(),
        pedido_id: pedido.id,
        modelo: linea.modelo,
        piel: linea.piel,
        color: linea.color,
      })
      .select('id')
      .single();

    if (detErr || !detalle) continue;

    // Insertar puntos/tallas
    for (const t of tallasConPares) {
      await supabase.from('detalle_pedido_puntos_movil').insert({
        empresa_id: empresaId,
        uuid: generarUuid(),
        detalle_id: detalle.id,
        talla_id: t.talla_id,
        talla: t.talla,
        pares: t.pares,
      });
    }
  }

  return { ok: true, pedidoId: pedido.id, folio };
}
