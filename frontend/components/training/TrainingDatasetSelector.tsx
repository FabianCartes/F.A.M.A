'use client';
import { useEffect, useId, useRef, useState } from 'react';
import { getDatasetCatalog } from '@/lib/api/trainingApi';
import type { TrainingCatalogDataset } from '@/lib/schemas/training';

export type CatalogSelection = TrainingCatalogDataset;
const identity = (row: CatalogSelection) => row.record_id;
const label = (row: CatalogSelection) => row.name;

export default function TrainingDatasetSelector({onSelect, disabled=false, defaultName}: {
  onSelect:(row:CatalogSelection)=>void; disabled?:boolean;
  defaultName?:string;
}) {
  const [rows,setRows]=useState<CatalogSelection[]>([]);
  const [selected,setSelected]=useState<CatalogSelection|null>(null);
  const [query,setQuery]=useState('');
  const [open,setOpen]=useState(false);
  const [active,setActive]=useState(0);
  const trigger=useRef<HTMLButtonElement>(null);
  const listId=useId();
  const expanded=open&&!disabled;
  const close=(restore=false)=>{setOpen(false);setQuery('');setActive(0);if(restore)trigger.current?.focus();};
  const [error,setError]=useState(false);
  const [retry,setRetry]=useState(0);
  useEffect(()=>{
    const request=new AbortController();
    getDatasetCatalog()
      .then(rows=>{if(!request.signal.aborted){setRows(rows);setError(false);}})
      .catch(()=>{if(!request.signal.aborted)setError(true);});
    return ()=>request.abort();
  },[retry]);
  const matches=rows.filter(row=>row.name.toLocaleLowerCase().includes(query.trim().toLocaleLowerCase()));
  const choose=(row:CatalogSelection)=>{if(disabled)return;setSelected(row);onSelect(row);close(true);};
  return <section aria-label="Catálogo de entrenamiento" className="space-y-3">
    <div className="relative" onBlur={event=>{if(!event.currentTarget.contains(event.relatedTarget))close();}}>
      <label id={`${listId}-label`} className="block text-[11px] text-gray-400">Dataset para entrenamiento</label>
      <button ref={trigger} type="button" role="combobox" aria-labelledby={`${listId}-label`} aria-expanded={expanded} aria-controls={listId} aria-haspopup="listbox" disabled={disabled}
        onClick={()=>{if(expanded)close();else {setQuery('');setActive(0);setOpen(true);}}}
        onKeyDown={event=>{if(disabled)return;if(event.key==='ArrowDown'||event.key==='ArrowUp'){event.preventDefault();setActive(event.key==='ArrowUp'?Math.max(0,rows.length-1):0);setOpen(true);}else if(event.key==='Escape')close();}}
        className="relative mt-1.5 w-full bg-[#111215] border border-[#23252e] rounded-lg pl-3 pr-9 py-2 text-xs text-gray-200 text-left enabled:hover:border-gray-500 transition-colors focus:border-emerald-600 disabled:opacity-50">
        {selected?label(selected):defaultName || 'Buscar o seleccionar dataset…'}
        <svg aria-hidden="true" focusable="false" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.75" className="pointer-events-none absolute right-3 top-1/2 -translate-y-1/2 h-3.5 w-3.5 text-gray-400">
          <circle cx="10.5" cy="10.5" r="6.5"/><path d="m16 16 4 4" strokeLinecap="round"/>
        </svg>
      </button>
      {expanded&&<div className="absolute z-20 mt-1 w-full bg-[#111215] border border-[#23252e] rounded-lg p-1.5">
        <input autoFocus role="combobox" aria-expanded="true" aria-autocomplete="list" aria-label="Buscar dataset por nombre" placeholder="Buscar dataset por nombre…" type="search" value={query} aria-controls={listId} aria-activedescendant={matches[active]?`${listId}-${active}`:undefined}
          onChange={event=>{setQuery(event.target.value);setActive(0);}}
          onKeyDown={event=>{
            if(event.key==='Escape'){event.preventDefault();close(true);}
            else if(event.key==='ArrowDown'||event.key==='ArrowUp'){event.preventDefault();setActive(value=>matches.length?(value+(event.key==='ArrowDown'?1:-1)+matches.length)%matches.length:0);}
            else if(event.key==='Enter'){event.preventDefault();if(matches[active])choose(matches[active]);}
          }}
          className="w-full bg-[#111215] border border-[#23252e] rounded-lg px-3 py-2 text-xs text-gray-200 focus:border-emerald-600"/>
        <ul id={listId} role="listbox" aria-label="Datasets disponibles" className="max-h-60 overflow-y-auto mt-1">
          {matches.map((row,index)=><li id={`${listId}-${index}`} key={identity(row)} role="option" aria-selected={!!selected&&identity(selected)===identity(row)} onMouseEnter={()=>setActive(index)} onMouseDown={event=>event.preventDefault()} onClick={()=>choose(row)}
            className={`px-3 py-2 text-xs text-gray-200 rounded-lg cursor-pointer ${active===index?'bg-[#23252e]':''}`}>{label(row)}</li>)}
        </ul>
        {!matches.length&&!error&&<p className="px-3 py-2 text-xs text-gray-400">No hay datasets que coincidan con la búsqueda.</p>}
      </div>}
    </div>
    {!expanded&&!matches.length&&!error&&<p className="text-xs text-gray-400">No hay datasets que coincidan con la búsqueda.</p>}
    {error&&<p role="alert">Error de comprobación: no se pudo consultar el catálogo. <button type="button" onClick={()=>setRetry(value=>value+1)}>Reintentar consulta</button></p>}
  </section>;
}
