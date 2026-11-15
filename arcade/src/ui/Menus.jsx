import { PixelText } from './PixelText.jsx';
import { Screen } from './Screen.jsx';

function MenuList({ items, index, onPick, onChange, scale = 1, centered = false }) {
  return (
    <ul className={centered ? 'menu-list centered' : 'menu-list'}>
      {items.map((item, i) => {
        const arrows = onChange && item.value !== undefined;
        return (
          <li key={item.key} className={i === index ? 'sel' : undefined}>
            <button type="button" tabIndex={-1} className="row" onClick={() => onPick(i)}>
              <span className="cursor"><PixelText text=">" scale={scale} /></span>
              <PixelText text={item.label} scale={scale} />
            </button>
            {item.value !== undefined && (
              <span className="val">
                {arrows && (
                  <button type="button" tabIndex={-1} className="arrow" onClick={() => onChange(i, -1)} aria-label="Previous value">
                    <PixelText text="<" />
                  </button>
                )}
                <PixelText text={item.value} />
                {arrows && (
                  <button type="button" tabIndex={-1} className="arrow" onClick={() => onChange(i, 1)} aria-label="Next value">
                    <PixelText text=">" />
                  </button>
                )}
              </span>
            )}
          </li>
        );
      })}
    </ul>
  );
}

export function MenuScreen({ title, label, led, rows, index, onPick, onChange, centered = false, itemScale = 1, footer }) {
  const scale = title.length > 7 ? 2 : 3;
  return (
    <div className="stage">
      <Screen label={label} led={led} ledLabel="link">
        <div className={centered ? 'menu centered' : 'menu'}>
          <div className="title"><PixelText text={title} scale={scale} /></div>
          <MenuList items={rows} index={index} onPick={onPick} onChange={onChange} scale={itemScale} centered={centered} />
          {footer && <div className="menu-footer"><PixelText text={footer} className="dim" /></div>}
        </div>
      </Screen>
    </div>
  );
}

export function Dialog({ unit, label, title, sub, note, table, items, index, onPick }) {
  return (
    <div className="modal" style={unit ? { '--u': `${unit}px` } : undefined}>
      <Screen label={label}>
        <div className="dialog">
          <PixelText text={title} scale={2} />
          {sub && <PixelText text={sub} className="dim" />}
          {note && <PixelText text={note} />}
          {table && (
            <div className="table" style={{ gridTemplateColumns: `repeat(${table[0].length}, auto)` }}>
              {table.flatMap((row, r) => row.map((cell, c) => (
                <div key={`${r}-${c}`} className={c === 0 ? 'th' : 'td'}>
                  {cell !== '' && <PixelText text={cell} className={c === 0 ? 'dim' : undefined} />}
                </div>
              )))}
            </div>
          )}
          <MenuList items={items} index={index} onPick={onPick} />
        </div>
      </Screen>
    </div>
  );
}
