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
it('reports an error without auto-retry or training start',async()=>{
 const transport=vi.fn(async(input:RequestInfo|URL)=>String(input).includes('include_imported')?Response.json({datasets:rows}):Response.json({detail:'No hay suficientes audios por clase.'},{status:422}));vi.stubGlobal('fetch',transport);
 render(<ImportedTrainingPanel profile={profile} seed={42} onSelect={vi.fn()}/>);
 await screen.findByText('first');fireEvent.change(screen.getByLabelText('Dataset para entrenamiento'),{target:{value:'first'}});fireEvent.click(screen.getByText('Preparar dataset'));
 expect(await screen.findByRole('alert')).toHaveProperty('textContent','No hay suficientes audios por clase.');expect(transport).toHaveBeenCalledTimes(2);
});
