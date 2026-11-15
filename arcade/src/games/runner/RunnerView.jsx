import { useEffect, useRef, useState } from 'react';
import { Screen, FieldMessage } from '../../ui/Screen.jsx';
import { PixelText } from '../../ui/PixelText.jsx';
import { View, C } from './scene.js';

const ACCENTS = [C.cyan, C.orange];

const fmt = (sec) => {
  const s = Math.max(0, Math.ceil(sec));
  return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, '0')}`;
};

function RunnerScreen({ match, index, label, led }) {
  const canvas = useRef(null);
  const ref = useRef(match);
  ref.current = match;
  const [noGl, setNoGl] = useState(false);

  useEffect(() => {
    let view;
    try {
      view = new View(canvas.current, ACCENTS[index], 723 + index);
    } catch {
      setNoGl(true);
      return undefined;
    }
    view.reset(ref.current.track);
    let raf;
    const loop = () => {
      const m = ref.current;
      view.render(m.players[index], m.anim);
      raf = requestAnimationFrame(loop);
    };
    raf = requestAnimationFrame(loop);
    return () => { cancelAnimationFrame(raf); view.dispose(); };
  }, [index]);

  const p = match.players[index];
  let center = null;
  if (noGl) center = <FieldMessage lines={['WEBGL', 'NOT AVAILABLE']} />;
  else if (match.state === 'countdown') center = <FieldMessage lines={[String(Math.max(1, Math.ceil(match.countdown / 1000)))]} scale={4} />;
  else if (!p.alive) center = <FieldMessage lines={match.solo ? ['GAME', 'OVER'] : ['OUT', `${p.score} PTS`]} />;

  return (
    <Screen label={label} led={led} ledLabel="pad">
      <div className="runner">
        <canvas ref={canvas} className="runner-canvas" aria-label={`${label} track`} />
        <div className="runner-hud">
          <div className="hud-box">
            <PixelText text="SCORE" className="dim" />
            <PixelText text={p.score} />
            <div className="lives" aria-label={`${p.lives} lives`}>
              {[0, 1, 2].map((i) => <i key={i} className={i < p.lives ? 'on' : ''} />)}
            </div>
          </div>
          <div className="hud-box right">
            <PixelText text="TIME" className="dim" />
            <PixelText text={fmt(match.duration - match.elapsed)} />
            <PixelText text={`COINS ${p.coins}`} className="dim" />
          </div>
        </div>
        {center && <div className="runner-center">{center}</div>}
        {!center && match.popups[index].map((pp) => (
          <div key={pp.id} className="runner-popup"><PixelText text={pp.text} scale={2} /></div>
        ))}
      </div>
    </Screen>
  );
}

export function RunnerView({ match, pads }) {
  return (
    <div className="stage">
      {match.players.map((_, i) => (
        <RunnerScreen
          key={i}
          match={match}
          index={i}
          label={match.solo ? 'Runner' : `Player ${i + 1}`}
          led={!!pads[i + 1]}
        />
      ))}
    </div>
  );
}
