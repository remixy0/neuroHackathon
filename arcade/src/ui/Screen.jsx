import { PixelText } from './PixelText.jsx';

// Ramka ekranu (obudowa) z czarnym ekranem w środku
export function Screen({ label, led, ledLabel, className = '', children }) {
  return (
    <section className={`bezel ${className}`}>
      <header className="bezel-top">
        <span>{label}</span>
        {led !== undefined && (
          <span className="led-wrap" title={led ? 'Network pad connected' : 'No network pad'}>
            <i className={led ? 'led on' : 'led'} />
            {ledLabel}
          </span>
        )}
      </header>
      <div className="lcd">{children}</div>
    </section>
  );
}

// Komunikat na środku pola gry (odliczanie, koniec gry…)
export function FieldMessage({ lines, scale = 1 }) {
  return (
    <div className="field-msg">
      {lines.map((l) => <PixelText key={l} text={l} scale={scale} />)}
    </div>
  );
}
