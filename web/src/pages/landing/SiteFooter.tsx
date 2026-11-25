import { BrandMark } from '../../ui/Pixels';
import { FooterScene } from './FooterScene';
import { botUrl } from './bot';

/** Landing footer, after MedSim's: lockup and a big display line over link columns, the pixel night street
 *  with the museum, and the credits line sitting on the road. */
export function SiteFooter({ bot, onSignin, onJump }: { bot: string; onSignin: () => void; onJump: (id: string) => void }) {
  return (
    <footer className="lp-footer night">
      <div className="lp-wrap lp-footer-top">
        <div className="lp-footer-brand">
          <span className="lp-footer-lockup"><BrandMark size={40} /><span className="lp-footer-word">Memo</span></span>
          <p className="lp-footer-line">See you in the <em>theater.</em></p>
          <p className="lp-footer-tag">The family memory museum. Send a memory on Telegram, walk through it by year and month, and let Grandma tell it.</p>
        </div>
        <nav className="lp-footer-nav" aria-label="Footer">
          <div>
            <p className="lp-kicker">Visit</p>
            <ul>
              <li><a className="lp-footer-link" href={botUrl(bot)} target="_blank" rel="noreferrer">Open the Telegram bot</a></li>
              <li><button type="button" className="lp-footer-link" onClick={onSignin}>Sign in</button></li>
              <li><button type="button" className="lp-footer-link" onClick={() => onJump('how')}>How it works</button></li>
            </ul>
          </div>
          <div>
            <p className="lp-kicker">Inside</p>
            <ul>
              <li><button type="button" className="lp-footer-link" onClick={() => onJump('cast')}>The cast</button></li>
              <li><button type="button" className="lp-footer-link" onClick={() => onJump('voice')}>Languages</button></li>
              <li><button type="button" className="lp-footer-link" onClick={() => onJump('privacy')}>Privacy</button></li>
              <li><button type="button" className="lp-footer-link" onClick={() => onJump('faq')}>FAQ</button></li>
            </ul>
          </div>
        </nav>
      </div>
      <FooterScene />
      <div className="lp-footer-base">
        <div className="lp-wrap lp-footer-base-inner">
          <p>Text, voice notes and photos in. A museum out. @{bot} on Telegram.</p>
          <p className="lp-footer-small">Private by default. Send /export to take everything with you.</p>
        </div>
      </div>
    </footer>
  );
}
