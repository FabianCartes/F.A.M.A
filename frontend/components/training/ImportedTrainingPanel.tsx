'use client';
import { useEffect, useMemo, useRef, useState, type ReactNode } from 'react';
import { importedTrainingApi as api, ImportedTrainingError } from '@/lib/api/importedTrainingApi';
import { importedProfileSchema, type ImportedPreparation, type ImportedDataset, type ImportedSelection, type ImportedProfile } from '@/lib/schemas/importedTraining';

// Only verified protocol codes determine a category; server messages are not UI copy.
function rejectionMessage(code?:string) {
 const messages:Record<string,string>={
  split_impossible:'Grupos independientes insuficientes: no se pudo formar una partición con cobertura por clase. Se requieren al menos tres grupos por clase; tres archivos no prueban independencia.',
  invalid_audio:'Audio no utilizable: hay WAV ilegibles, vacíos, truncados o incompatibles.',
  invalid_profile:'Configuración incompatible: revise arquitectura y parámetros de audio.',
  invalid_seed:'Configuración incompatible: revise la semilla.',
  profile_conflict:'Configuración incompatible: el perfil no coincide con la preparación.',
  profile_mismatch:'Configuración incompatible: el perfil no coincide con la preparación.',
  preparation_required:'Necesita preparación con la configuración actual.',
  preparation_stale:'Necesita preparación con la configuración actual.',
 };
 const key=code ?? '';
 return `${Object.hasOwn(messages,key) ? messages[key] : 'Error de comprobación: no se pudo verificar la preparación. Vuelva a consultar el catálogo antes de solicitar otra preparación explícita.'} No se inició entrenamiento.`;
}

// Exact preparation reuse: same seed, policy, provenance and normalized profile.
function matchPreparation(dataset:ImportedDataset|undefined,profile:ImportedProfile,seed:number) {
 const normalized=importedProfileSchema.safeParse(profile);if(!normalized.success)return undefined;
 return dataset?.preparations.find(p=>p.eligible&&p.reasons.length===0&&p.seed===seed
  &&p.policy?.name==='per-wav-stratified-70-15-15-v1'&&JSON.stringify(p.policy.target)==='[0.7,0.15,0.15]'
  &&p.provenance?.source==='per-wav-independent-assumption-v1'&&Object.keys(p.provenance).length===1
  &&JSON.stringify(p.profile)===JSON.stringify(normalized.data));
}
function selectionOf(dataset:string,p:ImportedPreparation):ImportedSelection {
 const {snapshot_id,prepared_version,eligible,reasons,profile,warnings}=p;
 return {dataset_id:dataset,snapshot_id,prepared_version,eligible,reasons,profile,warnings};
}
const profileKey=(profile:ImportedProfile,seed:number)=>`${seed}|${JSON.stringify(profile)}`;

