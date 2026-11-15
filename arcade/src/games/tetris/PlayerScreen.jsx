import { PixelText } from '../../ui/PixelText.jsx';
import { Screen, FieldMessage } from '../../ui/Screen.jsx';
import { MiniPiece, Playfield } from './Playfield.jsx';
import { wrap } from '../../ui/font.js';
import { formatTime } from './engine.js';

function Stat({ label, value }) {
  return (
    <div className="stat">
      <PixelText text={label} className="dim" />
      <PixelText text={value} />
    </div>
  );
}

export function PlayerScreen({ match, player, label, led }) {
  const p = player;
  const paused = match.state === 'paused';
  const incoming = p.garbage.reduce((a, b) => a + b, 0);

  let overlay = null;
  if (match.state === 'countdown') {
    overlay = <FieldMessage lines={[String(Math.max(1, Math.ceil(match.countdown / 1000)))]} scale={4} />;
  } else if (!p.alive) {
    const ko = match.mode === 'timed' ? ['OUT', `LINES ${p.lines}`] : ['GAME', 'OVER'];
    overlay = <FieldMessage lines={ko} />;
  }

  const stats = [
    ['SCORE', p.score],
    ['LINES', match.mode === 'sprint' ? `${p.lines}/40` : p.lines],
    ['LEVEL', p.level],
  ];
  const t = match.timeLimit ? Math.ceil((match.timeLimit - match.elapsed) / 1000) * 1000 : match.elapsed;
  stats.push(['TIME', formatTime(t, match.mode === 'sprint')]);

  return (
    <Screen label={label} led={led} ledLabel="pad">
      <div className="hud">
        <div className="side">
          <div className="panel">
            <PixelText text="HOLD" className="dim" />
            <div className="slot big">{!paused && <MiniPiece type={p.hold} dim={p.holdUsed} />}</div>
          </div>
          {stats.map(([k, v]) => <Stat key={k} label={k} value={v} />)}
        </div>

        <div className="well">
          <div className="wall">
            {incoming > 0 && (
              <div className="incoming" style={{ height: `calc(var(--cell) * ${Math.min(incoming, 20)})` }} />
            )}
          </div>
          <Playfield player={p} hidden={paused} overlay={overlay} />
          <div className="wall" />
        </div>

        <div className="side">
          <div className="panel">
            <PixelText text="NEXT" className="dim" />
            <div className="next">
              {!paused && p.queue.slice(0, 5).map((t, i) => (
                <div key={i} className={i === 0 ? 'slot big' : 'slot'}>
                  <MiniPiece type={t} scale={i === 0 ? 1 : 0.75} />
                </div>
              ))}
            </div>
          </div>
          <div className="popups">
            {p.popups.slice(-2).map((pp) => (
              <div key={pp.id} className={pp.t > 1100 ? 'popup fading' : 'popup'}>
                {wrap(pp.text, 8).map((line) => <PixelText key={line} text={line} />)}
              </div>
            ))}
          </div>
        </div>
      </div>
    </Screen>
  );
}
