import { render, screen, fireEvent, waitFor, cleanup, act } from '@testing-library/react';
import { afterEach, expect, it, vi } from 'vitest';
import ImportedTrainingPanel from '../ImportedTrainingPanel';
import type { ImportedProfile } from '@/lib/schemas/importedTraining';
const profile:ImportedProfile={architecture:'audio_cnn',channels:1,preprocessing:'mono_mel',windowing:'energy_peak_pad',window_hop_seconds:0.5,audio:{target_sr:8000,duration_seconds:1,n_mels:32,n_fft:256,hop_length:64,f_min:0,f_max:4000,use_gpu_frontend:false}};
const rows=['first','second'].map(id=>({source_type:'imported',id,name:id,eligible:false,reasons:['preparation_required'],preparations:[]}));
afterEach(()=>{cleanup();vi.unstubAllGlobals();});
it.each(['snapshot','members','preparation'])('ignores a late %s after switching datasets and aborts on unmount',async(stage)=>{
 let finish!:(response:Response)=>void;let signal:AbortSignal|undefined;
 const transport=vi.fn((input:RequestInfo|URL,options?:RequestInit)=>{
 const url=String(input);
 if(url.includes('include_imported'))return Promise.resolve(Response.json({datasets:rows}));
 const data=url.endsWith('/members')?{snapshot_id:'snap',members:[{member_id:'wav',class_name:'bird',original_path:'bird/a.wav',size_bytes:44,sha256:'hash'}]}:url.endsWith('/preparations')?{snapshot_id:'snap',version_id:'version',state:'ready',profile,class_to_index:{bird:0},warnings:[],seed:42}:{id:'snap',dataset_id:'first',name:'first',file_count:1,state:'ready'};
 const match=stage==='snapshot'?url.endsWith('/snapshots'):stage==='members'?url.endsWith('/members'):url.endsWith('/preparations');
 if(match){signal=options?.signal as AbortSignal;return new Promise<Response>(resolve=>{finish=()=>resolve(Response.json(data));});}
 return Promise.resolve(Response.json(data));
 });vi.stubGlobal('fetch',transport);
 const select=vi.fn();const view=render(<ImportedTrainingPanel profile={profile} seed={42} onSelect={select}/>);
 await screen.findByText('first');fireEvent.change(screen.getByLabelText('Dataset para entrenamiento'),{target:{value:'first'}});
 fireEvent.click(screen.getByText('Preparar dataset'));
 await waitFor(()=>expect(finish).toBeDefined());
 fireEvent.change(screen.getByLabelText('Dataset para entrenamiento'),{target:{value:'second'}});
 expect(signal?.aborted).toBe(true);
 await act(async()=>finish(Response.json({})));
 expect(select).toHaveBeenLastCalledWith(null);expect(screen.queryByText(/Preparado para entrenar/)).toBeNull();
 view.unmount();expect(signal?.aborted).toBe(true);
});
it.each([
 ['invalid_audio','Audio no utilizable'],
 ['invalid_profile','Configuración incompatible'],
 ['split_search_unavailable','Error de comprobación'],
 ['unknown_server_code','Error de comprobación'],
])('maps %s safely without treating an indeterminate check as insufficient groups',async(code,message)=>{
 const transport=vi.fn(async(input:RequestInfo|URL)=>String(input).includes('include_imported')?Response.json({datasets:rows}):Response.json({detail:{code,message:'unsafe details'}},{status:422}));vi.stubGlobal('fetch',transport);
 render(<ImportedTrainingPanel profile={profile} seed={42} onSelect={vi.fn()}/>);
 await screen.findByText('first');fireEvent.change(screen.getByLabelText('Dataset para entrenamiento'),{target:{value:'first'}});fireEvent.click(screen.getByText('Preparar dataset'));
 expect((await screen.findByRole('alert')).textContent).toContain(message);
 expect(screen.queryByText(/unsafe details/)).toBeNull();
 expect(transport).toHaveBeenCalledTimes(2);
});
it.each(['malformed-success','unexpected-error','network-rejection'])('keeps %s as a check error with cleared readiness and no extra requests',async(mode)=>{
 const transport=vi.fn(async(input:RequestInfo|URL)=>{
  if(String(input).includes('include_imported'))return Response.json({datasets:rows});
  if(mode==='malformed-success')return Response.json({state:'ready'});
  if(mode==='network-rejection')throw new TypeError('unsafe network details');
  return {ok:true,json:async()=>{throw new Error('unsafe unexpected details');}} as unknown as Response;
 });vi.stubGlobal('fetch',transport);
 const select=vi.fn();render(<ImportedTrainingPanel profile={profile} seed={42} onSelect={select}/>);
 await screen.findByText('first');fireEvent.change(screen.getByLabelText('Dataset para entrenamiento'),{target:{value:'first'}});
 fireEvent.click(screen.getByRole('button',{name:'Preparar dataset'}));
 const alert=await screen.findByRole('alert');
 expect(alert.textContent).toContain('Error de comprobación: no se pudo verificar la preparación.');
 expect(alert.textContent).not.toMatch(/Configuración incompatible|Grupos independientes insuficientes|unsafe/);
 expect(screen.queryByText(/Preparado para entrenar/)).toBeNull();
 expect(select).toHaveBeenLastCalledWith(null);
 expect(select.mock.calls.some(([choice])=>choice?.eligible)).toBe(false);
 expect(transport).toHaveBeenCalledTimes(2);
 expect(transport.mock.calls.filter(call=>String(call[0]).endsWith('/snapshots'))).toHaveLength(1);
});
it.each(['constructor','toString','__proto__'])('treats inherited object key %s as an unknown protocol code',async(code)=>{
 const transport=vi.fn(async(input:RequestInfo|URL)=>String(input).includes('include_imported')
  ? Response.json({datasets:rows})
  : Response.json({detail:{code,message:'unsafe raw details'}},{status:422}));vi.stubGlobal('fetch',transport);
 const select=vi.fn();render(<ImportedTrainingPanel profile={profile} seed={42} onSelect={select}/>);
 await screen.findByText('first');fireEvent.change(screen.getByLabelText('Dataset para entrenamiento'),{target:{value:'first'}});
 fireEvent.click(screen.getByRole('button',{name:'Preparar dataset'}));
 const alert=await screen.findByRole('alert');
 expect(alert.textContent).toBe('Error de comprobación: no se pudo verificar la preparación. Vuelva a consultar el catálogo antes de solicitar otra preparación explícita. No se inició entrenamiento.');
 expect(alert.textContent).not.toMatch(/function|native code|object Object|unsafe/);
 expect(select).toHaveBeenLastCalledWith(null);
 expect(select.mock.calls.some(([choice])=>choice?.eligible)).toBe(false);
 expect(screen.queryByText(/Preparado para entrenar/)).toBeNull();
 expect(transport).toHaveBeenCalledTimes(2);
});
it('reports an error without auto-retry or training start',async()=>{
 const transport=vi.fn(async(input:RequestInfo|URL)=>String(input).includes('include_imported')?Response.json({datasets:rows}):Response.json({detail:{code:'split_impossible',message:'unsafe server path /private/data'}},{status:422}));vi.stubGlobal('fetch',transport);
 render(<ImportedTrainingPanel profile={profile} seed={42} onSelect={vi.fn()}/>);
 await screen.findByText('first');fireEvent.change(screen.getByLabelText('Dataset para entrenamiento'),{target:{value:'first'}});fireEvent.click(screen.getByText('Preparar dataset'));
 expect(await screen.findByRole('alert')).toHaveProperty('textContent','Grupos independientes insuficientes: no se pudo formar una partición con cobertura por clase. Se requieren al menos tres grupos por clase; tres archivos no prueban independencia. No se inició entrenamiento.');expect(transport).toHaveBeenCalledTimes(2);
});
