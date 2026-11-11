import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, expect, it, vi } from 'vitest';
import TrainingView from '../TrainingView';

afterEach(()=>{cleanup();vi.unstubAllGlobals();});

it('dispatches an explicitly selected registered candidate without using imported preparation',async()=>{
 const transport=vi.fn(async(input:RequestInfo|URL)=>{
  const url=String(input);
  if(url.includes('/datasets'))return Response.json({datasets:[{id:'AvesChilenas',name:'AvesChilenas',record_id:'legacy:1',source_type:'legacy',audio_count:9,class_count:3,eligible:true,eligibility_state:'current_flow_compatible',reasons:[]}]});
  if(url.includes('/history'))return Response.json({history:[]});
  if(url.endsWith('/progress'))return Response.json({status:'idle'});
  return Response.json({status:'started'});
 });vi.stubGlobal('fetch',transport);
 render(<TrainingView/>);
 const start=screen.getByRole('button',{name:'Iniciar Entrenamiento Local (1 Modelo)'}) as HTMLButtonElement;
 const selector=screen.getByRole('combobox',{name:'Dataset para entrenamiento'});
 fireEvent.click(selector);
 fireEvent.click(await screen.findByRole('option',{name:'AvesChilenas'}));
 await waitFor(()=>expect(start.disabled).toBe(false));
 expect(selector.textContent).toBe('AvesChilenas');
 expect(screen.queryByRole('button',{name:'Preparar dataset'})).toBeNull();
 fireEvent.click(start);
 await waitFor(()=>expect(transport.mock.calls.some(call=>String(call[0]).endsWith('/start'))).toBe(true));
 const call=transport.mock.calls.find(call=>String(call[0]).endsWith('/start')) as unknown as [string,RequestInit];
 const body=JSON.parse(String(call[1].body));
 expect(body.dataset_name).toBe('AvesChilenas');
 expect(body).not.toHaveProperty('imported_dataset_id');
});
it('shows blocked registered sources with an incompatibility reason and never starts or prepares them',async()=>{
 const transport=vi.fn(async(input:RequestInfo|URL)=>{
  const url=String(input);
  if(url.includes('/datasets'))return Response.json({datasets:[{id:'../outside',name:'Invalid registered source',record_id:'legacy:23',source_type:'legacy',audio_count:0,class_count:null,eligible:false,eligibility_state:'blocked',reasons:['incompatible_configuration']}]});
  if(url.includes('/progress'))return Response.json({status:'idle'});
  if(url.includes('/history'))return Response.json({history:[]});
  return Response.json({});
 });vi.stubGlobal('fetch',transport);
 render(<TrainingView/>);
 fireEvent.click(await screen.findByRole('combobox',{name:'Dataset para entrenamiento'}));
 fireEvent.click(await screen.findByRole('option',{name:/Invalid registered source/}));
 expect(await screen.findByText(/Configuración incompatible/)).toBeTruthy();
 expect(screen.queryByRole('button',{name:'Preparar dataset'})).toBeNull();
 expect(screen.queryByRole('button',{name:'Gestionar particiones'})).toBeNull();
 const start=screen.getByRole('button',{name:'Iniciar Entrenamiento Local (1 Modelo)'}) as HTMLButtonElement;
 await waitFor(()=>expect(start.disabled).toBe(true));fireEvent.click(start);
 expect(transport.mock.calls.some(call=>String(call[0]).endsWith('/start'))).toBe(false);
 expect(screen.getByText(/independencia no está verificada/)).toBeTruthy();
 expect(screen.getByText(/Clases desconocidas/)).toBeTruthy();
});
