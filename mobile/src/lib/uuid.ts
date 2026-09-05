/**
 * Identidad global por registro (RD-9).
 *
 * Cada fila que se inserta en una tabla *_movil sincronizable debe llevar
 * un `uuid` v4 generado por el cliente. Ese uuid es la clave de merge entre
 * terminales en Supabase (la subida ya NO se resuelve por el id numerico,
 * que colisiona entre terminales offline).
 *
 * Usa crypto.randomUUID() cuando el runtime lo expone (Hermes/React Native
 * moderno); si no, genera un uuid v4 con Math.random (suficiente para la
 * escala del sistema: ~122 bits de aleatoriedad).
 */
export function generarUuid(): string {
  const c: any = (globalThis as any).crypto;
  if (c && typeof c.randomUUID === 'function') {
    try {
      return c.randomUUID();
    } catch {
      // Continuar con el generador de respaldo.
    }
  }
  // Generador v4 de respaldo (formato xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx).
  const hex = (n: number): string => n.toString(16).padStart(2, '0');
  const bytes = new Uint8Array(16);
  for (let i = 0; i < 16; i++) {
    bytes[i] = Math.floor(Math.random() * 256);
  }
  bytes[6] = (bytes[6] & 0x0f) | 0x40; // version 4
  bytes[8] = (bytes[8] & 0x3f) | 0x80; // variante RFC 4122
  return [
    hex(bytes[0]) + hex(bytes[1]) + hex(bytes[2]) + hex(bytes[3]),
    hex(bytes[4]) + hex(bytes[5]),
    hex(bytes[6]) + hex(bytes[7]),
    hex(bytes[8]) + hex(bytes[9]),
    hex(bytes[10]) + hex(bytes[11]) + hex(bytes[12]) + hex(bytes[13]) +
      hex(bytes[14]) + hex(bytes[15]),
  ].join('-');
}
