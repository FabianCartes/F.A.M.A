import { useEffect, useId, useRef, useState } from "react";

interface ModelOption {
  id: string;
  name?: string;
  has_weights?: boolean;
}

export default function PredictionModelSelector({ models, value, onChange }: {
  models: ModelOption[];
  value: string;
  onChange: (id: string) => void;
}) {
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState("");
  const [active, setActive] = useState(0);
  const trigger = useRef<HTMLButtonElement>(null);
  const listId = useId();
  const selected = models.find(model => model.id === value);
  const matches = models.filter(model => (model.name || model.id).toLocaleLowerCase()
    .includes(query.trim().toLocaleLowerCase()));
  const placeholder = models.length ? "Sin modelos con pesos disponibles" : "Sin modelos disponibles";
  useEffect(() => {
    if (open) document.getElementById(`${listId}-${active}`)?.scrollIntoView?.({ block: "nearest" });
  }, [active, listId, open, query]);
  const move = (direction: number) => {
    for (let step = 1; step <= matches.length; step++) {
      const next = (active + direction * step + matches.length) % matches.length;
      if (matches[next].has_weights === true) { setActive(next); return; }
    }
  };
  const close = (restoreFocus = false) => {
    setOpen(false);
    setQuery("");
    setActive(0);
    if (restoreFocus) trigger.current?.focus();
  };
  const choose = (model: ModelOption) => {
    if (model.has_weights !== true) return;
    onChange(model.id);
    close(true);
  };

  return <div className="relative min-w-0 w-full sm:w-[280px] max-w-[340px]"
    onBlur={event => { if (!event.currentTarget.contains(event.relatedTarget)) close(); }}>
    <button id="model-select" ref={trigger} type="button" role="combobox" aria-label="Modelo:"
      aria-expanded={open} aria-controls={listId} aria-haspopup="listbox" value={value}
      onClick={() => { if (open) close(); else setOpen(true); }}
      onKeyDown={event => {
        if (event.key === "ArrowDown" || event.key === "ArrowUp") {
          event.preventDefault();
          const enabled = models.map((model, index) => model.has_weights === true ? index : -1).filter(index => index >= 0);
          setActive(event.key === "ArrowUp" ? enabled.at(-1) ?? 0 : enabled[0] ?? 0);
          setOpen(true);
        }
      }}
      className="relative w-full bg-[#111215] border border-[#23252e] rounded-lg pl-3 pr-9 py-2 text-xs text-gray-200 text-left hover:border-gray-500 transition-colors focus:border-emerald-600">
      <span className="block truncate">{selected ? selected.name || selected.id : placeholder}</span>
      <svg aria-hidden="true" focusable="false" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.75" className="pointer-events-none absolute right-3 top-1/2 -translate-y-1/2 h-3.5 w-3.5 text-gray-400">
        <circle cx="10.5" cy="10.5" r="6.5" /><path d="m16 16 4 4" strokeLinecap="round" />
      </svg>
    </button>
    {open && <div className="absolute z-20 mt-1 w-full bg-[#111215] border border-[#23252e] rounded-lg p-1.5 shadow-lg">
      <input autoFocus type="search" role="combobox" aria-label="Buscar modelo por nombre"
        placeholder="Buscar modelo por nombre…" aria-expanded="true" aria-autocomplete="list" aria-controls={listId}
        aria-activedescendant={matches[active] ? `${listId}-${active}` : undefined}
        value={query} onChange={event => { setQuery(event.target.value); setActive(0); }}
        onKeyDown={event => {
          if (event.key === "ArrowDown" || event.key === "ArrowUp") {
            event.preventDefault();
            move(event.key === "ArrowDown" ? 1 : -1);
          } else if (event.key === "Enter") {
            event.preventDefault();
            if (matches[active]) choose(matches[active]);
          } else if (event.key === "Escape") {
            event.preventDefault();
            close(true);
          }
        }}
        className="w-full bg-[#111215] border border-[#23252e] rounded-lg px-3 py-2 text-xs text-gray-200 focus:border-emerald-600" />
      <ul id={listId} role="listbox" aria-label="Modelos disponibles" className="max-h-60 overflow-y-auto mt-1">
        <li role="group" aria-label="Mis modelos">
          <span className="block px-3 py-1 text-[11px] text-gray-400">Mis modelos</span>
          <ul role="presentation">
            {matches.map((model, index) => <li id={`${listId}-${index}`} key={model.id} role="option"
              aria-selected={model.id === value} aria-disabled={model.has_weights !== true}
              onMouseEnter={() => setActive(index)} onMouseDown={event => event.preventDefault()} onClick={() => choose(model)}
              className={`px-3 py-2 text-xs rounded-lg ${active === index ? "bg-[#23252e]" : ""} ${model.has_weights === true ? "text-gray-200 cursor-pointer" : "text-gray-500 cursor-not-allowed"}`}>
              {model.name || model.id}{model.has_weights === true ? "" : " (no disponible)"}
            </li>)}
          </ul>
        </li>
      </ul>
      {!matches.length && <p role="status" className="px-3 py-2 text-xs text-gray-400">
        {models.length ? "No hay modelos que coincidan con la búsqueda." : "Sin modelos disponibles"}
      </p>}
    </div>}
  </div>;
}
