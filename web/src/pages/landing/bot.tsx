import { useEffect, useState } from 'react';
import QRCode from 'qrcode';
import { get } from '../../api/client';
import { useWorld } from '../../state/worldStore';

export const DEFAULT_BOT = 'memo_ajji_bot';

/** The Memo bot's username: from the museum when signed in, else the public GET /api/bot, else the build-time default. */
export function useBot(): string {
  const m = useWorld((s) => s.museum?.bot_username);
  const [bot, setBot] = useState<string>((import.meta.env.VITE_BOT_USERNAME as string | undefined) || DEFAULT_BOT);
  useEffect(() => {
    if (m) { setBot(m); return; }
    get<{ bot_username?: string }>('/api/bot', { quiet401: true }).then((r) => { if (r.bot_username) setBot(r.bot_username); }).catch(() => undefined);
  }, [m]);
  return bot;
}

export const botUrl = (bot: string) => `https://t.me/${bot}`;

export function QR({ text, size = 160 }: { text: string; size?: number }) {
  const [url, setUrl] = useState('');
  useEffect(() => { QRCode.toDataURL(text, { margin: 1, width: size * 2 }).then(setUrl).catch(() => setUrl('')); }, [text, size]);
  return url ? <img className="qr" src={url} width={size} height={size} alt={`QR code that opens ${text}`} /> : null;
}
