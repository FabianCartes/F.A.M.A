import { render, screen, fireEvent, waitFor, cleanup, within } from '@testing-library/react';
import { it, expect, vi, afterEach } from 'vitest';
import TrainingView from '../TrainingView';
import Boundary from '@/components/auth/SessionBoundary';
import SidebarSession from '@/components/SidebarSession';
function SessionBoundary({ children }: { children: React.ReactNode }) {
 return <Boundary><SidebarSession isCollapsed={false} onToggleCollapsed={() => {}} />{children}</Boundary>;
}
vi.mock('next/navigation',()=>({useRouter:()=>({replace:vi.fn()})}));
afterEach(()=>{cleanup();vi.unstubAllGlobals();});
it('keeps an explicit registered choice and architecture across rerender and same-owner session refresh', async () => {
 let identityReads = 0;
 vi.stubGlobal('fetch', vi.fn(async (input: RequestInfo | URL) => {
  const url = String(input);
  let data: unknown = {};
  if (url.includes('/auth/me')) {
   identityReads++;
   data = {id:1,email:'owner@example.test',nombre_completo:'Owner',rol:'investigador',activo:true};
  } else if (url.includes('/datasets')) data = {datasets:[{source_type:'legacy',record_id:'legacy:1',id:'AvesChilenas',name:'AvesChilenas',audio_count:9,class_count:3,eligible:true,eligibility_state:'current_flow_compatible',reasons:[]}]};
  else if (url.includes('/history')) data = {history:[]};
  else if (url.includes('/progress')) data = {status:'idle',logs:[]};
  return Response.json(data);
 }));
 const view = render(<SessionBoundary><TrainingView/></SessionBoundary>);
 await screen.findByText('Owner');
 fireEvent.click(screen.getByRole('combobox',{name:'Dataset para entrenamiento'}));
 fireEvent.click(await screen.findByRole('option',{name:'AvesChilenas'}));
 expect(screen.getByLabelText('Dataset para entrenamiento').textContent).toBe('AvesChilenas');
 expect(screen.queryByRole('region', {name:'Preparación importada'})).toBeNull();
 const architecture = screen.getByRole('combobox', {name:'Arquitectura de Red Neuronal'});
 expect(screen.getAllByRole('combobox', {name:'Arquitectura de Red Neuronal'})).toHaveLength(1);
 expect(within(architecture).getByRole('option', {name:'PANNs-CNN14 (Audio Industrial & Pre-trained CNN)'})).toBeTruthy();
 fireEvent.change(architecture, {target:{value:'ResNet-34d'}});
 expect((screen.getByLabelText('Épocas de Entrenamiento') as HTMLInputElement).value).toBe('15');
 expect((screen.getByLabelText(/Batch Size \(Tamaño de Lote\)/) as HTMLInputElement).value).toBe('8');
 view.rerender(<SessionBoundary><TrainingView/></SessionBoundary>);
 fireEvent(window, new Event('focus'));
 await waitFor(() => expect(identityReads).toBe(2));
 await screen.findByText('Owner');
 expect(screen.getByLabelText('Dataset para entrenamiento').textContent).toBe('AvesChilenas');
 expect((screen.getByRole('combobox', {name:'Arquitectura de Red Neuronal'}) as HTMLSelectElement).value).toBe('ResNet-34d');
 expect(screen.queryByLabelText('Colección importada')).toBeNull();
});