export default function ImportedTrainingPanel({onSelect, profile, seed, architectureControl, disabled=false, selectedDataset, triadProfiles, onSelectTriad}: {
 onSelect:(selection:ImportedSelection|null)=>void; profile:ImportedProfile; seed:number; architectureControl?:ReactNode; disabled?:boolean;
 selectedDataset?:ImportedDataset;
 // Triad mode: one preparation per component profile on a common snapshot and seed.
 triadProfiles?:ImportedProfile[]; onSelectTriad?:(selections:ImportedSelection[]|null)=>void;
}) {
 const [catalog,setCatalog]=useState<ImportedDataset[]>([]);
 const [localDataset,setDataset]=useState('');
 const dataset=selectedDataset?.id ?? localDataset;
 const [error,setError]=useState(''); const [pending,setPending]=useState(false);
 const [ready,setReady]=useState<ImportedSelection|null>(null);
 const [restored,setRestored]=useState(false);
 const [triadStore,setTriadStore]=useState<Record<string,ImportedSelection>>({});
 const generation=useRef(0); const controller=useRef<AbortController|null>(null);
 const select=useRef(onSelect); select.current=onSelect;
 const selected=selectedDataset ?? catalog.find(d=>d.id===dataset);
 useEffect(()=>{
   if(selectedDataset)return;
   const request=new AbortController();
   api.catalog(request.signal).then(rows=>{if(!request.signal.aborted)setCatalog(rows);})
     .catch(()=>{if(!request.signal.aborted)setError('No se pudo cargar el catálogo privado. Compruebe la sesión y vuelva a seleccionar la fuente.');});
   return ()=>{request.abort();generation.current++;controller.current?.abort();};
 },[selectedDataset]);
 useEffect(()=>()=>{generation.current++;controller.current?.abort();},[]);
 // The parent memoizes this complete profile from the visible controls.
 useEffect(()=>{
   generation.current++;controller.current?.abort();setReady(null);setRestored(false);setPending(false);setError('');select.current(null);
 },[profile,seed,dataset]);
 useEffect(()=>{
   if(triadProfiles)return;
   const match=matchPreparation(selected,profile,seed);
   if(match){
     const {snapshot_id,prepared_version,eligible,reasons,profile,warnings}=match;
     const choice:ImportedSelection={dataset_id:dataset,snapshot_id,prepared_version,eligible,reasons,profile,warnings};
     setReady(choice);setRestored(true);select.current(choice);
   }
 },[selected,dataset,profile,seed,triadProfiles]);
 // Derived, not stored: a changed architecture/profile or seed simply stops matching its entry,
 // so only the affected preparations are invalidated and percentages never matter.
 const triadSelections=useMemo(()=>{
   if(!triadProfiles)return null;
   const chosen=triadProfiles.map(p=>{
     const cached=triadStore[`${dataset}|${profileKey(p,seed)}`];
     const match=cached?undefined:matchPreparation(selected,p,seed);
     if(cached)return cached;
     return match?selectionOf(dataset,match):null;
   });
   return chosen.every(c=>c!==null)&&new Set(chosen.map(c=>c!.snapshot_id)).size===1?chosen as ImportedSelection[]:null;
 },[triadProfiles,triadStore,selected,dataset,seed]);
 useEffect(()=>{onSelectTriad?.(triadSelections);},[triadSelections,onSelectTriad]);
 function reset(id:string) {
   generation.current++;controller.current?.abort();setDataset(id);setReady(null);setRestored(false);setPending(false);setError('');select.current(null);
 }
 async function prepare() {
   const version=++generation.current;controller.current?.abort();const request=new AbortController();controller.current=request;
   const current=()=>!request.signal.aborted&&version===generation.current;
   setPending(true);setError('');setReady(null);setRestored(false);select.current(null);
   try {
     if(!Number.isInteger(seed)||seed<0||seed>2**32-1)throw new Error('Semilla inválida');
     if(triadProfiles){
       const normalizedProfiles=triadProfiles.map(p=>importedProfileSchema.parse(p));
       const resource=await api.snapshot(dataset,request.signal);if(!current())return;
       const result=await api.members(resource.id,request.signal);if(!current())return;
       const done=new Map<string,ImportedSelection>();
       for(const p of normalizedProfiles){
         const key=profileKey(p,seed);if(done.has(key))continue;
         const storeKey=`${dataset}|${key}`;const match=matchPreparation(selected,p,seed);
         const known=triadStore[storeKey]??(match?selectionOf(dataset,match):undefined);
         if(known&&known.snapshot_id===resource.id){done.set(key,known);const reused={[storeKey]:known};setTriadStore(prev=>({...prev,...reused}));continue;}
         const manifest=await api.prepare(resource.id,{
           mapping:result.members.map(m=>({member_id:m.member_id,recording_id:m.member_id,group_id:m.member_id})),
           provenance:{source:'per-wav-independent-assumption-v1'},seed,profile:p,
         },request.signal);if(!current())return;
         const sel:ImportedSelection={dataset_id:dataset,snapshot_id:resource.id,prepared_version:manifest.version_id,eligible:true,reasons:[],profile:manifest.profile,warnings:manifest.warnings};
         done.set(key,sel);const entry={[storeKey]:sel};setTriadStore(prev=>({...prev,...entry}));
       }
       return;
     }
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
     if(current())setError(rejectionMessage(reason instanceof ImportedTrainingError ? reason.code : undefined));
   } finally {if(current())setPending(false);}
 }
 return <section aria-label="Preparación importada" className={selectedDataset ? "space-y-3" : "bg-[#16171b] border border-[#23252e] rounded-xl p-5 space-y-3 shadow-sm"}>
 {!selectedDataset&&<label className="text-[11px] text-gray-400 block font-medium">Dataset para entrenamiento<select className="w-full bg-[#111215] border border-[#23252e] rounded-lg px-3 py-2 text-xs text-gray-200 mt-1.5" disabled={disabled} value={dataset} onChange={e=>reset(e.target.value)}><option value="">Seleccione una colección propia</option>{catalog.map(d=><option key={d.id} value={d.id}>{d.name}</option>)}</select></label>}
 {architectureControl}
 {(triadProfiles??[profile]).some(p=>p.architecture==='panns_cnn14')&&<p className="text-xs text-amber-400">En este flujo, PANNs-CNN14 se inicializa sin pesos preentrenados. Requiere al menos 64 bandas mel.</p>}
 <button className="bg-emerald-700 hover:bg-emerald-600 text-white rounded-lg px-3 py-2 text-xs disabled:opacity-40" type="button" disabled={disabled||pending||!selected||(triadProfiles?Boolean(triadSelections):Boolean(ready))} onClick={()=>void prepare()}>Preparar dataset</button>
 <p className="text-xs text-gray-400">70% entrenamiento · 15% validación · 15% test.</p>
 <p className="text-xs text-white">Se asume que cada WAV es una grabación independiente</p>
 <p className="text-xs text-gray-400">Si cambias la física del audio, la arquitectura o la semilla, prepara el dataset de nuevo.</p>
 {!triadProfiles&&!ready&&selected?.reasons.includes('preparation_stale')&&<p role="status" className="text-xs text-amber-400">El dataset tiene una revisión nueva, que puede incluir audios aceptados en retroalimentación. Prepare de nuevo antes del siguiente entrenamiento. Las preparaciones anteriores se conservan.</p>}
 {!triadProfiles&&selected&&!ready&&!pending&&!error&&<p className="text-xs text-gray-400">{selected.reasons.some(code=>!['preparation_required','preparation_stale'].includes(code)) ? rejectionMessage(selected.reasons.find(code=>!['preparation_required','preparation_stale'].includes(code))) : 'Necesita preparación con la configuración actual.'}</p>}
 {pending&&<p role="status" className="text-xs leading-relaxed text-gray-400">Preparando dataset. No se iniciará entrenamiento automáticamente.</p>}
 {error&&<p role="alert" className="text-xs leading-relaxed text-amber-400">{error}</p>}
 {triadSelections&&<p role="status" className="text-xs text-emerald-400">Tríada preparada para entrenar: tres preparaciones comparten snapshot y semilla. Iniciar entrenamiento es una acción separada.</p>}
 {triadProfiles&&!triadSelections&&!pending&&!error&&<p className="text-xs text-gray-400">Necesita preparación con la configuración actual de los tres componentes.</p>}
 {ready&&!triadProfiles&&<p role="status" className="text-xs text-emerald-400">{restored?'Ya preparado para entrenar.':'Preparado para entrenar.'} Iniciar entrenamiento es una acción separada.</p>}
 </section>;
}
