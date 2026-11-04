import { render, screen, fireEvent, waitFor, cleanup } from '@testing-library/react';
import { it, expect, vi, afterEach } from 'vitest';
import TrainingView from '../TrainingView';
import SessionBoundary from '@/components/auth/SessionBoundary';
vi.mock('next/navigation',()=>({useRouter:()=>({replace:vi.fn()})}));
afterEach(()=>{cleanup();vi.unstubAllGlobals();});
it.each(['existing','new'])('starts only the %s imported preparation with visible individual parameters',async(mode)=>{
 const profile={architecture:'audio_cnn',channels:1,preprocessing:'mono_mel',windowing:'energy_peak_pad',window_hop_seconds:0.5,audio:{target_sr:8000,duration_seconds:1,n_mels:32,n_fft:256,hop_length:64,f_min:0,f_max:4000,use_gpu_frontend:false}};
 const transport=vi.fn(async(input:RequestInfo|URL)=>{
 const url=String(input);let data:unknown={};
 if(url.includes('/auth/web/logout'))return new Response(null,{status:204});
 if(url.includes('/auth/web/me'))data={id:1,email:'owner@example.test',nombre_completo:'Owner',rol:'investigador',activo:true};
 else if(url.includes('include_imported=true'))data={datasets:[{source_type:'imported',id:'arbitrary',name:'Arbitrary WAV',eligible:true,reasons:[],preparations:[{snapshot_id:'snapshot',prepared_version:'version',eligible:true,reasons:[],profile,warnings:[]}]}]};
 else if(url.endsWith('/members'))data={snapshot_id:'snapshot',members:[{member_id:'member',class_name:'ants',original_path:'ants/a.wav',size_bytes:44,sha256:'hash'}]};
 else if(url.endsWith('/snapshots'))data={id:'snapshot',dataset_id:'arbitrary',name:'Arbitrary WAV',state:'ready',file_count:1};
 else if(url.endsWith('/preparations'))data={snapshot_id:'snapshot',version_id:'version',state:'ready',profile,class_to_index:{ants:0},warnings:[],seed:42};
 else if(url.includes('/datasets'))data={datasets:[]};else if(url.includes('/history'))data={history:[]};
 else if(url.includes('/progress'))data={status:'checkpoint_persisted',logs:[]};
 return new Response(JSON.stringify(data));});vi.stubGlobal('fetch',transport);vi.stubGlobal('alert',vi.fn());
 render(<SessionBoundary><TrainingView/></SessionBoundary>);
 await screen.findByText('Owner');
 fireEvent.change(screen.getByLabelText('Tipo de fuente'),{target:{value:'imported'}});
 await screen.findByText('Arbitrary WAV');fireEvent.change(screen.getByLabelText('Colección importada'),{target:{value:'arbitrary'}});
 if(mode==='existing')fireEvent.change(screen.getByLabelText('Preparación existente'),{target:{value:'0'}});
 else {
 fireEvent.click(screen.getByText('Crear snapshot y obtener plantilla'));
 await waitFor(()=>expect((screen.getByLabelText('Mapa explícito JSON') as HTMLTextAreaElement).value).toContain('member'));
 fireEvent.change(screen.getByLabelText('Mapa explícito JSON'),{target:{value:'[{"member_id":"member","recording_id":"recording","group_id":"group"}]'}});
 fireEvent.change(screen.getByLabelText('Procedencia JSON'),{target:{value:'{"source":"curated"}'}});
 fireEvent.change(screen.getByLabelText('Perfil explícito JSON'),{target:{value:JSON.stringify(profile)}});
 fireEvent.click(screen.getByText('Preparar snapshot'));
 await screen.findByText(/Preparado para entrenar/);
 }
 expect((screen.getByTestId('architecture-select') as HTMLSelectElement).disabled).toBe(true);
 expect((screen.getByText('2 Modelos (Dúo)') as HTMLButtonElement).disabled).toBe(true);
 fireEvent.change(screen.getByLabelText('Épocas de Entrenamiento'),{target:{value:'1'}});
 fireEvent.change(screen.getByLabelText(/Batch Size \(Tamaño de Lote\)/),{target:{value:'2'}});
 fireEvent.click(screen.getByText('Iniciar Entrenamiento Local (1 Modelo)'));
 await waitFor(()=>expect(transport.mock.calls.some(c=>String(c[0]).includes('/start'))).toBe(true));
 const call=transport.mock.calls.find(c=>String(c[0]).includes('/start'))!;
 const body=JSON.parse(String((call as unknown as [string,RequestInit])[1].body));
 expect(body).toMatchObject({imported_dataset_id:'arbitrary',snapshot_id:'snapshot',imported_prepared_version:'version',architecture:'AudioCNN',epochs:1,batch_size:2,audio_config:profile.audio});
 expect(body).not.toHaveProperty('dataset_name');expect(body).not.toHaveProperty('is_tri_model');
 await screen.findByText(/Checkpoint persistido; evaluación pendiente/,{}, {timeout:2500});
 expect(body.models).toEqual([{architecture:'AudioCNN',weight:1,epochs:1,learning_rate:0.001,batch_size:2}]);
 fireEvent.click(screen.getByText('Cerrar sesión'));
 await waitFor(()=>expect(screen.queryByLabelText('Colección importada')).toBeNull());
 expect((screen.getByLabelText('Tipo de fuente') as HTMLSelectElement).value).toBe('legacy');
});
