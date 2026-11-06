import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, expect, it, vi } from 'vitest';
import ImportedTrainingPanel from '../ImportedTrainingPanel';
import type { ImportedProfile } from '@/lib/schemas/importedTraining';

const profile:ImportedProfile={architecture:'audio_cnn',channels:1,preprocessing:'mono_mel',windowing:'energy_peak_pad',window_hop_seconds:0.5,audio:{target_sr:8000,duration_seconds:1,n_mels:32,n_fft:256,hop_length:64,f_min:0,f_max:4000,use_gpu_frontend:false}};
function prepared():Record<string,unknown> {
 return {snapshot_id:'snap',prepared_version:'new70',eligible:true,reasons:[],profile,warnings:[],seed:42,policy:{name:'per-wav-stratified-70-15-15-v1',target:[0.7,0.15,0.15]},provenance:{source:'per-wav-independent-assumption-v1'}};
}
function catalog(preparation:Record<string,unknown>) {
 const fetch=vi.fn(async()=>Response.json({datasets:[{source_type:'imported',id:'data',name:'My WAVs',eligible:true,reasons:[],preparations:[preparation]}]}));
 vi.stubGlobal('fetch',fetch);return fetch;
}
async function choose() {
 await screen.findByText('My WAVs');
 fireEvent.change(screen.getByLabelText('Dataset para entrenamiento'),{target:{value:'data'}});
}
afterEach(()=>{cleanup();vi.unstubAllGlobals();});
it('restores a compatible preparation after remount without preparing again',async()=>{
 const fetch=catalog(prepared());const select=vi.fn();
 const first=render(<ImportedTrainingPanel profile={profile} seed={42} onSelect={select}/>);
 await choose();await screen.findByText(/Ya preparado para entrenar/);
 first.unmount();select.mockClear();
 const second=render(<ImportedTrainingPanel profile={profile} seed={42} onSelect={select}/>);
 await choose();await screen.findByText(/Ya preparado para entrenar/);
 await waitFor(()=>expect(select).toHaveBeenLastCalledWith(expect.objectContaining({dataset_id:'data',snapshot_id:'snap',prepared_version:'new70'})));
 expect(screen.getByRole('button',{name:'Preparar dataset'})).toHaveProperty('disabled',true);
 expect(screen.queryByLabelText('Preparación existente')).toBeNull();
 expect(fetch).toHaveBeenCalledTimes(2);
 expect(fetch.mock.calls.every(call=>(call as unknown[])[1]===undefined||((call as unknown[])[1] as RequestInit).method==='GET')).toBe(true);
 second.rerender(<ImportedTrainingPanel profile={profile} seed={43} onSelect={select}/>);
 await waitFor(()=>expect(screen.queryByText(/Ya preparado para entrenar/)).toBeNull());
 expect(select).toHaveBeenLastCalledWith(null);
});
it.each(['seed','profile','stale','legacy','target','provenance','missing'])('does not restore incompatible %s metadata',async(damage)=>{
 const choice=prepared();
 if(damage==='seed')choice.seed=43;
 if(damage==='profile')choice.profile={...profile,audio:{...profile.audio,f_min:100}};
 if(damage==='stale'){choice.eligible=false;choice.reasons=['preparation_stale'];}
 if(damage==='legacy')choice.policy={name:'group-cover-v1',target:[0.8,0.1,0.1]};
 if(damage==='target')choice.policy={name:'per-wav-stratified-70-15-15-v1',target:[0.7,0.2,0.1]};
 if(damage==='provenance')choice.provenance={source:'per-wav-independent-assumption-v1',extra:'not the approved sentinel'};
 if(damage==='missing'){delete choice.seed;delete choice.policy;delete choice.provenance;}
 const fetch=catalog(choice);const select=vi.fn();
 render(<ImportedTrainingPanel profile={profile} seed={42} onSelect={select}/>);
 await choose();
 expect(screen.queryByText(/Ya preparado para entrenar/)).toBeNull();
 expect(screen.getByRole('button',{name:'Preparar dataset'})).toHaveProperty('disabled',false);
 expect(select).not.toHaveBeenCalledWith(expect.objectContaining({prepared_version:'new70'}));
 expect(fetch).toHaveBeenCalledTimes(1);
});
