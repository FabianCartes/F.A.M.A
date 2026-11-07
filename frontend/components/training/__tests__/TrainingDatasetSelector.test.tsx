import { cleanup, fireEvent, render, screen } from '@testing-library/react';
import { afterEach, expect, it, vi } from 'vitest';
import TrainingDatasetSelector from '../TrainingDatasetSelector';

afterEach(()=>{cleanup();vi.unstubAllGlobals();});
it('keeps a catalog check failure distinct and retries reads only',async()=>{
 let fail=true;
 const transport=vi.fn(async()=>{if(fail)throw new TypeError('offline');return Response.json({datasets:[]});});vi.stubGlobal('fetch',transport);
 render(<TrainingDatasetSelector includeImported={false} onSelect={vi.fn()}/>);
 expect((await screen.findByRole('alert')).textContent).toContain('Error de comprobación');
 fail=false;fireEvent.click(screen.getByRole('button',{name:'Reintentar consulta'}));
 await screen.findByText('No hay datasets que coincidan con la búsqueda.');
 expect(transport).toHaveBeenCalledTimes(2);
 expect(transport.mock.calls.every(call=>(call as unknown as [string,RequestInit])[1]?.method==='GET')).toBe(true);
});
it('lists mixed sources and duplicate names with stable identities and preserves selection while searching',async()=>{
 vi.stubGlobal('fetch',vi.fn(async(input:RequestInfo|URL)=>Response.json({datasets:String(input).includes('include_unavailable')?[
  {id:'Smoke',name:'Smoke',record_id:'legacy:7',source_type:'legacy',audio_count:9,class_count:3,eligible:true,eligibility_state:'current_flow_compatible',reasons:[]},
  {id:'MaquinariaMinas',name:'MaquinariaMinas',record_id:'legacy:8',source_type:'legacy',audio_count:0,class_count:null,eligible:false,eligibility_state:'blocked',reasons:['incompatible_configuration']},
 ]:[{id:'own',name:'Smoke',source_type:'imported',eligible:false,reasons:['preparation_required'],preparations:[]}]})));
 const select=vi.fn();render(<TrainingDatasetSelector includeImported onSelect={select}/>);
 await screen.findByRole('option',{name:/MaquinariaMinas/});
 const choices=screen.getAllByRole('option',{name:/Smoke/});expect(choices).toHaveLength(2);
 expect(choices.map(o=>(o as HTMLOptionElement).value)).toEqual(['legacy:7','imported:own']);
 fireEvent.change(screen.getByLabelText('Dataset para entrenamiento'),{target:{value:'imported:own'}});
 expect(select).toHaveBeenLastCalledWith(expect.objectContaining({source_type:'imported',id:'own'}));
 fireEvent.change(screen.getByLabelText('Buscar dataset por nombre'),{target:{value:'mAqUiNaRiA'}});
 expect(screen.getAllByRole('option',{name:/MaquinariaMinas/})).toHaveLength(1);
 expect((screen.getByLabelText('Dataset para entrenamiento') as HTMLSelectElement).value).toBe('imported:own');
 expect(select).toHaveBeenCalledTimes(1);
});
