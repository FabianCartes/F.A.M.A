import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, expect, it, vi } from 'vitest';
import ImportedTrainingPanel from '../ImportedTrainingPanel';
import type { ImportedProfile } from '@/lib/schemas/importedTraining';
const profile:ImportedProfile={architecture:'audio_cnn',channels:1,preprocessing:'mono_mel',windowing:'energy_peak_pad',window_hop_seconds:0.5,audio:{target_sr:8000,duration_seconds:1,n_mels:32,n_fft:256,hop_length:64,f_min:0,f_max:4000,use_gpu_frontend:false}};
afterEach(()=>{cleanup();vi.unstubAllGlobals();});
it('explains dataset growth and accepted feedback without automatic preparation or historical selectors',async()=>{
 const transport=vi.fn(async()=>Response.json({datasets:[{source_type:'imported',id:'owned',name:'Growing dataset',eligible:false,reasons:['preparation_stale'],preparations:[]}]}));vi.stubGlobal('fetch',transport);
 render(<ImportedTrainingPanel profile={profile} seed={42} onSelect={vi.fn()}/>);
 await screen.findByText('Growing dataset');fireEvent.change(screen.getByLabelText('Dataset para entrenamiento'),{target:{value:'owned'}});
 expect(screen.getByText(/El dataset tiene una revisión nueva/).textContent).toContain('aceptados en retroalimentación');
 expect(screen.queryByLabelText('Preparación existente')).toBeNull();expect(transport).toHaveBeenCalledTimes(1);
});
it('hides the stale revision warning after preparation and restores it when the profile changes',async()=>{
 vi.stubGlobal('fetch',vi.fn(async(input:RequestInfo|URL)=>{
  const url=String(input);
  if(url.includes('include_imported'))return Response.json({datasets:[{source_type:'imported',id:'owned',name:'Growing dataset',eligible:false,reasons:['preparation_stale'],preparations:[]}]});
  if(url.endsWith('/members'))return Response.json({snapshot_id:'snap',members:[]});
  if(url.endsWith('/preparations'))return Response.json({snapshot_id:'snap',version_id:'version',state:'ready',profile,class_to_index:{},warnings:[],seed:42});
  return Response.json({id:'snap',dataset_id:'owned',state:'ready',name:'Growing dataset',file_count:0});
 }));
 const select=vi.fn();const view=render(<ImportedTrainingPanel profile={profile} seed={42} onSelect={select}/>);
 await screen.findByText('Growing dataset');
 fireEvent.change(screen.getByLabelText('Dataset para entrenamiento'),{target:{value:'owned'}});
 expect(screen.getByText(/El dataset tiene una revisión nueva/)).toBeTruthy();
 fireEvent.click(screen.getByRole('button',{name:'Preparar dataset'}));
 await screen.findByText(/Preparado para entrenar/);
 expect(screen.queryByText(/El dataset tiene una revisión nueva/)).toBeNull();
 expect(select).toHaveBeenLastCalledWith(expect.objectContaining({eligible:true,prepared_version:'version'}));
 view.rerender(<ImportedTrainingPanel profile={profile} seed={73} onSelect={select}/>);
 await waitFor(()=>expect(screen.queryByText(/Preparado para entrenar/)).toBeNull());
 expect(screen.getByText(/El dataset tiene una revisión nueva/)).toBeTruthy();
 expect(select).toHaveBeenLastCalledWith(null);
});
it.each(['audio','architecture','seed'])('invalidates readiness when %s controls change',async(field)=>{
 vi.stubGlobal('fetch',vi.fn(async(input:RequestInfo|URL)=>{
 const url=String(input);if(url.includes('include_imported'))return Response.json({datasets:[{source_type:'imported',id:'owned',name:'Dataset',eligible:false,reasons:[],preparations:[]}]});
 if(url.endsWith('/members'))return Response.json({snapshot_id:'snap',members:[]});
 if(url.endsWith('/preparations'))return Response.json({snapshot_id:'snap',version_id:'version',state:'ready',profile,class_to_index:{},warnings:[],seed:42});
 return Response.json({id:'snap',dataset_id:'owned',state:'ready',name:'Dataset',file_count:0});
 }));const select=vi.fn();const view=render(<ImportedTrainingPanel profile={profile} seed={42} onSelect={select}/>);
 await screen.findByText('Dataset');fireEvent.change(screen.getByLabelText('Dataset para entrenamiento'),{target:{value:'owned'}});fireEvent.click(screen.getByText('Preparar dataset'));await screen.findByText(/Preparado para entrenar/);
 const next:ImportedProfile=field==='architecture'?{...profile,architecture:'efficientnet_b0'}:field==='audio'?{...profile,audio:{...profile.audio,n_mels:64}}:profile;
 view.rerender(<ImportedTrainingPanel profile={next} seed={field==='seed'?73:42} onSelect={select}/>);
 await waitFor(()=>expect(select).toHaveBeenLastCalledWith(null));expect(screen.queryByText(/Preparado para entrenar/)).toBeNull();expect((screen.getByText('Preparar dataset') as HTMLButtonElement).disabled).toBe(false);
});
