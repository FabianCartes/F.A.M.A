import {afterEach, expect, it, vi} from 'vitest';
import {act, cleanup, fireEvent, render, screen, waitFor} from '@testing-library/react';
import TrainingView from '../TrainingView';
import {confirmApiSession} from '@/lib/api';
afterEach(()=>{cleanup();vi.unstubAllGlobals();});
function transport(progress: () => Promise<Response>, stop = async () => Response.json({status:'stopping'})) {
 const fetcher=vi.fn(async(input:RequestInfo|URL)=>{
  const url=String(input);
  if(url.endsWith('/progress'))return progress();
  if(url.endsWith('/stop'))return stop();
  if(new URL(url,window.location.origin).pathname.endsWith('/datasets'))return Response.json({datasets:[]});
  if(url.endsWith('/history'))return Response.json({history:[]});
  return Response.json({});
 });
 vi.stubGlobal('fetch',fetcher);return fetcher;
}
it('holds admission pending across an idle progress read, prevents duplicate POSTs and transitions only on acceptance',async()=>{
 let resolve!:(r:Response)=>void;
 let reads=0;
 const fetcher=transport(async()=>{reads++;return Response.json({status:'idle'});});
 const base=fetcher.getMockImplementation()!;
 fetcher.mockImplementation(async(input:RequestInfo|URL)=>String(input).endsWith('/start') ? new Promise<Response>(r=>{resolve=r;}) : base(input));
 render(<TrainingView/>);
 await waitFor(()=>expect(start().disabled).toBe(false));
 fireEvent.click(start());
 const pending=screen.getByRole('button',{name:'Preparando inicio…'}) as HTMLButtonElement;
 expect(pending.disabled).toBe(true);
 expect(screen.getByText('Preparando la solicitud de inicio. Puede tardar unos segundos.')).toBeTruthy();
 expect(screen.queryByRole('button',{name:'Detener'})).toBeNull();
 fireEvent.click(pending);
 // Changing epochs triggers the existing progress reader while the POST is deferred.
 fireEvent.change(screen.getByLabelText('Épocas de Entrenamiento'),{target:{value:'11'}});
 await waitFor(()=>expect(reads).toBeGreaterThan(1));
 expect(pending.disabled).toBe(true);
 fireEvent.click(pending);
 expect(fetcher.mock.calls.filter(c=>String(c[0]).endsWith('/start'))).toHaveLength(1);
 await act(async()=>resolve(Response.json({status:'started'})));
 await screen.findByRole('button',{name:'Detener'});
 expect(screen.queryByText('Preparando la solicitud de inicio. Puede tardar unos segundos.')).toBeNull();
});
it.each(['http','network'])('releases pending admission after %s failure without an automatic retry',async mode=>{
 let reject!:(error:Error)=>void;
 let resolve!:(r:Response)=>void;
 const alert=vi.fn();vi.stubGlobal('alert',alert);
 const fetcher=transport(async()=>Response.json({status:'idle'}));
 const base=fetcher.getMockImplementation()!;
 fetcher.mockImplementation(async(input:RequestInfo|URL)=>String(input).endsWith('/start') ? new Promise<Response>((yes,no)=>{resolve=yes;reject=no;}) : base(input));
 render(<TrainingView/>);
 await waitFor(()=>expect(start().disabled).toBe(false));fireEvent.click(start());
 expect(screen.getByRole('button',{name:'Preparando inicio…'})).toBeTruthy();
 await act(async()=>{if(mode==='network')reject(new TypeError('Failed to fetch'));else resolve(Response.json({detail:'Admission denied'},{status:409}));});
 await waitFor(()=>expect(start().disabled).toBe(false));
 expect(alert).toHaveBeenCalledWith(expect.stringContaining(mode==='network'?'Resultado incierto':'Admission denied'));
 expect(screen.queryByRole('button',{name:'Detener'})).toBeNull();
 expect(fetcher.mock.calls.filter(c=>String(c[0]).endsWith('/start'))).toHaveLength(1);
});
it('clears pending for a new session and ignores the previous start response',async()=>{
 let resolve!:(r:Response)=>void;
 const fetcher=transport(async()=>Response.json({status:'idle'}));
 const base=fetcher.getMockImplementation()!;
 fetcher.mockImplementation(async(input:RequestInfo|URL)=>String(input).endsWith('/start') ? new Promise<Response>(r=>{resolve=r;}) : base(input));
 const view=render(<TrainingView/>);
 await waitFor(()=>expect(start().disabled).toBe(false));fireEvent.click(start());
 confirmApiSession();view.rerender(<TrainingView/>);
 await waitFor(()=>expect(start().disabled).toBe(false));
 await act(async()=>resolve(Response.json({status:'started'})));
 expect(start().disabled).toBe(false);
 expect(screen.queryByRole('button',{name:'Detener'})).toBeNull();
});
const start=()=>screen.getByRole('button',{name:'Iniciar Entrenamiento Local (1 Modelo)'}) as HTMLButtonElement;
it('blocks duplicate start until initial progress resolves and restores the existing run without starting anything',async()=>{
 let resolve!:(r:Response)=>void;
 const fetcher=transport(()=>new Promise(r=>{resolve=r;}));
 render(<TrainingView/>);
 expect(start().disabled).toBe(true);
 await waitFor(()=>expect(resolve).toBeDefined());
 resolve(Response.json({status:'training',epoch:3,total_epochs:10,logs:[{message:'Recovered existing run',level:'info',timestamp:'12:00'}]}));
 await screen.findByText('Recovered existing run');
 expect((screen.getByRole('button',{name:/Entrenando Época 3/}) as HTMLButtonElement).disabled).toBe(true);
 expect(fetcher.mock.calls.some(c=>String(c[0]).endsWith('/start'))).toBe(false);
});
it('ignores progress JSON from a superseded session and checks the new session before enabling start',async()=>{
 let resolve!:(data:unknown)=>void;
 let first=true;
 transport(async()=>{
  if(first){first=false;return {ok:true,json:()=>new Promise(r=>{resolve=r;})} as Response;}
  return Response.json({status:'idle'});
 });
 const view=render(<TrainingView/>);
 await waitFor(()=>expect(resolve).toBeDefined());
 confirmApiSession();view.rerender(<TrainingView/>);
 resolve({status:'training',logs:[{message:'Foreign job',level:'info',timestamp:'12:00'}]});
 await waitFor(()=>expect(start().disabled).toBe(false));
 expect(screen.queryByText('Foreign job')).toBeNull();
});
it.each(['evaluating','training'])('keeps %s active through evaluation and polls until a terminal state without claiming stop was accepted',async initial=>{
 let status=initial;
 const stopMessage='No hay ningún entrenamiento activo para detener.';
 transport(async()=>Response.json({status,logs:[{message:status==='evaluating'?'Evaluation underway':'Training underway',level:'info',timestamp:'12:00'}]}),async()=>Response.json({status:'evaluating',message:stopMessage}));
 render(<TrainingView/>);
 await screen.findByText(initial==='evaluating'?'Evaluation underway':'Training underway');
 status='evaluating';
 await screen.findByText('Evaluation underway',{}, {timeout:2500});
 expect(screen.queryByRole('alert')).toBeNull();
 expect((screen.getByRole('button',{name:/Entrenando Época/}) as HTMLButtonElement).disabled).toBe(true);
 fireEvent.click(screen.getByRole('button',{name:'Detener'}));
 await screen.findByText(stopMessage);
 expect(screen.queryByText('Detención solicitada; esperando el estado final.')).toBeNull();
 expect(screen.queryByRole('button',{name:'Iniciar Entrenamiento Local (1 Modelo)'})).toBeNull();
 status='completed';
 await waitFor(()=>expect(start().disabled).toBe(false),{timeout:2500});
 await screen.findByText('Entrenamiento completado.');
});
it.each(['completed','failed','stopped','checkpoint_persisted'])('restores terminal %s without treating it as active',async status=>{
 transport(async()=>Response.json({status}));render(<TrainingView/>);
 await waitFor(()=>expect(start().disabled).toBe(false));
 expect(screen.queryByRole('button',{name:'Detener'})).toBeNull();
});
it('keeps start blocked on initial failure and allows explicit read-only retry',async()=>{
 let fail=true;
 transport(async()=>fail ? Response.json({}, {status:503}) : Response.json({status:'idle'}));
 render(<TrainingView/>);
 await screen.findByRole('alert');expect(start().disabled).toBe(true);
 fail=false;fireEvent.click(screen.getByText('Reintentar consulta de progreso'));
 await waitFor(()=>expect(start().disabled).toBe(false));
});
it('continues polling after cooperative stop until the actual terminal response',async()=>{
 let status='training';
 transport(async()=>Response.json({status}),async()=>Response.json({status:'stopping'}));
 render(<TrainingView/>);
 fireEvent.click(await screen.findByRole('button',{name:'Detener'}));
 await screen.findByText('Detención solicitada; esperando el estado final.');
 expect(screen.queryByRole('button',{name:'Iniciar Entrenamiento Local (1 Modelo)'})).toBeNull();
 status='stopped';
 await waitFor(()=>expect(start().disabled).toBe(false),{timeout:2500});
});
it('does not infer idle from an invalid initial body',async()=>{
 transport(async()=>Response.json({}));render(<TrainingView/>);
 await screen.findByText('Respuesta de progreso no válida.');
 expect(start().disabled).toBe(true);
});
it('handles a nontraining stop reply without claiming that a stop is pending',async()=>{
 let status='training';
 transport(async()=>Response.json({status}),async()=>{status='idle';return Response.json({status:'idle',message:'No hay ningún entrenamiento activo para detener.'});});
 render(<TrainingView/>);
 fireEvent.click(await screen.findByRole('button',{name:'Detener'}));
 await screen.findByText('No hay ningún entrenamiento activo para detener.');
 await waitFor(()=>expect(start().disabled).toBe(false),{timeout:2500});
 expect(screen.queryByText('Detención solicitada; esperando el estado final.')).toBeNull();
});
it.each([403,200])('shows stop error for HTTP/body failure (%s) and permits retry while polling remains active',async status=>{
 transport(async()=>Response.json({status:'training'}),async()=>Response.json({error:'Stop denied'}, {status}));
 render(<TrainingView/>);
 fireEvent.click(await screen.findByRole('button',{name:'Detener'}));
 await screen.findByText(/Stop denied/);
 expect((screen.getByRole('button',{name:'Detener'}) as HTMLButtonElement).disabled).toBe(false);
});
