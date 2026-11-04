'use client';
import { useEffect, useRef, useState } from 'react';
import { importedTrainingApi as api, ImportedTrainingError } from '@/lib/api/importedTrainingApi';
import { importedProfileSchema, type ImportedDataset, type ImportedSelection } from '@/lib/schemas/importedTraining';

export default function ImportedTrainingPanel({onSelect, disabled=false}: {onSelect:(selection:ImportedSelection|null)=>void; disabled?:boolean}) {
 const [catalog,setCatalog]=useState<ImportedDataset[]>([]);
 const [dataset,setDataset]=useState(''); const [snapshot,setSnapshot]=useState('');
 const [metadata,setMetadata]=useState('');
 const [mapping,setMapping]=useState(''); const [provenance,setProvenance]=useState('');
 const [profile,setProfile]=useState(''); const [seed,setSeed]=useState('42');
 const [error,setError]=useState(''); const [pending,setPending]=useState(false);
 const [ready,setReady]=useState<ImportedSelection|null>(null);
 const generation=useRef(0); const controller=useRef<AbortController|null>(null);
 const selected=catalog.find(d=>d.id===dataset);
 useEffect(()=>{
   const request=new AbortController(); controller.current=request; const version=++generation.current;
   api.catalog(request.signal).then(rows=>{if(!request.signal.aborted&&version===generation.current)setCatalog(rows);})
     .catch(()=>{if(!request.signal.aborted&&version===generation.current)setError('No se pudo cargar el catálogo privado. Compruebe la sesión y vuelva a seleccionar la fuente.');});
   return ()=>{generation.current++;controller.current?.abort();};
 },[]);
 function reset(id:string) {
   generation.current++;controller.current?.abort();setDataset(id);setSnapshot('');setMapping('');setMetadata('');setProfile('');setProvenance('');setReady(null);setPending(false);setError('');onSelect(null);
 }
 async function operation(work:(signal:AbortSignal)=>Promise<void>) {
   const version=++generation.current;controller.current?.abort();const request=new AbortController();controller.current=request;
   setPending(true);setError('');setReady(null);onSelect(null);
   try {await work(request.signal);} catch (reason) {
     if(!request.signal.aborted&&version===generation.current)setError(reason instanceof ImportedTrainingError ? reason.message : 'No se pudo preparar. Revise mapa, procedencia y perfil; si la conexión se interrumpió, vuelva a seleccionar un recurso existente. No se reintentó ni inició entrenamiento.');
   } finally {if(!request.signal.aborted&&version===generation.current)setPending(false);}
 }
 function choose(selection:ImportedSelection) {setReady(selection);onSelect(selection);}
 return <section aria-label="Preparación importada" className="bg-[#16171b] border border-[#23252e] rounded-xl p-5 space-y-3">
 <h2>Fuente importada — WAV local, una etiqueta por archivo</h2>
 <label>Colección importada<select disabled={disabled} value={dataset} onChange={e=>reset(e.target.value)}><option value="">Seleccione una colección propia</option>{catalog.map(d=><option key={d.id} value={d.id}>{d.name}</option>)}</select></label>
 {selected&&<><p>ID: {selected.id}. {selected.reasons.join(', ')}</p>
 <label>Preparación existente<select disabled={disabled||pending} value={ready ? String(selected.preparations.findIndex(p=>p.prepared_version===ready.prepared_version&&p.snapshot_id===ready.snapshot_id)) : ''} onChange={e=>{const p=selected.preparations[Number(e.target.value)];if(e.target.value!==''&&p?.eligible){controller.current?.abort();generation.current++;choose({...p,dataset_id:dataset});}else{setReady(null);onSelect(null);}}}><option value="">Seleccione snapshot y versión</option>{selected.preparations.map((p,i)=><option key={p.snapshot_id+p.prepared_version} value={i} disabled={!p.eligible}>{p.snapshot_id} / {p.prepared_version} {p.reasons.join(', ')}</option>)}</select></label>
 <button type="button" disabled={disabled||pending} onClick={()=>void operation(async signal=>{
   const resource=await api.snapshot(dataset,signal);if(signal.aborted)return;
   setSnapshot(resource.id);const result=await api.members(resource.id,signal);if(signal.aborted)return;
   setMapping(JSON.stringify(result.members.map(m=>({member_id:m.member_id,recording_id:'',group_id:''})),null,2));
   setMetadata(JSON.stringify(result.members,null,2));
 })}>Crear snapshot y obtener plantilla</button>
 <p>Snapshot: {snapshot||'sin seleccionar'}. Crear snapshot no inicia entrenamiento. Tras una desconexión, consulte nuevamente las preparaciones existentes antes de repetir.</p>
 <Metadata text={metadata}/>
 <p>Complete cada member_id con recording_id y group_id reales; los campos vacíos son intencionales. No deduzca independencia del nombre ni del hash. Todas las clases deben aparecer en train/val/test.</p>
 <label>Mapa explícito JSON<textarea disabled={disabled||pending} value={mapping} onChange={e=>setMapping(e.target.value)} /></label>
 <label>Procedencia JSON<textarea disabled={disabled||pending} placeholder={'{"source":"fuente de anotaciones"}'} value={provenance} onChange={e=>setProvenance(e.target.value)}/></label>
 <p>Perfil completo: architecture, channels, preprocessing, windowing, window_hop_seconds y audio con target_sr, duration_seconds, n_mels, n_fft, hop_length, f_min, f_max, use_gpu_frontend. Debe ser compatible con la arquitectura; no se aplican defaults legacy.</p>
 <label>Perfil explícito JSON<textarea disabled={disabled||pending} value={profile} onChange={e=>setProfile(e.target.value)}/></label>
 <label>Semilla de preparación<input disabled={disabled||pending} value={seed} onChange={e=>setSeed(e.target.value)}/></label>
 <button type="button" disabled={disabled||pending||!snapshot} onClick={()=>void operation(async signal=>{
   if(mapping.length+profile.length+provenance.length>8*1024*1024)throw new Error('Presupuesto');
   if(!/^\d+$/.test(seed)||Number(seed)>2**32-1)throw new Error('Semilla uint32 explícita requerida');
   const manifest=await api.prepare(snapshot,{mapping:JSON.parse(mapping),provenance:JSON.parse(provenance),seed:Number(seed),profile:importedProfileSchema.parse(JSON.parse(profile))},signal);
   if(signal.aborted)return;
   const choice={dataset_id:dataset,snapshot_id:snapshot,prepared_version:manifest.version_id,eligible:true,reasons:[],profile:manifest.profile,warnings:manifest.warnings};
   setCatalog(rows=>rows.map(d=>d.id===dataset?{...d,preparations:[...d.preparations,choice]}:d));choose(choice);
 })}>Preparar snapshot</button></>}
 {pending&&<p role="status">Solicitud en curso; esperando el recurso completo. Sin reintento automático.</p>}
 {error&&<p role="alert">{error}</p>}
 {ready&&<div role="status"><p>Preparado para entrenar: {ready.snapshot_id} / {ready.prepared_version}. Solo modelo individual; iniciar es una acción separada.</p><pre>{JSON.stringify(ready.profile,null,2)}</pre><p>Advertencias (no bloquean por cantidad): {JSON.stringify(ready.warnings)}</p></div>}
 </section>;
 // Metadata is bounded in the visible DOM; the complete JSON remains selectable in a textarea.
 function Metadata({text}:{text:string}) {return <label>Miembros verificados (JSON, clase/ruta/ID)<textarea readOnly value={text} rows={6}/></label>;}
}
