'use client';
import { useEffect, useState } from 'react';
import { getDatasetCatalog } from '@/lib/api/trainingApi';
import { importedTrainingApi } from '@/lib/api/importedTrainingApi';
import type { TrainingCatalogDataset } from '@/lib/schemas/training';
import type { ImportedDataset } from '@/lib/schemas/importedTraining';

export type CatalogSelection = TrainingCatalogDataset | ImportedDataset;
const identity = (row: CatalogSelection) => row.source_type === 'legacy' ? row.record_id : `imported:${row.id}`;
const label = (row: CatalogSelection) => `${row.name} (${row.source_type === 'legacy' ? 'Registrado' : 'Importado propio'}, ${identity(row)})`;

export default function TrainingDatasetSelector({includeImported, onSelect, disabled=false, defaultLegacyName}: {
  includeImported:boolean; onSelect:(row:CatalogSelection)=>void; disabled?:boolean;
  defaultLegacyName?:string;
}) {
  const [rows,setRows]=useState<CatalogSelection[]>([]);
  const [selected,setSelected]=useState<CatalogSelection|null>(null);
  const [query,setQuery]=useState('');
  const [error,setError]=useState(false);
  const [retry,setRetry]=useState(0);
  useEffect(()=>{
    const request=new AbortController();
    Promise.all([getDatasetCatalog(), includeImported ? importedTrainingApi.catalog(request.signal) : Promise.resolve([])])
      .then(([legacy,imports])=>{if(!request.signal.aborted){setRows([...legacy,...imports]);setError(false);}})
      .catch(()=>{if(!request.signal.aborted)setError(true);});
    return ()=>request.abort();
  },[includeImported,retry]);
  const matches=rows.filter(row=>row.name.toLocaleLowerCase().includes(query.trim().toLocaleLowerCase()));
  const hiddenSelection=selected&&!matches.some(row=>identity(row)===identity(selected));
  return <section aria-label="Catálogo de entrenamiento" className="space-y-3">
    <label className="block text-[11px] text-gray-400">Buscar dataset por nombre
      <input type="search" value={query} onChange={event=>setQuery(event.target.value)} className="mt-1.5 w-full bg-[#111215] border border-[#23252e] rounded-lg px-3 py-2 text-xs text-gray-200 focus:border-emerald-600"/>
    </label>
    <label className="block text-[11px] text-gray-400">Dataset para entrenamiento
      <select disabled={disabled} value={selected?identity(selected):defaultLegacyName?`legacy:default:${defaultLegacyName}`:''} onChange={event=>{
        const row=rows.find(row=>identity(row)===event.target.value);
        if(row){setSelected(row);onSelect(row);}
      }} className="mt-1.5 w-full bg-[#111215] border border-[#23252e] rounded-lg px-3 py-2 text-xs text-gray-200 focus:border-emerald-600">
        {!selected&&defaultLegacyName
          ? <option value={`legacy:default:${defaultLegacyName}`} disabled>{defaultLegacyName} (Legacy predeterminado; validación al iniciar)</option>
          : <option value="" disabled>Seleccione un dataset</option>}
        {hiddenSelection&&<option value={identity(selected)}>{label(selected)} — selección fuera del filtro</option>}
        {matches.map(row=><option key={identity(row)} value={identity(row)}>{label(row)}</option>)}
      </select>
    </label>
    {!matches.length&&!error&&<p className="text-xs text-gray-400">No hay datasets que coincidan con la búsqueda.</p>}
    {error&&<p role="alert">Error de comprobación: no se pudo consultar el catálogo. <button type="button" onClick={()=>setRetry(value=>value+1)}>Reintentar consulta</button></p>}
  </section>;
}
