import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, expect, it, vi } from 'vitest';
import TrainingView from '../TrainingView';
import SessionBoundary from '@/components/auth/SessionBoundary';
vi.mock('next/navigation',()=>({useRouter:()=>({replace:vi.fn()})}));

afterEach(()=>{cleanup();vi.unstubAllGlobals();});

it('requires explicit preparation for Smoke despite eligible sync metadata and clears rejection on source switching',async()=>{
 const transport=vi.fn(async(input:RequestInfo|URL)=>{
  const url=String(input);
  if(url.includes('/auth/web/me'))return Response.json({id:1,email:'owner@example.test',nombre_completo:'Owner',rol:'investigador',activo:true});
  if(url.includes('include_imported'))return Response.json({datasets:[{source_type:'imported',id:'own',name:'Smoke',eligible:true,reasons:[],preparations:[]}]});
  if(url.includes('/datasets'))return Response.json({datasets:[{id:'Smoke',name:'Smoke',record_id:'legacy:7',source_type:'legacy',audio_count:9,class_count:3,eligible:true,eligibility_state:'current_flow_compatible',reasons:[]}]});
  if(url.endsWith('/snapshots'))return Response.json({id:'snap',dataset_id:'own',state:'ready',name:'Smoke',file_count:1});
  if(url.endsWith('/members'))return Response.json({snapshot_id:'snap',members:[]});
  if(url.endsWith('/preparations'))return Response.json({detail:{code:'split_impossible',message:'unsafe data'}},{status:422});
  if(url.includes('/progress'))return Response.json({status:'idle'});
  if(url.includes('/history'))return Response.json({history:[]});
  return Response.json({});
 });vi.stubGlobal('fetch',transport);
 render(<SessionBoundary><TrainingView/></SessionBoundary>);
 fireEvent.click(await screen.findByRole('combobox',{name:'Dataset para entrenamiento'}));
 await screen.findByRole('option',{name:/Smoke.*Privado/});
 fireEvent.click(screen.getByRole('option',{name:'Smoke — Privado'}));
 expect(screen.getByText(/Necesita preparación/)).toBeTruthy();
 expect((screen.getByRole('button',{name:'Iniciar Entrenamiento Local (1 Modelo)'}) as HTMLButtonElement).disabled).toBe(true);
 expect(transport.mock.calls.some(call=>String(call[0]).endsWith('/snapshots'))).toBe(false);
 fireEvent.click(screen.getByRole('button',{name:'Preparar dataset'}));
 expect(await screen.findByRole('alert')).toHaveProperty('textContent',expect.stringContaining('Grupos independientes insuficientes'));
 expect(screen.queryByText(/unsafe data/)).toBeNull();
 fireEvent.click(await screen.findByRole('combobox',{name:'Dataset para entrenamiento'}));
 fireEvent.click(screen.getByRole('option',{name:'Smoke — Compartido'}));
 expect(screen.queryByRole('region',{name:'Preparación importada'})).toBeNull();
 expect(screen.getByText(/Compatible con el flujo actual/)).toBeTruthy();
 fireEvent.click(await screen.findByRole('combobox',{name:'Dataset para entrenamiento'}));
 fireEvent.click(screen.getByRole('option',{name:'Smoke — Privado'}));
 expect(screen.queryByText(/Grupos independientes insuficientes/)).toBeNull();
 expect(screen.getByText(/Necesita preparación/)).toBeTruthy();
 expect(transport.mock.calls.filter(call=>String(call[0]).endsWith('/preparations'))).toHaveLength(1);
 expect(transport.mock.calls.some(call=>String(call[0]).endsWith('/start'))).toBe(false);
});
it('displays the retained legacy default reference before dispatching its original dataset name',async()=>{
 const transport=vi.fn(async(input:RequestInfo|URL)=>{
  const url=String(input);
  if(url.includes('/datasets'))return Response.json({datasets:[]});
  if(url.includes('/history'))return Response.json({history:[]});
  if(url.endsWith('/progress'))return Response.json({status:'idle'});
  return Response.json({status:'started'});
 });vi.stubGlobal('fetch',transport);
 render(<TrainingView/>);
 const start=screen.getByRole('button',{name:'Iniciar Entrenamiento Local (1 Modelo)'}) as HTMLButtonElement;
 await waitFor(()=>expect(start.disabled).toBe(false));
 const selector=screen.getByRole('combobox',{name:'Dataset para entrenamiento'});
 expect(selector.textContent).toContain('AvesChilenas');
 expect(selector.textContent).toContain('predeterminado');
 fireEvent.click(start);
 await waitFor(()=>expect(transport.mock.calls.some(call=>String(call[0]).endsWith('/start'))).toBe(true));
 const call=transport.mock.calls.find(call=>String(call[0]).endsWith('/start')) as unknown as [string,RequestInit];
 const body=JSON.parse(String(call[1].body));
 expect(body.dataset_name).toBe('AvesChilenas');
 expect(body).not.toHaveProperty('imported_dataset_id');
});
it('shows unsupported registered sources with an incompatibility reason and never starts or prepares them',async()=>{
 const transport=vi.fn(async(input:RequestInfo|URL)=>{
  const url=String(input);
  if(url.includes('/datasets'))return Response.json({datasets:[{id:'MaquinariaMinas',name:'MaquinariaMinas',record_id:'legacy:23',source_type:'legacy',audio_count:0,class_count:null,eligible:false,eligibility_state:'blocked',reasons:['incompatible_configuration']}]});
  if(url.includes('/progress'))return Response.json({status:'idle'});
  if(url.includes('/history'))return Response.json({history:[]});
  return Response.json({});
 });vi.stubGlobal('fetch',transport);
 render(<TrainingView/>);
 fireEvent.click(await screen.findByRole('combobox',{name:'Dataset para entrenamiento'}));
 fireEvent.click(await screen.findByRole('option',{name:/MaquinariaMinas/}));
 expect(await screen.findByText(/Configuración incompatible/)).toBeTruthy();
 expect(screen.queryByRole('button',{name:'Preparar dataset'})).toBeNull();
 const start=screen.getByRole('button',{name:'Iniciar Entrenamiento Local (1 Modelo)'}) as HTMLButtonElement;
 await waitFor(()=>expect(start.disabled).toBe(true));fireEvent.click(start);
 expect(transport.mock.calls.some(call=>String(call[0]).endsWith('/start'))).toBe(false);
 expect(screen.getByText(/independencia no está verificada/)).toBeTruthy();
 expect(screen.getByText(/Clases desconocidas/)).toBeTruthy();
});
