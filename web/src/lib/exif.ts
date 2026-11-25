/** Tiny client-side EXIF reader: DateTimeOriginal and camera model from a JPEG's first 128 KB. Falls back to file date. */
export interface LocalPhoto { file: File; name: string; size: number; taken_at: string; taken_at_source: 'exif' | 'file'; camera: string | null; folder: string | null; width: number | null; height: number | null }

function readAscii(v: DataView, off: number, len: number): string {
  let s = '';
  for (let i = 0; i < len; i++) { const c = v.getUint8(off + i); if (!c) break; s += String.fromCharCode(c); }
  return s.trim();
}

function parseExif(buf: ArrayBuffer): { date?: string; model?: string; w?: number; h?: number } {
  const v = new DataView(buf);
  if (v.byteLength < 4 || v.getUint16(0) !== 0xffd8) return {};
  let p = 2;
  while (p + 4 < v.byteLength) {
    const marker = v.getUint16(p);
    const size = v.getUint16(p + 2);
    if (marker === 0xffe1 && readAscii(v, p + 4, 4) === 'Exif') {
      const t = p + 10;
      const le = v.getUint16(t) === 0x4949;
      const u16 = (o: number) => v.getUint16(o, le);
      const u32 = (o: number) => v.getUint32(o, le);
      const out: { date?: string; model?: string; w?: number; h?: number } = {};
      const ifd = (off: number, depth: number) => {
        if (off + 2 > v.byteLength) return;
        const n = u16(off);
        for (let i = 0; i < n; i++) {
          const e = off + 2 + i * 12;
          if (e + 12 > v.byteLength) return;
          const tag = u16(e), type = u16(e + 2), cnt = u32(e + 4);
          const valOff = cnt * (type === 3 ? 2 : type === 4 ? 4 : 1) > 4 ? t + u32(e + 8) : e + 8;
          if (tag === 0x8769 && depth < 2) ifd(t + u32(e + 8), depth + 1);
          else if ((tag === 0x9003 || tag === 0x0132) && type === 2 && !out.date) out.date = readAscii(v, valOff, cnt);
          else if (tag === 0x0110 && type === 2) out.model = readAscii(v, valOff, cnt);
          else if (tag === 0xa002) out.w = type === 3 ? u16(e + 8) : u32(e + 8);
          else if (tag === 0xa003) out.h = type === 3 ? u16(e + 8) : u32(e + 8);
        }
      };
      try { ifd(t + u32(t + 4), 0); } catch { /* corrupt EXIF */ }
      return out;
    }
    if ((marker & 0xff00) !== 0xff00) break;
    p += 2 + size;
  }
  return {};
}

export async function readLocalPhoto(file: File, folder: string | null): Promise<LocalPhoto> {
  let date: string | undefined, model: string | undefined, w: number | undefined, h: number | undefined;
  if (/jpe?g$/i.test(file.name) || file.type === 'image/jpeg') {
    try { ({ date, model, w, h } = parseExif(await file.slice(0, 131072).arrayBuffer())); } catch { /* ignore */ }
  }
  let iso: string, src: 'exif' | 'file' = 'file';
  const m = date?.match(/^(\d{4}):(\d{2}):(\d{2})[ T](\d{2}):(\d{2}):(\d{2})/);
  if (m) { iso = `${m[1]}-${m[2]}-${m[3]}T${m[4]}:${m[5]}:${m[6]}`; src = 'exif'; } else iso = new Date(file.lastModified).toISOString();
  return { file, name: file.name, size: file.size, taken_at: iso, taken_at_source: src, camera: model || null, folder, width: w ?? null, height: h ?? null };
}

export const isImage = (f: File) => /^image\//.test(f.type) || /\.(jpe?g|png|webp|heic|heif)$/i.test(f.name);

/** Mirrors the server filter keys for the browser-pick source so we upload only what the user confirmed. */
export function filterLocal(items: LocalPhoto[], f: { all?: boolean; latest_n?: number; date_from?: string; date_to?: string; min_size?: number; max_size?: number; camera?: string }): LocalPhoto[] {
  let r = items.slice().sort((a, b) => a.taken_at.localeCompare(b.taken_at));
  if (f.date_from) r = r.filter((p) => p.taken_at.slice(0, 10) >= f.date_from!);
  if (f.date_to) r = r.filter((p) => p.taken_at.slice(0, 10) <= f.date_to!);
  if (f.min_size) r = r.filter((p) => p.size >= f.min_size!);
  if (f.max_size) r = r.filter((p) => p.size <= f.max_size!);
  if (f.camera) r = r.filter((p) => (p.camera || '').toLowerCase().includes(f.camera!.toLowerCase()));
  if (f.latest_n) r = r.slice(-f.latest_n);
  return r;
}
