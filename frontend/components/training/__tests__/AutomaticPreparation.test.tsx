import { render, screen, fireEvent, waitFor, cleanup } from '@testing-library/react';
import { afterEach, expect, it, vi } from 'vitest';
import ImportedTrainingPanel from '../ImportedTrainingPanel';
import type { ImportedProfile } from '@/lib/schemas/importedTraining';
const profile:ImportedProfile={architecture:'efficientnet_b0',channels:1,preprocessing:'mono_mel',windowing:'energy_peak_pad',window_hop_seconds:1,audio:{target_sr:22050,duration_seconds:5,n_mels:128,n_fft:2048,hop_length:512,f_min:800,f_max:10000,use_gpu_frontend:false}};
afterEach(()=>{cleanup();vi.unstubAllGlobals();});
it('prepares the selected dataset automatically with the visible profile and explicit independent WAV assumption',async()=>{
 const select=vi.fn();const bodies:Record<string,unknown>[]=[];
 vi.stubGlobal('fetch',vi.fn(async(input:RequestInfo|URL,init?:RequestInit)=>{
 const url=String(input);if(init?.body)bodies.push(JSON.parse(String(init.body)));
 if(url.includes('include_imported'))return Response.json({datasets:[{source_type:'imported',id:'data',name:'My WAVs',eligible:true,reasons:[],preparations:[{snapshot_id:'old',prepared_version:'old80',eligible:true,reasons:[],profile,warnings:[]}]}]});
 if(url.endsWith('/members'))return Response.json({snapshot_id:'snap',members:[{member_id:'wav-1',class_name:'bird',original_path:'bird/a.wav',size_bytes:44,sha256:'hash'}]});
 if(url.endsWith('/preparations'))return Response.json({snapshot_id:'snap',version_id:'new70',state:'ready',profile,class_to_index:{bird:0},warnings:[],seed:73});
 return Response.json({id:'snap',dataset_id:'data',state:'ready',name:'My WAVs',file_count:1});
 }));
 render(<ImportedTrainingPanel profile={profile} seed={73} onSelect={select}/>);
 await screen.findByText('My WAVs');fireEvent.change(screen.getByLabelText('Dataset para entrenamiento'),{target:{value:'data'}});
 expect(screen.queryByRole('textbox')).toBeNull();expect(screen.queryByLabelText('Preparación existente')).toBeNull();
 expect(select).not.toHaveBeenCalledWith(expect.objectContaining({prepared_version:'old80'}));
 fireEvent.click(screen.getByRole('button',{name:'Preparar dataset'}));
 await screen.findByText(/Preparado para entrenar/);
 expect(bodies[1]).toEqual({mapping:[{member_id:'wav-1',recording_id:'wav-1',group_id:'wav-1'}],provenance:{source:'per-wav-independent-assumption-v1'},seed:73,profile});
 await waitFor(()=>expect(select).toHaveBeenLastCalledWith(expect.objectContaining({prepared_version:'new70'})));
});
