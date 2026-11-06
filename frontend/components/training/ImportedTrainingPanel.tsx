'use client';
import { useEffect, useRef, useState } from 'react';
import { importedTrainingApi as api, ImportedTrainingError } from '@/lib/api/importedTrainingApi';
import { importedProfileSchema, type ImportedDataset, type ImportedSelection, type ImportedProfile } from '@/lib/schemas/importedTraining';

export default function ImportedTrainingPanel({onSelect, profile, seed, disabled=false}: {
 onSelect:(selection:ImportedSelection|null)=>void; profile:ImportedProfile; seed:number; disabled?:boolean;
}) {
 const [catalog,setCatalog]=useState<ImportedDataset[]>([]);
 const [dataset,setDataset]=useState('');
 const [error,setError]=useState(''); const [pending,setPending]=useState(false);
 const [ready,setReady]=useState<ImportedSelection|null>(null);
 const [restored,setRestored]=useState(false);
 const generation=useRef(0); const controller=useRef<AbortController|null>(null);
 const select=useRef(onSelect); select.current=onSelect;
 const selected=catalog.find(d=>d.id===dataset);
 useEffect(()=>{
   const request=new AbortController();
   api.catalog(request.signal).then(rows=>{if(!request.signal.aborted)setCatalog(rows);})
     .catch(()=>{if(!request.signal.aborted)setError('No se pudo cargar el catálogo privado. Compruebe la sesión y vuelva a seleccionar la fuente.');});
   return ()=>{request.abort();generation.current++;controller.current?.abort();};
 },[]);
 // The parent memoizes this complete profile from the visible controls.
 useEffect(()=>{
   generation.current++;controller.current?.abort();setReady(null);setRestored(false);setPending(false);setError('');select.current(null);
 },[profile,seed]);
 useEffect(()=>{
   const normalized=importedProfileSchema.safeParse(profile);if(!normalized.success)return;
   const match=selected?.preparations.find(p=>p.eligible&&p.reasons.length===0&&p.seed===seed
     &&p.policy?.name==='per-wav-stratified-70-15-15-v1'&&JSON.stringify(p.policy.target)==='[0.7,0.15,0.15]'
     &&p.provenance?.source==='per-wav-independent-assumption-v1'&&Object.keys(p.provenance).length===1
     &&JSON.stringify(p.profile)===JSON.stringify(normalized.data));
   if(match){
     const {snapshot_id,prepared_version,eligible,reasons,profile,warnings}=match;
     const choice:ImportedSelection={dataset_id:dataset,snapshot_id,prepared_version,eligible,reasons,profile,warnings};
     setReady(choice);setRestored(true);select.current(choice);
   }
 },[selected,dataset,profile,seed]);
 function reset(id:string) {
   generation.current++;controller.current?.abort();setDataset(id);setReady(null);setRestored(false);setPending(false);setError('');select.current(null);
 }
 async function prepare() {
   const version=++generation.current;controller.current?.abort();const request=new AbortController();controller.current=request;
   const current=()=>!request.signal.aborted&&version===generation.current;
   setPending(true);setError('');setReady(null);setRestored(false);select.current(null);
   try {
     if(!Number.isInteger(seed)||seed<0||seed>2**32-1)throw new Error('Semilla inválida');
     const normalized=importedProfileSchema.parse(profile);
     const resource=await api.snapshot(dataset,request.signal);if(!current())return;
     const result=await api.members(resource.id,request.signal);if(!current())return;
     // Catalog entries do not attest policy or seed. Request this policy explicitly
     // rather than silently accepting a historical 80/10/10 preparation.
     const manifest=await api.prepare(resource.id,{
       mapping:result.members.map(m=>({member_id:m.member_id,recording_id:m.member_id,group_id:m.member_id})),
       provenance:{source:'per-wav-independent-assumption-v1'},seed,profile:normalized,
     },request.signal);if(!current())return;
     const choice:ImportedSelection={dataset_id:dataset,snapshot_id:resource.id,prepared_version:manifest.version_id,eligible:true,reasons:[],profile:manifest.profile,warnings:manifest.warnings};
     setReady(choice);select.current(choice);
   } catch(reason) {
     if(current())setError(reason instanceof ImportedTrainingError ? reason.message : 'No se pudo preparar el dataset. Revise la configuración de audio y la semilla e inténtelo de nuevo. No se inició entrenamiento.');
   } finally {if(current())setPending(false);}
 }
 return <section aria-label="Preparación importada" className="bg-[#16171b] border border-[#23252e] rounded-xl p-5 space-y-3 shadow-sm">
 <label className="text-[11px] text-gray-400 block font-medium">Dataset para entrenamiento<select className="w-full bg-[#111215] border border-[#23252e] rounded-lg px-3 py-2 text-xs text-gray-200 mt-1.5" disabled={disabled} value={dataset} onChange={e=>reset(e.target.value)}><option value="">Seleccione una colección propia</option>{catalog.map(d=><option key={d.id} value={d.id}>{d.name}</option>)}</select></label>
 <button className="bg-emerald-700 hover:bg-emerald-600 text-white rounded-lg px-3 py-2 text-xs disabled:opacity-40" type="button" disabled={disabled||pending||!selected||Boolean(ready)} onClick={()=>void prepare()}>Preparar dataset</button>
 <p className="text-xs text-gray-400">70% entrenamiento · 15% validación · 15% test.</p>
 <p className="text-xs text-amber-400">Se asume que cada WAV es una grabación independiente; esta independencia no está verificada.</p>
 {selected?.reasons.includes('preparation_stale')&&<p role="status" className="text-xs text-amber-400">El dataset tiene una revisión nueva, que puede incluir audios aceptados en retroalimentación. Prepare de nuevo antes del siguiente entrenamiento. Las preparaciones anteriores se conservan.</p>}
 {selected&&!ready&&!pending&&!error&&<p className="text-xs text-gray-400">Necesita preparación con la configuración actual.</p>}
 {pending&&<p role="status">Preparando dataset. No se iniciará entrenamiento automáticamente.</p>}
 {error&&<p role="alert">{error}</p>}
 {ready&&<p role="status" className="text-xs text-emerald-400">{restored?'Ya preparado para entrenar.':'Preparado para entrenar.'} Iniciar entrenamiento es una acción separada.</p>}
 </section>;
}
