import { useEffect, useId, useRef, useState } from "react";

interface ModelOption {
  id: string;
  name?: string;
  has_weights?: boolean;
  architecture?: string | null;
  dataset?: string | null;
  dataset_name?: string | null;
  version?: number | null;
  metrics?: unknown;
}

/** Presentation only: version/reference claims come from the complete server ledger. */
export function triadModelDetails(model?: ModelOption) {
  const metrics: Record<string, unknown> = model?.architecture === "ImportedTriad" && model.metrics && typeof model.metrics === "object"
    ? model.metrics as Record<string, unknown> : {};
  const standard = /^fama_triad_[1-9]\d*$/.test(model?.id || "");
  const rawVersion = standard ? model?.version : metrics.triad_version;
  const version = typeof rawVersion === "number" && Number.isInteger(rawVersion) && rawVersion > 0
    ? rawVersion : null;
  const reference = metrics.same_components_as_version;
  const tooltip = version && typeof reference === "number" && Number.isInteger(reference) && reference > 0 && reference < version
    ? `Mismos modelos que la v${reference}; solo cambian los pesos` : undefined;
  const weights = metrics.weights;
  const components = metrics.components;
  const aliases: Record<string, string> = {
    efficientnet_b0: "B0", "EfficientNet-B0": "B0", convnext_nano: "CNX", "ConvNeXt-Nano": "CNX",
    resnet34d: "R34", "ResNet-34d": "R34", audio_cnn: "CNN", AudioCNN: "CNN",
    panns_cnn14: "PANNs", "PANNs-CNN14": "PANNs",
  };
  let weightsLabel: string | undefined;
  if (Array.isArray(weights) && weights.length === 3 && weights.every(w => typeof w === "number" && Number.isFinite(w) && w >= 0 && w <= 1)
      && Math.abs(weights.reduce((a, b) => a + b, 0) - 1) <= 1e-9 && Array.isArray(components) && components.length === 3) {
    const names = components.map(c => c?.imported_source?.profile?.architecture);
    if (names.every(name => typeof name === "string" && name.length > 0)) {
      weightsLabel = names.map((name, i) => `${aliases[name] || name} ${Number((weights[i] * 100).toFixed(6))}`).join(" · ");
    }
  }
  return {
    version, tooltip, weightsLabel,
    datasetId: standard ? model?.dataset_name || model?.dataset || undefined : typeof metrics.dataset_id === "string" ? metrics.dataset_id : undefined,
    datasetName: standard ? model?.dataset || undefined : typeof metrics.dataset_display_name === "string" ? metrics.dataset_display_name : undefined,
  };
}

export function TriadModelBadges({ model }: { model?: ModelOption }) {
  const { weightsLabel, tooltip } = triadModelDetails(model);
  if (!weightsLabel && !tooltip) return null;
  return <span className="flex flex-wrap gap-1 mt-1 text-[11px] text-emerald-300">
    {weightsLabel && <span className="break-words rounded border border-emerald-900 px-1.5 py-0.5">{weightsLabel}</span>}
    {tooltip && <span title={tooltip} aria-label={tooltip} className="cursor-help rounded border border-[#323642] px-1.5 py-0.5 text-gray-400">Solo pesos ⓘ</span>}
  </span>;
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
  const groups = new Map<string, { label: string; models: ModelOption[] }>();
  for (const model of models) {
    if (!(model.name || model.id).toLocaleLowerCase().includes(query.trim().toLocaleLowerCase())) continue;
    const details = triadModelDetails(model);
    const key = details.datasetId && details.datasetName ? `dataset:${details.datasetId}` : "other";
    if (!groups.has(key)) groups.set(key, { label: key === "other" ? "Mis modelos" : details.datasetName!, models: [] });
    groups.get(key)!.models.push(model);
  }
  for (const [key, group] of groups) {
    if (key !== "other") group.models.sort((a, b) => (triadModelDetails(b).version ?? 0) - (triadModelDetails(a).version ?? 0));
  }
  const matches = Array.from(groups.values()).flatMap(group => group.models);
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
          const enabled = matches.map((model, index) => model.has_weights === true ? index : -1).filter(index => index >= 0);
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
        {Array.from(groups.entries()).map(([key, group]) => <li key={key} role="group" aria-label={group.label}>
          <span className="block px-3 py-1 text-[11px] text-gray-400">{group.label}</span>
          <ul role="presentation">
            {group.models.map(model => { const index = matches.indexOf(model); return <li id={`${listId}-${index}`} key={model.id} role="option"
              aria-selected={model.id === value} aria-disabled={model.has_weights !== true}
              onMouseEnter={() => setActive(index)} onMouseDown={event => event.preventDefault()} onClick={() => choose(model)}
              className={`px-3 py-2 text-xs rounded-lg ${active === index ? "bg-[#23252e]" : ""} ${model.has_weights === true ? "text-gray-200 cursor-pointer" : "text-gray-500 cursor-not-allowed"}`}>
              {model.name || model.id}{model.has_weights === true ? "" : " (no disponible)"}
              <TriadModelBadges model={model} />
            </li>; })}
          </ul>
        </li>)}
      </ul>
      {!matches.length && <p role="status" className="px-3 py-2 text-xs text-gray-400">
        {models.length ? "No hay modelos que coincidan con la búsqueda." : "Sin modelos disponibles"}
      </p>}
    </div>}
  </div>;
}
