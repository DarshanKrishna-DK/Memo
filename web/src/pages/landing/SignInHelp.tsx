import { useEffect, useState } from 'react';
import { ApiError, get, post } from '../../api/client';
import { useWorld } from '../../state/worldStore';
import { Modal } from '../../ui/common';
import { QR, botUrl } from './bot';

interface DevMember { id: string; nickname: string | null; role: string; family_name: string }

/** "How to sign in" pop-up: the museum opens from a private link the bot sends after /museum. */
export function SignInHelp({ bot, onClose }: { bot: string; onClose: () => void }) {
  const err = useWorld((s) => s.authError);
  const boot = useWorld((s) => s.boot);
  const [members, setMembers] = useState<DevMember[]>([]);
  const [devErr, setDevErr] = useState<string | null>(null);
  const [checking, setChecking] = useState(false);
  const link = botUrl(bot);
  useEffect(() => {
    if (!import.meta.env.DEV) return;
    get<{ members: DevMember[] }>('/api/dev/members', { quiet401: true }).then((r) => setMembers(r.members)).catch(() => undefined);
  }, []);
  async function retry() {
    setChecking(true);
    await boot();
    setChecking(false);
  }
  async function dev(id: string) {
    setDevErr(null);
    try { await post('/api/dev/signin', { member_id: id }); await boot(); } catch (e) { setDevErr(e instanceof ApiError && e.status === 404 ? 'Dev sign-in is off on this server.' : e instanceof Error ? e.message : 'Dev sign-in failed.'); }
  }
  return (
    <Modal title="Sign in with Telegram" onClose={onClose}>
      {err && <p className="err" role="alert">{err}</p>}
      <p>There is no password. Your museum opens from a private link that the Memo bot sends you.</p>
      <div className="lp-signin">
        <ol className="lp-signin-steps">
          <li>Open <a href={link} target="_blank" rel="noreferrer">@{bot}</a> in Telegram, or scan the code with your phone.</li>
          <li>Send <kbd>/museum</kbd>.</li>
          <li>Tap the button in the reply. It brings you back here, signed in.</li>
        </ol>
        <QR text={link} size={136} />
      </div>
      <p className="muted lp-small">The link works once and expires after 15 minutes. Send <kbd>/museum</kbd> again for a fresh one.</p>
      <div className="row">
        <a className="btn btn-primary" href={link} target="_blank" rel="noreferrer">Open the Telegram bot</a>
        <button type="button" className="btn" onClick={() => void retry()} disabled={checking}>{checking ? 'Checking' : 'I have signed in, check again'}</button>
      </div>
      {members.length > 0 && (
        <div className="stack">
          <span className="label">Development only</span>
          {members.map((m) => <button key={m.id} type="button" className="btn btn-ghost btn-sm" onClick={() => void dev(m.id)}>Dev sign-in: {m.nickname ?? 'member'} ({m.role}), {m.family_name}</button>)}
          {devErr && <p className="err">{devErr}</p>}
        </div>
      )}
    </Modal>
  );
}
